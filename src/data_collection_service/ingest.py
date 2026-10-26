import os
from pathlib import Path
from typing import Literal

import yaml
from fastapi import HTTPException
from pydantic import BaseModel, Field

import config
from data_collection_service.bucket_storage_client import (
    BucketStorageClient,
    StorageConfigError,
    StorageError,
)

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
    status: Literal['ingested', 'no_local_data']
    detail: str | None = None
    requested_up_to: int | None = None
    # Keys of the objects uploaded by this call
    uploaded: list[str] = []
    # Keys that were already in the bucket and were left unchanged
    skipped: list[str] = []


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

    if not MOVIES_PATH.is_file():
        raise HTTPException(
            status_code=500,
            detail=f'{MOVIES_PATH} is missing. Run "uv run dvc repro".',
        )

    # Local path and bucket key of every file the bucket should contain
    part_filenames = [
        config.RATINGS_PART_FILENAME.format(n) for n in target_numbers
    ]
    files = [(MOVIES_PATH, MOVIES_PATH.name)] + [
        (RATINGS_PARTS_DIR / name, BucketStorageClient.RATINGS_PREFIX + name)
        for name in part_filenames
    ]

    try:
        upload_client = BucketStorageClient.from_env()
    except StorageConfigError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    try:
        stored_numbers = upload_client.read_stored_part_numbers()
    except StorageError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    # The bucket is append-only, so it can't go back to fewer parts
    if stored_numbers and max(stored_numbers) > requested_up_to:
        raise HTTPException(
            status_code=409,
            detail=f'The bucket already contains parts up to '
            f'{max(stored_numbers)}, more than requested_up_to='
            f'{requested_up_to}. Stored parts are never removed.',
        )

    uploaded = []
    skipped = []
    try:
        for path, key in files:
            # Never overwrite: a stored object must stay as it is
            if upload_client.exists(key):
                skipped.append(key)
                continue
            upload_client.upload(path, key)
            uploaded.append(key)
    except StorageError as e:
        # Files uploaded so far stay in the bucket and are skipped on retry
        raise HTTPException(
            status_code=502,
            detail=f'Storage error after uploading {uploaded}: {e}',
        ) from e

    return IngestResponse(
        status='ingested',
        detail=f'Uploaded {len(uploaded)} files, '
        f'{len(skipped)} were already in the bucket.',
        requested_up_to=requested_up_to,
        uploaded=uploaded,
        skipped=skipped,
    )


if __name__ == '__main__':
    print(ingest_up_to(2))
