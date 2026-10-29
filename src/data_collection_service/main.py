from fastapi import Depends, FastAPI

from data_collection_service.ingest import IngestRequest, ingest_up_to
from user_authentication_service.auth import require_admin

DESCRIPTION = """
Uploads the rating data part by part from the local machine to the DagsHub
storage bucket, to simulate data that arrives over time.
"""

api = FastAPI(title='Cloud Collection Service', description=DESCRIPTION)


@api.post('/ingest', dependencies=[Depends(require_admin)])
def ingest(request: IngestRequest | None = None):
    return ingest_up_to(request.requested_up_to if request else None)
