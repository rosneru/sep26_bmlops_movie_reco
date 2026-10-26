import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from src.config import (
    MISSING_GENRE,
    MOVIE_MATRIX_PATH,
    RANDOM_SEED,
    TEST_RATIO,
    TRAIN_RATIO,
    USER_MATRIX_PATH,
    VAL_RATIO,
)
from src.train_service.check_data import inspect_matrix


def read_matrix(path, id_column):
    """Clean recoverable row issues without writing intermediate files."""
    df = pd.read_csv(path)

    input_count = len(df)

    # Remove completely identical rows.
    duplicate_mask = df.duplicated(keep='first')
    duplicate_count = int(duplicate_mask.sum())

    df = df.loc[~duplicate_mask].copy()
    numeric_features, issues = inspect_matrix(
        df, id_column, binary=id_column == 'movieId'
    )
    bad_rows = np.zeros(len(df), dtype=bool)
    for mask in issues.values():
        bad_rows |= mask

    clean_df = df.loc[~bad_rows].copy()
    clean_features = numeric_features.loc[~bad_rows].copy()

    if clean_df.empty:
        raise ValueError(f'{path.name}: no valid rows remain')

    # Exact duplicates were already removed. Remaining duplicate IDs
    # therefore have conflicting feature values.
    conflicting_ids = clean_df[id_column].duplicated(keep=False)

    if conflicting_ids.any():
        raise ValueError(f'{path.name}: duplicate IDs with conflicting features')

    print(
        f'{path.name}: '
        f'input={input_count:,}, '
        f'exact_duplicates_removed={duplicate_count:,}, '
        f'invalid_rows_removed={int(bad_rows.sum()):,}, '
        f'kept={len(clean_df):,}'
    )

    return (
        clean_df[id_column].reset_index(drop=True),
        clean_features.reset_index(drop=True),
    )


def clean_and_normalize(ids, features, genre_columns):
    """Remove zero genre vectors and apply row-wise L2 normalization."""
    values = features.loc[:, genre_columns].to_numpy(dtype=np.float32)

    keep = np.any(values != 0, axis=1)
    removed = int((~keep).sum())
    ids = ids.loc[keep].reset_index(drop=True)
    values = values[keep]
    if len(values) == 0:
        raise ValueError('No rows remain after removing zero genre vectors')
    values = values / np.linalg.norm(values, axis=1, keepdims=True)

    return ids, values, removed


def split_users(user_ids, user_values):
    """Split users using the ratios defined in config.py."""
    ratios = [TRAIN_RATIO, VAL_RATIO, TEST_RATIO]

    if not all(np.isfinite(ratio) and 0 < ratio < 1 for ratio in ratios):
        raise ValueError('Split ratios must be finite and between 0 and 1')

    if not np.isclose(sum(ratios), 1.0, rtol=0, atol=1e-9):
        raise ValueError('TRAIN_RATIO + VAL_RATIO + TEST_RATIO must equal 1')
    if len(user_ids) < 10:
        raise ValueError('Need at least 10 users for this split')

    # Stable starting order makes splits independent of CSV row order.
    order = np.argsort(user_ids.to_numpy(), kind='stable')
    user_ids = user_ids.iloc[order].reset_index(drop=True)
    user_values = user_values[order]

    indices = np.arange(len(user_ids))

    train_idx, remaining_idx = train_test_split(
        indices,
        test_size=VAL_RATIO + TEST_RATIO,
        random_state=RANDOM_SEED,
        shuffle=True,
    )

    val_idx, test_idx = train_test_split(
        remaining_idx,
        test_size=TEST_RATIO / (VAL_RATIO + TEST_RATIO),
        random_state=RANDOM_SEED,
        shuffle=True,
    )

    splits = {
        'train': train_idx,
        'val': val_idx,
        'test': test_idx,
    }

    return user_ids, user_values, splits


# Mani's original approach saved prepared CSVs before training read them back.
# Keep the handoff in memory: preparation is quick, the data fits in RAM, and
# preparation and training run in the same job. Each run prepares the current
# processed inputs, avoiding intermediate CSV writes and stale prepared files.
# Reconsider persistent prepared datasets if preparation becomes expensive or
# needs to run as a separate job.
def prepare_data(user_path=USER_MATRIX_PATH, movie_path=MOVIE_MATRIX_PATH):
    """Return normalized user splits, movie features and preparation metadata."""
    user_ids, users = read_matrix(
        user_path,
        'userId',
    )
    movie_ids, movies = read_matrix(
        movie_path,
        'movieId',
    )

    if set(users.columns) != set(movies.columns):
        raise ValueError(
            'User and movie feature columns differ: '
            f'user-only={sorted(set(users.columns) - set(movies.columns))}, '
            f'movie-only={sorted(set(movies.columns) - set(users.columns))}'
        )

    genres = [column for column in users.columns if column != MISSING_GENRE]

    if not genres:
        raise ValueError('No usable genre columns')

    input_users = len(user_ids)
    input_movies = len(movie_ids)

    # Both matrices use exactly the same genre column order.
    user_ids, user_values, removed_users = clean_and_normalize(
        user_ids,
        users,
        genres,
    )

    movie_ids, movie_values, removed_movies = clean_and_normalize(
        movie_ids,
        movies,
        genres,
    )

    user_ids, user_values, splits = split_users(
        user_ids,
        user_values,
    )

    metadata = {
        'seed': RANDOM_SEED,
        'genres': genres,
        'normalization': 'row_l2',
        'split_unit': 'user',
        'split_method': 'train_test_split',
        'split_ratios': {
            'train': TRAIN_RATIO,
            'val': VAL_RATIO,
            'test': TEST_RATIO,
        },
        'actual_split_ratios': {
            name: len(rows) / len(user_ids) for name, rows in splits.items()
        },
        'input_users': input_users,
        'input_movies': input_movies,
        'removed_zero_users': removed_users,
        'removed_zero_movies': removed_movies,
        'split_counts': {name: len(rows) for name, rows in splits.items()},
        'output_movies': len(movie_ids),
        'label_type': 'genre_cosine_pseudo_label',
        'evaluation_scope': (
            'Genre similarity approximation for held-out users; '
            'not real preference or future interaction prediction.'
        ),
    }

    print(f'Removed users without genres: {removed_users}')
    print(f'Removed movies without genres: {removed_movies}')

    for name, rows in splits.items():
        print(f'{name} users: {len(rows):,}')

    print(f'Movies: {len(movie_ids):,}')
    print(f'Genres: {len(genres)}')
    metadata['source_files'] = [user_path.name, movie_path.name]
    return {
        'genres': genres,
        'user_features': {name: user_values[rows] for name, rows in splits.items()},
        'movies': movie_values,
        'metadata': metadata,
    }


if __name__ == '__main__':
    prepare_data()
