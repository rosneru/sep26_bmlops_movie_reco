# Local Airflow infrastructure

All services live in the main `docker-compose.yml`, using Airflow 3.3.2 and
PostgreSQL 16. The API server provides the dashboard, the scheduler coordinates
work with LocalExecutor, and the DAG processor parses files in `airflow/dags`.
There is no Redis or separate Celery worker. A manual infrastructure smoke-test DAG is included; movie pipeline DAGs are not connected yet.

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
integration with data preparation, KNN training and prediction. No training,
prediction deployment, or DagsHub writes are triggered by this setup.

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
