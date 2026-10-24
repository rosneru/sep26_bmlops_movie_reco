import os
from pathlib import Path

from fastapi import FastAPI
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


def ingest_up_to(up_to_part):
    pass


api = FastAPI(title='Cloud Collection Service', description=DESCRIPTION)


class IngestRequest(BaseModel):
    up_to_part: int | None = Field(
        default=None,
        ge=1,
        description='After the call the bucket contains the parts '
        '1..up_to_part. Default: split.current_part from params.yaml.',
    )

    model_config = {'json_schema_extra': {'examples': [{'up_to_part': 2}]}}


@api.post('/ingest')
def ingest(request: IngestRequest | None = None):
    return ingest_up_to(request.up_to_part if request else None)
