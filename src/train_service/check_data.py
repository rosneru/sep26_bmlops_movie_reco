"""Shared data checks and the optional diagnostic command."""

import numpy as np
import pandas as pd

from src.config import MISSING_GENRE, MOVIE_MATRIX_PATH, USER_MATRIX_PATH


def inspect_matrix(frame, id_column, *, binary=False):
    if id_column not in frame.columns:
        raise ValueError(f'Missing {id_column}')
    columns = [name for name in frame.columns if name != id_column]
    if frame.empty or not columns:
        raise ValueError('Matrix must have rows and feature columns')
    features = frame[columns].apply(pd.to_numeric, errors='coerce')
    values = features.to_numpy(dtype=np.float64)
    issues = {
        'missing_id': (
            frame[id_column].isna() | frame[id_column].astype(str).str.strip().eq('')
        ).to_numpy(),
        'missing_or_invalid_feature': ~np.isfinite(values).all(axis=1),
        'feature_outside_0_1': (
            np.isfinite(values) & ((values < 0) | (values > 1))
        ).any(axis=1),
        'non_binary_movie_feature': (
            (np.isfinite(values) & ~np.isin(values, [0, 1])).any(axis=1)
            if binary
            else np.zeros(len(frame), dtype=bool)
        ),
    }
    return features, issues


def validate_matrix(frame, id_column, *, binary=False):
    features, issues = inspect_matrix(frame, id_column, binary=binary)
    errors = [name for name, mask in issues.items() if mask.any()]
    if errors:
        raise ValueError('Invalid matrix: ' + ', '.join(errors))
    if frame[id_column].duplicated().any():
        raise ValueError(f'Duplicate {id_column} values')
    return features


def load_matrix(path, id_column):
    features = validate_matrix(
        pd.read_csv(path), id_column, binary=id_column == 'movieId'
    )
    print(f'{path.name}: {len(features):,} rows, {len(features.columns)} features')
    return features


def main():
    users = load_matrix(USER_MATRIX_PATH, 'userId')
    movies = load_matrix(MOVIE_MATRIX_PATH, 'movieId')

    user_columns = set(users.columns)
    movie_columns = set(movies.columns)

    if user_columns != movie_columns:
        raise ValueError(
            'Feature mismatch: '
            f'user-only={sorted(user_columns - movie_columns)}, '
            f'movie-only={sorted(movie_columns - user_columns)}'
        )

    # Align features by column name.
    movies = movies.loc[:, users.columns]

    # Missing genre information is not a meaningful genre.
    genre_columns = [
        column for column in users.columns if column != MISSING_GENRE
    ]

    if not genre_columns:
        raise ValueError('No usable genre columns')

    user_genres = users[genre_columns]
    movie_genres = movies[genre_columns]

    zero_users = int((user_genres.sum(axis=1) == 0).sum())
    zero_movies = int((movie_genres.sum(axis=1) == 0).sum())

    if zero_users == len(users):
        raise ValueError('All users have zero usable genre features')

    if zero_movies == len(movies):
        raise ValueError('All movies have zero usable genre features')

    print('Usable genres:', genre_columns)
    print('Users with no usable genres:', zero_users)
    print('Movies with no usable genres:', zero_movies)
    print(
        'Distinct movie genre profiles:',
        len(movie_genres.drop_duplicates()),
    )
    print('Data checks passed.')


if __name__ == '__main__':
    main()
