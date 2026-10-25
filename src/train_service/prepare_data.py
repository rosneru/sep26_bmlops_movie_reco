import json

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from src.config import (
    USER_MATRIX_PATH,
    MOVIE_MATRIX_PATH,
    TRAINING_DATA_DIR,
    RANDOM_SEED,
    MISSING_GENRE,
    TRAIN_RATIO,
    VAL_RATIO,
    TEST_RATIO,
)

def read_matrix(path, id_column):
    """Clean recoverable row issues and save rejected rows."""
    df = pd.read_csv(path)

    if id_column not in df.columns:
        raise ValueError(f'{path.name}: missing {id_column}')

    feature_columns = [
        column for column in df.columns
        if column != id_column
    ]

    if not feature_columns:
        raise ValueError(f'{path.name}: no feature columns')

    if df.empty:
        raise ValueError(f'{path.name}: empty dataset')

    input_count = len(df)

    # Remove completely identical rows.
    duplicate_mask = df.duplicated(keep='first')
    duplicate_count = int(duplicate_mask.sum())

    duplicates = df.loc[duplicate_mask].copy()
    duplicates['rejection_reason'] = 'exact_duplicate'

    df = df.loc[~duplicate_mask].copy()

    # Convert invalid feature strings to NaN so they can be identified.
    numeric_features = df[feature_columns].apply(
        pd.to_numeric,
        errors='coerce',
    )

    values = numeric_features.to_numpy(dtype=np.float64)

    missing_id = (
        df[id_column].isna()
        | df[id_column].astype(str).str.strip().eq('')
    ).to_numpy()

    invalid_features = ~np.isfinite(values).all(axis=1)

    out_of_range = (
        np.isfinite(values)
        & ((values < 0) | (values > 1))
    ).any(axis=1)

    # Movie genre features must be binary before normalization.
    non_binary = np.zeros(len(df), dtype=bool)

    if id_column == 'movieId':
        non_binary = (
            np.isfinite(values)
            & ~np.isin(values, [0, 1])
        ).any(axis=1)

    reasons = []

    for row in range(len(df)):
        row_reasons = []

        if missing_id[row]:
            row_reasons.append('missing_id')

        if invalid_features[row]:
            row_reasons.append('missing_or_invalid_feature')

        if out_of_range[row]:
            row_reasons.append('feature_outside_0_1')

        if non_binary[row]:
            row_reasons.append('non_binary_movie_feature')

        reasons.append(';'.join(row_reasons))

    bad_rows = (
        missing_id
        | invalid_features
        | out_of_range
        | non_binary
    )

    rejected = df.loc[bad_rows].copy()
    rejected['rejection_reason'] = np.asarray(reasons)[bad_rows]

    # Save rejected rows, preserving their original values.
    rejected_dir = TRAINING_DATA_DIR / 'rejected'
    rejected_dir.mkdir(parents=True, exist_ok=True)

    rejected_path = rejected_dir / f'{path.stem}_rejected.csv'

    pd.concat(
        [duplicates, rejected],
        ignore_index=True,
    ).to_csv(rejected_path, index=False)

    clean_df = df.loc[~bad_rows].copy()
    clean_features = numeric_features.loc[~bad_rows].copy()

    if clean_df.empty:
        raise ValueError(
            f'{path.name}: no valid rows remain; '
            f'see {rejected_path}'
        )

    # Exact duplicates were already removed. Remaining duplicate IDs
    # therefore have conflicting feature values.
    conflicting_ids = clean_df[id_column].duplicated(keep=False)

    if conflicting_ids.any():
        conflict_path = (
            rejected_dir / f'{path.stem}_conflicting_ids.csv'
        )

        clean_df.loc[conflicting_ids].to_csv(
            conflict_path,
            index=False,
        )

        raise ValueError(
            f'{path.name}: duplicate IDs with conflicting features; '
            f'see {conflict_path}'
        )

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
    values = features.loc[:, genre_columns].to_numpy(
        dtype=np.float32
    )

    keep = np.any(values != 0, axis=1)
    removed = int((~keep).sum())

    ids = ids.loc[keep].reset_index(drop=True)
    values = values[keep]

    if len(values) == 0:
        raise ValueError(
            'No rows remain after removing zero genre vectors'
        )

    # Each row is normalized independently.
    # No statistics are learned from validation or test users.
    # Because of cosine simularity, we use L2-Norm
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    values = values / norms

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


def save_matrix(filename, id_column, ids, values, genres):
    """Save IDs and their corresponding normalized genre vectors."""
    result = pd.DataFrame(values, columns=genres)
    result.insert(0, id_column, ids.to_numpy())

    result.to_csv(
        TRAINING_DATA_DIR / filename,
        index=False,
    )


def main():
    user_ids, users = read_matrix(
        USER_MATRIX_PATH,
        'userId',
    )
    movie_ids, movies = read_matrix(
        MOVIE_MATRIX_PATH,
        'movieId',
    )

    if set(users.columns) != set(movies.columns):
        raise ValueError(
            'User and movie feature columns differ: '
            f'user-only={sorted(set(users.columns) - set(movies.columns))}, '
            f'movie-only={sorted(set(movies.columns) - set(users.columns))}'
        )

    genres = [
        column
        for column in users.columns
        if column != MISSING_GENRE
    ]

    if not genres:
        raise ValueError('No usable genre columns')

    # Validate binary movie features before normalization.
    if not np.isin(movies.to_numpy(), [0, 1]).all():
        raise ValueError('Movie genre features must be binary')

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

    TRAINING_DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    for name, rows in splits.items():
        save_matrix(
            filename=f'users_{name}.csv',
            id_column='userId',
            ids=user_ids.iloc[rows],
            values=user_values[rows],
            genres=genres,
        )

    save_matrix(
        filename='movies.csv',
        id_column='movieId',
        ids=movie_ids,
        values=movie_values,
        genres=genres,
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
            name: len(rows) / len(user_ids)
            for name, rows in splits.items()
        },
        'input_users': input_users,
        'input_movies': input_movies,
        'removed_zero_users': removed_users,
        'removed_zero_movies': removed_movies,
        'split_counts': {
            name: len(rows)
            for name, rows in splits.items()
        },
        'output_movies': len(movie_ids),
        'label_type': 'genre_cosine_pseudo_label',
        'evaluation_scope': (
            'Genre similarity approximation for held-out users; '
            'not real preference or future interaction prediction.'
        ),
    }

    metadata_path = TRAINING_DATA_DIR / 'metadata.json'
    metadata_path.write_text(
        json.dumps(metadata, indent=2),
        encoding='utf-8',
    )

    print(f'Removed users without genres: {removed_users}')
    print(f'Removed movies without genres: {removed_movies}')

    for name, rows in splits.items():
        print(f'{name} users: {len(rows):,}')

    print(f'Movies: {len(movie_ids):,}')
    print(f'Genres: {len(genres)}')
    print(f'Saved to: {TRAINING_DATA_DIR}')


if __name__ == '__main__':
    main()
