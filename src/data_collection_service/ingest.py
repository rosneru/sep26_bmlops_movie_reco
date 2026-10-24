import os
from pathlib import Path

import yaml
from fastapi import HTTPException

import config

RATINGS_PARTS_DIR = Path(
    os.getenv('RATINGS_PARTS_DIR', config.RATINGS_PARTS_DIR)
)


MOVIES_PATH = Path(os.getenv('MOVIES_PATH', config.RAW_DATA_DIR / 'movies.csv'))
PARAMS_PATH = Path(
    os.getenv('PARAMS_PATH', config.PROJECT_ROOT / 'params.yaml')
)


def read_requested_up_to_from_params_file():
    """Return split.current_part from params.yaml."""
    with open(PARAMS_PATH) as f:
        return int(yaml.safe_load(f)['split']['current_part'])


def get_requested_up_to_from_argument_or_file(
    requested_up_to_arg: int | None,
) -> int:
    if requested_up_to_arg is not None:
        return requested_up_to_arg

    try:
        requested_up_to = read_requested_up_to_from_params_file()
        if requested_up_to < 1:
            raise HTTPException(
                status_code=500,
                detail=(
                    f'Invalid split.current_part={requested_up_to} in '
                    f'{PARAMS_PATH} (must be >= 1). Fix params.yaml or pass '
                    'requested_up_to in the request.'
                ),
            )
        return requested_up_to
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as e:
        raise HTTPException(
            status_code=500,
            detail=(
                f'No requested_up_to given and split.current_part could not be '
                f'determined from {PARAMS_PATH}: {type(e).__name__}: {e}'
            ),
        ) from e


def ingest_up_to(requested_up_to_arg: int | None):
    requested_up_to = get_requested_up_to_from_argument_or_file(
        requested_up_to_arg
    )
    target = list(range(1, requested_up_to + 1))
    part_files = sorted(RATINGS_PARTS_DIR.glob('ratings_*.csv'))
    return {
        'function': 'ingest_up_to',
        'requested_up_to': requested_up_to,
        'requested_up_to_arg': requested_up_to_arg,
        'target': target,
    }
