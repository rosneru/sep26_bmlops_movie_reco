# Local Airflow infrastructure

All services live in the main `docker-compose.yml`, using Airflow 3.3.2 and
PostgreSQL 16. The API server provides the dashboard, the scheduler coordinates
work with LocalExecutor, and the DAG processor parses files in `airflow/dags`.
There is no Redis or separate Celery worker. A manual infrastructure smoke-test DAG is included; the data preparation DAG runs the existing preparation image through DockerOperator.

## Local settings

Compose reads `.env` in the repository root, including the existing required
DagsHub and Grafana variables. Set these database settings there:

```dotenv
AIRFLOW_POSTGRES_USER=airflow
AIRFLOW_POSTGRES_DB=airflow
AIRFLOW_POSTGRES_PASSWORD=your-random-hexadecimal-password
```

Run the setup helper; it generates missing encryption/signing keys in `.env` and
dashboard credentials in the same root `.env` file, which is ignored by Git.
Existing nonempty settings are preserved; no separate password directory or
JSON file is created.

```powershell
python airflow/setup_local.py
```

This setup uses FAB Auth Manager. Configure dashboard credentials only in `.env`:

```dotenv
AIRFLOW_ADMIN_USER=airflow
AIRFLOW_ADMIN_PASSWORD=your-dashboard-password
```

The official API image entrypoint creates the Admin account if absent. FAB stores
its password hash in PostgreSQL, not in a separate JSON file. View your password
in the local `.env`; do not share or commit it. Changing `.env` later does not
reset an existing database account automatically. To explicitly synchronize its
password with `.env` after recreating the API container, run:

```powershell
docker compose exec airflow-api-server bash -c 'airflow users reset-password --username "$_AIRFLOW_WWW_USER_USERNAME" --password "$_AIRFLOW_WWW_USER_PASSWORD"'
```

This login is independent of PostgreSQL and DagsHub credentials. The dashboard
is bound to the local machine only: http://localhost:8081.

## First database initialization

Run from the repository root:

```powershell
docker volume create movie-reco-airflow-postgres-data
docker compose config --quiet
docker compose up -d --wait airflow-postgres
docker compose run --rm airflow-init
docker compose run --rm airflow-init db check
docker compose run --rm airflow-init db check-migrations --migration-wait-timeout 30
```

The database hostname inside Docker is `airflow-postgres`, port 5432; no database
port is published to Windows. The named external volume
`movie-reco-airflow-postgres-data` persists the database and is not deleted by
Compose down, even with `-v`. On a fresh machine the volume-create command is
required. PostgreSQL user/password/database settings initialize an empty volume
only; modifying `.env` does not change existing users or their passwords.

## Start and verify the dashboard infrastructure

Initialize the database first, then run:

```powershell
docker compose up -d --wait airflow-api-server airflow-scheduler airflow-dag-processor
docker compose ps airflow-postgres airflow-api-server airflow-scheduler airflow-dag-processor
```

Open http://localhost:8081 and log in with the credentials described above. The manual `infrastructure_smoke_test` DAG should appear after the processor discovers its file. The API server health endpoint is
http://localhost:8081/api/v2/monitor/health; inspect its component statuses as
well as the HTTP response. Scheduler and DAG processor healthchecks validate
heartbeats in the metadata database. Task/service logs persist in the named
`movie-reco_airflow_logs` volume mounted at `/opt/airflow/logs`.

Stop just these services:

```powershell
docker compose stop airflow-api-server airflow-scheduler airflow-dag-processor airflow-postgres
```

Database initialization is intentionally still manual: `airflow-init` has its
own profile. Normal Compose up does not run it. Automatic startup gating on
successful initialization is a planned later step, as is
prediction deployment. Starting the infrastructure does not run training;
manually triggering the training_pipeline DAG now trains/registers a KNN version.

References:
- https://airflow.apache.org/docs/apache-airflow/3.3.2/howto/docker-compose/index.html
- https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/auth-manager/simple/index.html

- https://airflow.apache.org/docs/apache-airflow-providers-fab/stable/auth-manager/webserver-authentication.html

## Manual infrastructure smoke test

DAG: `airflow/dags/infrastructure_smoke_test.py`.
The DAG is manual-only and runs `start -> log_message -> end`. It does not read
movie data, train a model, or contact DagsHub.

1. Open http://localhost:8081 and log in using your `.env` credentials.
2. Find `infrastructure_smoke_test` and unpause it.
3. Click Trigger DAG and wait for all three tasks to reach `success`.
4. Open the `log_message` task log and find `AIRFLOW_SMOKE_TEST_OK`.
5. Re-pause the DAG after testing if desired. It has no automatic schedule.

If the new DAG does not appear yet, restart only the DAG processor to force
immediate discovery:

```powershell
docker compose restart airflow-dag-processor
```

There is no separate pytest file for this check; use the DAG directly in the UI.

## Run preparation and KNN training from Airflow

DAG: `airflow/dags/training_pipeline.py`, shown as `training_pipeline` in the UI.
It has two sequential tasks: `prepare_features -> train_knn`. The first uses
DockerOperator with `movie-reco-data-preparation:local`. The second uses a small
DockerOperator subclass with `movie-reco-train:knn`; it resolves MLflow credentials
only at task execution. Both create sibling containers through Docker Engine,
not Docker Compose commands. Preparation reads `split.current_part` from the
mounted `params.yaml`. No trigger parameter is required or used in this version.
The DAG ID is `training_pipeline`, reflecting both preparation and training.
Historical runs under the old `data_preparation` ID remain in Airflow history;
that old DAG is no longer defined in the source. Use only `training_pipeline` for new runs.

The pinned official `apache/airflow:3.3.2` image already includes Docker provider
4.5.9, verified in the installed image, so no custom Airflow Dockerfile or package
installation is necessary. Only the scheduler has the Docker socket mounted,
because LocalExecutor runs task processes there. Socket access gives that service
control over the host Docker Engine; the API and DAG processor do not get it.

### Setup and start (PowerShell, repository root)

```powershell
python airflow/setup_local.py
docker compose config --quiet
docker compose build data_preparation
$env:MODEL_TYPE = "knn"
docker compose build train
Remove-Item Env:MODEL_TYPE -ErrorAction SilentlyContinue
docker compose up -d --wait airflow-api-server airflow-scheduler airflow-dag-processor
```

The helper fills missing `AIRFLOW_DOCKER_PROJECT_DIR` and `AIRFLOW_DOCKER_GID`
settings in `.env` without replacing existing settings. On Windows Docker Desktop
with Linux containers, the daemon-side project path looks like:

```dotenv
AIRFLOW_DOCKER_PROJECT_DIR=/run/desktop/mnt/host/d/Git/Liora/MLOPS/Final Pro-Movie Reco-With Team
AIRFLOW_DOCKER_GID=0
```

This is the host project directory as seen by Docker Engine, not the scheduler's
`/opt/airflow` directory. Raw data, rating parts and `params.yaml` are mounted
read-only in the preparation container; only `data/processed` is writable.
For another host/drive or Docker context, verify and adjust the path in `.env`.
On native Linux use the absolute host project path and the Docker socket's group
ID (obtain it with `stat -c %g /var/run/docker.sock`). The scheduler runs as the
Airflow user with this supplementary group, not as root.

### Manual verification in the dashboard

1. Ensure `movies.csv` and all rating parts through `split.current_part` exist.
2. Open http://localhost:8081 and log in with the `.env` dashboard account.
3. Find `training_pipeline`, unpause it, then click Trigger DAG.
4. Wait for `prepare_features` to reach `success`.
5. In its log, find `Data preparation passed: ratings=..., users=..., movies=..., genres=...`.
6. Wait for `train_knn` to reach `success`; it runs only after preparation succeeds.
7. In the training log, find `MLflow run ID:` and `Registry URI: models:/movie-genre-knn/<version>`.
8. Open DagsHub MLflow and confirm that run and the registered model version exist.
9. Verify the host output files:

```powershell
Get-Item data/processed/user_matrix.csv, data/processed/movie_matrix.csv |
    Select-Object Name, Length, LastWriteTime
```

The DAG has no automatic schedule, allows only one active run, and has no task
retries. Do not also run manual Compose/DVC preparation concurrently: all paths
write the same output files. Preparation has networking disabled. Training has
outbound bridge networking for DagsHub and a read-only processed-data mount.
Each child container is removed after success or failure; stdout/stderr remains
in the Airflow task log. A successful trigger registers a new KNN model version.
It does not restart or change the prediction service. `mount_tmp_dir=False`
avoids trying to mount a temporary directory that exists only in the scheduler.

If the DAG is not discovered, restart `airflow-dag-processor`. If an image is
missing, run `docker compose build data_preparation`. For Docker socket permission
errors, verify `AIRFLOW_DOCKER_GID` and recreate the scheduler. For mount errors,
verify the daemon-side path. Rebuild the preparation image after changes to its
code, Dockerfile or requirements; the DockerOperator does not build it for you.

Initialization is still manual (`docker compose run --rm airflow-init` on a fresh
database). Automatic startup dependency on its successful completion remains a
later step.

### MLflow credentials and training failure checks

Set `MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_USERNAME`, and `DAGSHUB_TOKEN` in the
root `.env`. The last becomes `MLFLOW_TRACKING_PASSWORD` only in the scheduler
execution service and then in the training container. After changing `.env`,
recreate the scheduler to update its environment:

```powershell
docker compose up -d --wait airflow-scheduler
```

The DAG processor and API server do not receive these MLflow credentials.
`MLflowTrainingOperator.execute()` validates them at runtime, registers the token
with Airflow's log masker, and passes them using DockerOperator's private
environment. Credentials are not embedded in the serialized DAG or rendered
task environment. Docker administrators can still inspect container environment
variables, so this mechanism does not hide secrets from Docker administrators.

KNN is explicitly selected in this DAG regardless of the `.env` MODEL_TYPE used
for standalone training. Always build `movie-reco-train:knn` before triggering.
The default `all_success` dependency prevents training after preparation failure.
Missing credentials fail before creating the training container. HTTP 403 from
MLflow means remote creation/registration is forbidden; check token validity and
Write access to the configured DagsHub project. Training cannot complete until
that access is fixed. No automatic retry is configured because a partial run may
already have registered a model version. Re-triggering the DAG prepares data again
and can register another version; it does not reuse a previously completed model.
The training task timeout is 30 minutes; the DAG timeout is 45 minutes.
