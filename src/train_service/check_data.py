import numpy as np
import pandas as pd

from src.config import USER_MATRIX_PATH, MOVIE_MATRIX_PATH


def load_matrix(path, id_column):
    filename = path.name

    if not path.is_file():
        raise FileNotFoundError(f'File not found: {path}')

    df = pd.read_csv(path)

    if id_column not in df.columns:
        raise ValueError(f'{filename}: missing {id_column}')

    if df.empty:
        raise ValueError(f'{filename}: empty dataset')

    if df[id_column].isna().any():
        raise ValueError(f'{filename}: missing IDs')

    if df[id_column].duplicated().any():
        raise ValueError(f'{filename}: duplicate IDs')

    features = df.drop(columns=id_column).apply(
        pd.to_numeric, errors='raise'
    )

    if features.shape[1] == 0:
        raise ValueError(f'{filename}: no feature columns')

    values = features.to_numpy(dtype=np.float32)

    if not np.isfinite(values).all():
        raise ValueError(
            f'{filename}: missing or infinite feature values'
        )

    if (values < 0).any() or (values > 1).any():
        raise ValueError(
            f'{filename}: feature values outside [0, 1]'
        )

    print(
        f'{filename}: '
        f'{len(df):,} rows, {len(features.columns)} features'
    )

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
        column
        for column in users.columns
        if column != '(no genres listed)'
    ]

    if not genre_columns:
        raise ValueError('No usable genre columns')

    user_genres = users[genre_columns]
    movie_genres = movies[genre_columns]

    if not np.isin(movie_genres.to_numpy(), [0, 1]).all():
        raise ValueError('Movie genre features must be binary')

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