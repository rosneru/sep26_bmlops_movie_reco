# Local Airflow infrastructure

All services live in the main `docker-compose.yml`, using Airflow 3.3.2 and
PostgreSQL 16. The API server provides the dashboard, the scheduler coordinates
work with LocalExecutor, and the DAG processor parses files in `airflow/dags`.
There is no Redis or separate Celery worker. No project DAGs have been added yet.

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

Open http://localhost:8081 and log in with the credentials described above. An
empty DAG list is expected. The API server health endpoint is
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
successful initialization is a planned later step, as are a smoke-test DAG and
integration with data preparation, KNN training and prediction. No training,
prediction deployment, or DagsHub writes are triggered by this setup.

References:
- https://airflow.apache.org/docs/apache-airflow/3.3.2/howto/docker-compose/index.html
- https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/auth-manager/simple/index.html

- https://airflow.apache.org/docs/apache-airflow-providers-fab/stable/auth-manager/webserver-authentication.html
