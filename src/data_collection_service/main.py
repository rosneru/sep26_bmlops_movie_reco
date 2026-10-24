from fastapi import FastAPI
from pydantic import BaseModel, Field

from data_collection_service.ingest import ingest_up_to

DESCRIPTION = """
Uploads the rating data part by part from the local machine to the DagsHub
storage bucket, to simulate data that arrives over time.
"""

api = FastAPI(title='Cloud Collection Service', description=DESCRIPTION)


class IngestRequest(BaseModel):
    requested_up_to: int | None = Field(
        default=None,
        ge=1,
        description='After the call the bucket contains the parts '
        '1..requested_up_to. Default: split.current_part from params.yaml.',
    )

    # Only documentation: example body for /docs, no effect on validation
    model_config = {'json_schema_extra': {'examples': [{'requested_up_to': 2}]}}


@api.post('/ingest')
def ingest(request: IngestRequest | None = None):
    return ingest_up_to(request.requested_up_to if request else None)
