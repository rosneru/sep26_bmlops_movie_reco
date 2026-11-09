from fastapi import Depends, FastAPI

from data_collection_service.ingest import IngestRequest, ingest_up_to
from user_authentication_service.auth import require_admin
from user_authentication_service.auth import router as auth_router

DESCRIPTION = """
Uploads the rating data part by part from the local machine to the DagsHub
storage bucket, to simulate data that arrives over time.
"""

api = FastAPI(title='Cloud Collection Service', description=DESCRIPTION)
api.include_router(auth_router)


@api.post('/ingest', dependencies=[Depends(require_admin)])
def ingest(request: IngestRequest | None = None):
    if request is None:
        return ingest_up_to(None)
    return ingest_up_to(request.requested_up_to, next_part=request.next_part)
