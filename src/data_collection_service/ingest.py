import os
from pathlib import Path
from typing import Literal

import yaml
from fastapi import HTTPException
from pydantic import BaseModel, Field

import config

RATINGS_PARTS_DIR = Path(
    os.getenv('RATINGS_PARTS_DIR', config.RATINGS_PARTS_DIR)
)


MOVIES_PATH = Path(os.getenv('MOVIES_PATH', config.RAW_DATA_DIR / 'movies.csv'))
PARAMS_PATH = Path(
    os.getenv('PARAMS_PATH', config.PROJECT_ROOT / 'params.yaml')
)


class IngestRequest(BaseModel):
    requested_up_to: int | None = Field(
        default=None,
        ge=1,
        description='After the call the bucket contains the parts '
        '1..requested_up_to. Default: split.current_part from params.yaml.',
    )

    # Only documentation: example body for /docs, no effect on validation
    model_config = {'json_schema_extra': {'examples': [{'requested_up_to': 2}]}}


class IngestResponse(BaseModel):
    status: Literal['planned', 'no_local_data']
    detail: str | None = None
    requested_up_to: int | None = None
    files: list[str] = []


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


def ingest_up_to(requested_up_to_arg: int | None) -> IngestResponse:
    requested_up_to = get_requested_up_to_from_argument_or_file(
        requested_up_to_arg
    )
    # Get all available part file names
    part_files = sorted(RATINGS_PARTS_DIR.glob('ratings_*.csv'))

    # And extract the numbers
    part_numbers = [int(p.stem.removeprefix('ratings_')) for p in part_files]
    if not part_numbers:
        # TODO: logger.warning
        return IngestResponse(
            status='no_local_data',
            detail=f'No rating parts found in {RATINGS_PARTS_DIR}. '
            'Run "uv run dvc repro split_data" to create them.',
            files=[],
            requested_up_to=requested_up_to,
        )

    # Get the the range of parts that we want to have on the S3 target
    target_numbers = list(range(1, requested_up_to + 1))

    # Check if there are part files missing locally. This would prevent to
    # fulfil the request.
    missing = sorted(set(target_numbers) - set(part_numbers))
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f'Local rating parts {missing} are missing. '
            'Run "uv run dvc repro split_data".',
        )

    files_to_be_uploaded = ['movies.csv'] + [
        config.RATINGS_PART_FILENAME.format(n) for n in target_numbers
    ]

    print('FILES TO BE UPLOADED')
    print('====================')
    print(files_to_be_uploaded)
    print('====================')

    # TODO: As soon as saving is built in, 'Uploading' would be inappropriate.
    # The endpoint doesn't respond until everything has been uploaded. Then the
    # status is 'ingested' and the detail is 'Uploaded 3 files.', meaning it's
    # in the past tense.
    return IngestResponse(
        status='planned',
        detail=f'Uploading {len(files_to_be_uploaded)} files..',
        files=files_to_be_uploaded,
        requested_up_to=requested_up_to,
    )


if __name__ == '__main__':
    print(ingest_up_to(2))
