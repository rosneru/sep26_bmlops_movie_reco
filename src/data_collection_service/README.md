# Data collection service

Simulates data that arrives over time: uploads `movies.csv` and the rating parts `1..n` from `data/interim/ratings_parts/` to the repo bucket *DagsHub Storage*. The uploaded files are shown on the DagsHub repo page under *Storage Buckets*.

The data preparation service reads its inputs from this bucket.

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
make test-dcs-next  # upload the next part only
```

The API docs are at <http://localhost:8001/docs>.

`POST /ingest` takes an optional `requested_up_to`. Without it, `split.current_part` from `params.yaml` is used.

With `{"next_part": true}` only the part after the highest one in the bucket is uploaded (part 1 for an empty bucket). If the bucket already contains all local parts, the status is `up_to_date` and nothing is uploaded. `next_part` cannot be combined with `requested_up_to` (`422`).

## Behaviour

- Files in the bucket are never overwritten or removed. Files already there are skipped.
- Requesting fewer parts than stored returns `409`.
- `requested_up_to < 1` returns `422`.

## Airflow DAG `data_ingestion`

Simulates the arriving data: every Tuesday at 09:00 Europe/Berlin, before the daily `training_pipeline` run at 09:40, it calls `POST /ingest` with `{"next_part": true}`. After 8 runs (8 weeks) all parts are uploaded; later runs are skipped (`up_to_date`).

- `catchup=False`: if the system starts after 09:00 on a Tuesday, the missed run starts right away. After a longer downtime only the latest missed Tuesday runs, so at most one part is uploaded per start. On the very first unpause no missed run is made; trigger the DAG manually if needed.
- Start `data_collection` before Airflow. The missed run starts as soon as the scheduler is up and fails without retry if the service is not reachable.

- A run that uploads a part updates the Airflow asset `rating_parts`. Skipped and failed runs do not, so DAGs scheduled on the asset only run when new data arrived.
- No retries: if an upload succeeded but its response was lost, a retry would upload one more part.

**Only one team member should unpause this DAG.** The bucket is shared, so every unpaused copy uploads a part per week and the simulation advances faster than intended. New DAGs are paused by default.

Prerequisites:

1. Set the admin account of this API in the root `.env` (demo: `admin` / `admin123`):

   ```dotenv
   DATA_COLLECTION_USERNAME=admin
   DATA_COLLECTION_PASSWORD=admin123
   ```

2. Start the service and recreate the scheduler:

   ```bash
   docker compose up -d --build data_collection
   docker compose up -d --wait airflow-scheduler
   ```

## Check the bucket

Print the numbers of the parts in the bucket:

```bash
PYTHONPATH=src uv run --env-file .env python -m data_collection_service.bucket_storage_client
```
