import os
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import config

DESCRIPTION = """
Uploads the rating data part by part from the local machine to the DagsHub
storage bucket, to simulate data that arrives over time.
"""

RATINGS_PARTS_DIR = Path(
    os.getenv('RATINGS_PARTS_DIR', config.RATINGS_PARTS_DIR)
)


MOVIES_PATH = Path(os.getenv('MOVIES_PATH', config.RAW_DATA_DIR / 'movies.csv'))
PARAMS_PATH = Path(
    os.getenv('PARAMS_PATH', config.PROJECT_ROOT / 'params.yaml')
)


def read_requested_part_from_params_file():
    """Return split.current_part from params.yaml."""
    with open(PARAMS_PATH) as f:
        return int(yaml.safe_load(f)['split']['current_part'])


def get_requested_part_from_argument_or_file(
    requested_part_arg: int | None,
) -> int:
    if requested_part_arg is not None:
        return requested_part_arg

    try:
        requested_part = read_requested_part_from_params_file()
        if requested_part < 1:
            raise HTTPException(
                status_code=500,
                detail=(
                    f'Invalid split.current_part={requested_part} in '
                    f'{PARAMS_PATH} (must be >= 1). Fix params.yaml or pass '
                    'requested_part in the request.'
                ),
            )
        return requested_part
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as e:
        raise HTTPException(
            status_code=500,
            detail=(
                f'No requested_part given and split.current_part could not be '
                f'determined from {PARAMS_PATH}: {type(e).__name__}: {e}'
            ),
        ) from e


def ingest_up_to(requested_part_arg: int | None):
    requested_part = get_requested_part_from_argument_or_file(
        requested_part_arg
    )
    target = list(range(1, requested_part + 1))
    part_files = sorted(RATINGS_PARTS_DIR.glob('ratings_*.csv'))
    return {
        'function': 'ingest_up_to',
        'requested_part': requested_part,
        'parts': part_files,
        'target': target,
    }


api = FastAPI(title='Cloud Collection Service', description=DESCRIPTION)


class IngestRequest(BaseModel):
    requested_part: int | None = Field(
        default=None,
        ge=1,
        description='After the call the bucket contains the parts '
        '1..requested_part. Default: split.current_part from params.yaml.',
    )

    # Only documentation: example body for /docs, no effect on validation
    model_config = {'json_schema_extra': {'examples': [{'requested_part': 2}]}}


@api.post('/ingest')
def ingest(request: IngestRequest | None = None):
    return ingest_up_to(request.requested_part if request else None)
