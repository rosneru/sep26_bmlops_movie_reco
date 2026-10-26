# Data collection service

Simulates data that arrives over time: uploads `movies.csv` and the rating parts `1..n` from `data/interim/ratings_parts/` to the repo bucket *DagsHub Storage*. The uploaded files are shown on the DagsHub repo page under *Storage Buckets*.

No pipeline stage reads from the bucket yet.

Run the commands below from the repository root.

## Prerequisites

1. The local rating parts: `uv run dvc repro split_data` (see the root README).
2. A DagsHub token (see the root README, section 1). Create `.env` if it does not exist yet, and set `DAGSHUB_TOKEN` there:

   ```bash
   cp .env.example .env
   ```

## Run

```bash
make run-dcs        # start the API on port 8001
make test-dcs-part  # upload the parts 1..2
```

The API docs are at <http://localhost:8001/docs>.

`POST /ingest` takes an optional `requested_up_to`. Without it, `split.current_part` from `params.yaml` is used.

## Behaviour

- Files in the bucket are never overwritten or removed. Files already there are skipped.
- Requesting fewer parts than stored returns `409`.
- `requested_up_to < 1` returns `422`.

## Check the bucket

Print the numbers of the parts in the bucket:

```bash
PYTHONPATH=src uv run --env-file .env python -m data_collection_service.bucket_storage_client
```
