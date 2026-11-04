"""Build and validate features as a one-off job, without model training."""

import argparse
import logging
import tempfile
from pathlib import Path

import pandas as pd
import yaml

from src import config
from src.features.build_features import create_user_matrix, read_movies, read_ratings
from src.train_service.check_data import validate_matrix

logger = logging.getLogger(__name__)


def selected_part(override, params_path):
    if override is not None:
        value = override
    else:
        with params_path.open(encoding='utf-8') as stream:
            value = yaml.safe_load(stream)['split']['current_part']
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError('current_part must be a positive integer')
    return value


def prepare(current_part):
    paths = [config.RAW_DATA_DIR / 'movies.csv'] + [
        config.RATINGS_PARTS_DIR / config.RATINGS_PART_FILENAME.format(number)
        for number in range(1, current_part + 1)
    ]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValueError(
            'Missing local inputs; prepare/split the raw data first: '
            + ', '.join(missing)
        )

    logger.info('Preparing local rating parts 1..%s', current_part)
    ratings = pd.concat(
        [read_ratings(path.name, path.parent) for path in paths[1:]],
        ignore_index=True,
    )
    movies = read_movies(paths[0].name, paths[0].parent)
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
        'Data preparation passed: ratings=%s, users=%s, movies=%s, genres=%s',
        len(ratings),
        len(users),
        len(movies),
        len(movie_features.columns),
    )
    logger.info('Outputs: %s and %s', config.USER_MATRIX_PATH, config.MOVIE_MATRIX_PATH)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--current-part', type=int, help='Override split.current_part in params.yaml'
    )
    parser.add_argument(
        '--params', type=Path, default=config.PROJECT_ROOT / 'params.yaml'
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s'
    )
    try:
        prepare(selected_part(args.current_part, args.params))
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        logger.error('Data preparation failed: %s', error)
        raise SystemExit(1) from error


if __name__ == '__main__':
    main()
