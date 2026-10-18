import logging
import os
from pathlib import Path

import requests

from config import RAW_DATA_DIR


def import_raw_data(raw_data_dir, filenames, base_url):
    """
    Download files from a remote location into a local directory.

    Each file is fetched from ``<base_url>/<filename>`` and written to
    ``raw_data_dir/<filename>``, overwriting existing files.

    Parameters
    ----------
    raw_data_dir : pathlib.Path
        Target directory. Created if it does not exist.
    filenames : Iterable[str]
        Names of the files to download.
    base_url : str
        URL of the remote folder containing the files, with or without
        a trailing slash.

    Raises
    ------
    requests.HTTPError
        If a download fails (4xx/5xx status code).
    """
    raw_data_dir = Path(raw_data_dir)
    os.makedirs(raw_data_dir, exist_ok=True)
    for filename in filenames:
        input_url = f'{base_url.rstrip("/")}/{filename}'
        output_file = raw_data_dir / filename

        print(f'Downloading {input_url} as {output_file.name}')
        response = requests.get(input_url)

        #  In case of an error stop the pipeline with a clear error message
        response.raise_for_status()

        # Write output file
        with open(output_file, 'wb') as f:
            f.write(response.content)


def main(
    raw_data_dir=RAW_DATA_DIR,
    # NOTE: For a start we only need 'movies.csv' and 'ratings.csv'
    filenames=[
        # 'genome-scores.csv',
        # 'genome-tags.csv',
        # 'links.csv',
        'movies.csv',
        'ratings.csv',
        # 'README.txt',
        # 'tags.csv',
    ],
    base_url=(
        'https://mlops-project-db.s3.eu-west-1.amazonaws.com/movie_recommandation/'
    ),
):
    """Download the raw data files into raw_data_dir."""
    import_raw_data(raw_data_dir, filenames, base_url)
    logger = logging.getLogger(__name__)
    logger.info('making raw data set')


if __name__ == '__main__':
    log_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_fmt)

    main()
