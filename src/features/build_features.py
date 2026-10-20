import logging
import os

import click
import pandas as pd

from config import (
    MOVIE_MATRIX_PATH,
    PROCESSED_DATA_DIR,
    RATINGS_PART_FILENAME,
    RATINGS_PARTS_DIR,
    RAW_DATA_DIR,
    USER_MATRIX_PATH,
)


def read_ratings(ratings_csv, data_dir=RAW_DATA_DIR) -> pd.DataFrame:
    """
    Reads a ratings.csv from the data/raw folder.

    Parameters
    -------
    ratings_csv : str
        The csv file that will be read. Must be corresponding to a rating file.

    Returns
    -------
    pd.DataFrame
        The ratings DataFrame. Its columns are, in order:
        "userId", "movieId", "rating" and "timestamp".
    """
    data = pd.read_csv(os.path.join(data_dir, ratings_csv))
    return data


def read_movies(movies_csv, data_dir=RAW_DATA_DIR) -> pd.DataFrame:
    """
    Reads a movies.csv from the data/raw folder.

    Parameters
    -------
    movies_csv : str
        The csv file that will be read. Must be corresponding to a movie file.

    Returns
    -------
    pd.DataFrame
        The movies DataFrame. Its columns are binary and represent the movie genres.
    """
    # Read the CSV file
    df = pd.read_csv(os.path.join(data_dir, movies_csv))

    # Split the 'genres' column into individual genres
    genres = df['genres'].str.get_dummies(sep='|')

    # Concatenate the original movieId and title columns with the binary genre columns
    result_df = pd.concat([df[['movieId', 'title']], genres], axis=1)
    return result_df


def create_user_matrix(ratings, movies):
    # Only keep which user rated which movie and the genres of each movie.
    # Note: "rating" and "timestamp" are not used by the user matrix.
    # Dropping them (and storing the genres as uint8) before the merge keeps
    # the memory usage low for millions of ratings.
    genres = movies.drop(columns=['movieId', 'title']).astype('uint8')
    movies = pd.concat([movies[['movieId']], genres], axis=1)

    # merge the 2 tables together
    movie_ratings = ratings[['userId', 'movieId']].merge(
        movies, on='movieId', how='inner'
    )
    movie_ratings = movie_ratings.drop('movieId', axis=1)

    # Calculate user_matrix
    user_matrix = movie_ratings.groupby('userId').agg(
        'mean',
    )

    return user_matrix


@click.command()
@click.option('--current-part', type=click.IntRange(min=1), required=True)
def main(current_part):
    """Build user and movie matrix from the rating parts 1..current_part."""
    logger = logging.getLogger(__name__)

    # read user_ratings and movies tables
    user_ratings = pd.concat(
        [
            read_ratings(
                RATINGS_PART_FILENAME.format(number), RATINGS_PARTS_DIR
            )
            for number in range(1, current_part + 1)
        ],
        ignore_index=True,
    )
    movies = read_movies('movies.csv')
    logger.info(
        f'Using {len(user_ratings)} ratings from parts 1..{current_part}'
    )

    user_matrix = create_user_matrix(user_ratings, movies)
    movies = movies.drop('title', axis=1)

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    movies.to_csv(MOVIE_MATRIX_PATH, index=False)
    user_matrix.to_csv(USER_MATRIX_PATH)
    logger.info(f'Built user matrix for {len(user_matrix)} users')


if __name__ == '__main__':
    log_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_fmt)

    main()
