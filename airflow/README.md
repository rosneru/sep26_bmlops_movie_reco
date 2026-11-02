# Airflow metadata database — first setup step

The main docker-compose.yml starts PostgreSQL and runs Airflow 3.3.2
database migrations. Scheduler, dashboard and DAGs will be added separately.
Compose reads the existing project variables from .env, including required DagsHub and Grafana settings. Targeted commands below start only the Airflow database.

In the root `.env`, configure `AIRFLOW_POSTGRES_USER=airflow`,
`AIRFLOW_POSTGRES_DB=airflow`, and a random hexadecimal
`AIRFLOW_POSTGRES_PASSWORD`. Never commit the password. If choosing another
password format, URL-encode it in the SQLAlchemy connection URI.

Run from the repository root in PowerShell:

```powershell
docker volume create movie-reco-airflow-postgres-data
docker compose config --quiet
docker compose up -d --wait airflow-postgres
docker compose run --rm airflow-init
docker compose run --rm airflow-init db check
docker compose run --rm airflow-init db check-migrations --migration-wait-timeout 30
```

The database hostname inside this Compose network is `airflow-postgres`, port
5432. No database port is published on the host. Database and user names default
to `airflow`; the same settings configure PostgreSQL and Airflow's connection.

PostgreSQL readiness is checked before initialization. `db migrate` creates
Airflow's tables and can be run again to apply pending migrations. This does not
create a dashboard login or start a web server.

The named volume `movie-reco-airflow-postgres-data` persists metadata.
It is declared external to preserve the database from the initial setup. On a fresh machine, the volume-create command above creates it. To stop only this database:

```powershell
docker compose stop airflow-postgres
```

The external volume is not deleted by Compose down, including down -v; deleting it explicitly erases the metadata database. The init service has a dedicated profile and runs only when explicitly requested. Changing
`POSTGRES_USER`, `POSTGRES_DB` or the password in `.env` after first initialization
does not update existing PostgreSQL users/databases; these settings initialize an
empty volume only. Keep the original values or perform an explicit SQL change.

Reference: https://airflow.apache.org/docs/apache-airflow/3.3.2/howto/docker-compose/index.html
