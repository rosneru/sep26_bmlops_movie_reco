from fastapi import FastAPI

from data_collection_service.ingest import IngestRequest, ingest_up_to

DESCRIPTION = """
Uploads the rating data part by part from the local machine to the DagsHub
storage bucket, to simulate data that arrives over time.
"""

api = FastAPI(title='Cloud Collection Service', description=DESCRIPTION)


@api.post('/ingest')
def ingest(request: IngestRequest | None = None):
    return ingest_up_to(request.requested_up_to if request else None)
