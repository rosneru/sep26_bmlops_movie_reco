"""Build and validate features from the bucket data, without model training."""

import argparse
import logging
import tempfile
from pathlib import Path

import pandas as pd

from src import config
from src.data_collection_service.bucket_storage_client import (
    BucketStorageClient,
    StorageConfigError,
    StorageError,
)
from src.features.build_features import create_user_matrix, read_movies, read_ratings
from src.train_service.check_data import validate_matrix

logger = logging.getLogger(__name__)

MOVIES_KEY = 'movies.csv'


def select_part_numbers(stored, up_to=None):
    """
    Return the numbers 1..n of the rating parts to prepare.

    n is 'up_to' if given, otherwise the highest part in the bucket. The
    ratings are cumulative, so every part from 1 to n must be stored.
    """
    if up_to is not None and up_to < 1:
        raise ValueError('--up-to must be a positive integer')
    if not stored:
        raise ValueError(
            'The bucket contains no rating parts; ingest data via the '
            'data collection service first'
        )
    last = max(stored) if up_to is None else up_to
    numbers = list(range(1, last + 1))
    if not set(numbers) <= set(stored):
        raise ValueError(
            f'Rating parts 1..{last} are required, but the bucket contains '
            f'only the parts {sorted(stored)}'
        )
    return numbers


def download_inputs(client, part_numbers, target_dir):
    """Download movies.csv and the given rating parts into target_dir."""
    client.download(MOVIES_KEY, target_dir / MOVIES_KEY)
    for number in part_numbers:
        filename = config.RATINGS_PART_FILENAME.format(number)
        client.download(
            BucketStorageClient.RATINGS_PREFIX + filename, target_dir / filename
        )


def prepare(input_dir, part_numbers):
    """Build, validate and write the feature matrices from the files in input_dir."""
    ratings = pd.concat(
        [
            read_ratings(config.RATINGS_PART_FILENAME.format(number), input_dir)
            for number in part_numbers
        ],
        ignore_index=True,
    )
    movies = read_movies(MOVIES_KEY, input_dir)
    users = create_user_matrix(ratings, movies).reset_index()
    movies = movies.drop(columns=['title'])

    # Apply the existing project checks before replacing either output file.
    user_features = validate_matrix(users, 'userId')
    movie_features = validate_matrix(movies, 'movieId', binary=True)
    if list(user_features.columns) != list(movie_features.columns):
        raise ValueError('User and movie genre columns or their order differ')
    genres = [name for name in movie_features if name != config.MISSING_GENRE]
    if not genres:
        raise ValueError('No usable genre columns')
    if not user_features[genres].ne(0).any(axis=None):
        raise ValueError('All users have zero usable genre features')
    if not movie_features[genres].ne(0).any(axis=None):
        raise ValueError('All movies have zero usable genre features')

    config.PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Stage both complete files first. Each replacement is atomic, but the pair
    # is not a transaction: run preparation serially and train only on success.
    with tempfile.TemporaryDirectory(
        dir=config.PROCESSED_DATA_DIR, prefix='.preparation-'
    ) as temporary:
        temporary = Path(temporary)
        users.to_csv(temporary / 'user_matrix.csv', index=False)
        movies.to_csv(temporary / 'movie_matrix.csv', index=False)
        (temporary / 'user_matrix.csv').replace(config.USER_MATRIX_PATH)
        (temporary / 'movie_matrix.csv').replace(config.MOVIE_MATRIX_PATH)

    logger.info(
        'Data preparation passed: parts=1..%s, ratings=%s, users=%s, movies=%s, '
        'genres=%s',
        part_numbers[-1],
        len(ratings),
        len(users),
        len(movies),
        len(movie_features.columns),
    )
    logger.info('Outputs: %s and %s', config.USER_MATRIX_PATH, config.MOVIE_MATRIX_PATH)


def run(up_to=None):
    client = BucketStorageClient.from_env()
    part_numbers = select_part_numbers(client.read_stored_part_numbers(), up_to)
    logger.info(
        'Preparing rating parts 1..%s from bucket %s', part_numbers[-1], client.bucket
    )
    with tempfile.TemporaryDirectory(prefix='bucket-inputs-') as input_dir:
        input_dir = Path(input_dir)
        download_inputs(client, part_numbers, input_dir)
        prepare(input_dir, part_numbers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--up-to',
        type=int,
        help='Use only the rating parts 1..UP_TO (default: all parts in the bucket)',
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s'
    )
    try:
        run(args.up_to)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        StorageConfigError,
        StorageError,
    ) as error:
        logger.error('Data preparation failed: %s', error)
        raise SystemExit(1) from error


if __name__ == '__main__':
    main()
