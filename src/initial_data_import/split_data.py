import logging
from itertools import pairwise
from pathlib import Path

import click
import numpy as np
import pandas as pd

from config import RATINGS_PART_FILENAME, RATINGS_PARTS_DIR, RAW_DATA_DIR


def split_ratings(ratings, n_parts):
    """
    Split the ratings chronologically into parts of (nearly) equal size.

    The ratings are sorted by timestamp, so part 1 contains the oldest and
    the last part the newest ratings. This simulates data that arrives over
    time.

    Parameters
    ----------
    ratings : pd.DataFrame
        The ratings DataFrame with a "timestamp" column.
    n_parts : int
        Number of parts.

    Returns
    -------
    list[pd.DataFrame]
        The parts, ordered from oldest to newest.
    """
    ratings = ratings.sort_values('timestamp', kind='stable')
    bounds = np.linspace(0, len(ratings), n_parts + 1).astype(int)
    return [ratings.iloc[start:end] for start, end in pairwise(bounds)]


@click.command()
@click.option('--n-parts', type=click.IntRange(min=1), required=True)
def main(n_parts):
    """Split data/raw/ratings.csv into n_parts files in RATINGS_PARTS_DIR."""
    logger = logging.getLogger(__name__)

    ratings = pd.read_csv(RAW_DATA_DIR / 'ratings.csv')
    parts = split_ratings(ratings, n_parts)

    # Remove parts of a previous run, which may have used more parts
    parts_dir = Path(RATINGS_PARTS_DIR)
    parts_dir.mkdir(parents=True, exist_ok=True)
    for old_file in parts_dir.glob(RATINGS_PART_FILENAME.replace('{:02d}', '*')):
        old_file.unlink()

    for number, part in enumerate(parts, start=1):
        output_file = parts_dir / RATINGS_PART_FILENAME.format(number)
        part.to_csv(output_file, index=False)

        first, last = pd.to_datetime(part['timestamp'].iloc[[0, -1]], unit='s')
        logger.info(
            f'{output_file.name}: {len(part)} ratings '
            f'from {first.date()} to {last.date()}'
        )


if __name__ == '__main__':
    log_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_fmt)

    main()
