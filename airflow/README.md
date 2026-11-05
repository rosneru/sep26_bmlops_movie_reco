# Local Airflow infrastructure

## Quick start and current startup behavior

Airflow database initialization is now automatic: Compose waits for PostgreSQL
to become healthy, runs `airflow-init` (`airflow db migrate`), and starts the API
server, scheduler and DAG processor only after initialization exits successfully.
Existing database contents and run history are preserved. No separate init
command is required for normal startup.

With the root `.env` configured,
run from the repository root in PowerShell:

```powershell
docker compose up -d --build --wait airflow-api-server airflow-scheduler airflow-dag-processor
docker compose ps -a airflow-init airflow-postgres airflow-api-server airflow-scheduler airflow-dag-processor
```

Expected: `airflow-init` shows `Exited (0)` and all four long-running services
show `healthy`. Open http://localhost:8081 with your `.env` dashboard credentials.
Starting these services does not trigger training; run `training_pipeline`
manually from the dashboard. If initialization fails, inspect
`docker compose logs airflow-init`; new Airflow runtime services remain blocked.
Use Compose `up` for this dependency ordering; `restart` does not replay it.
For a new machine without local settings, follow the setup sections below.

The main `docker-compose.yml` includes `compose.airflow.yml`, which uses a local image based on Airflow 3.3.2 and
PostgreSQL 16. The API server provides the dashboard, the scheduler coordinates
work with LocalExecutor, and the DAG processor parses files in `airflow/dags`.
There is no Redis or separate Celery worker. A manual infrastructure smoke-test DAG is included; the training pipeline prepares data, registers KNN and deploys/verifies its exact version.

## Local settings

Compose reads `.env` in the repository root, including the existing required
DagsHub and Grafana variables. The database user and name both default to
`airflow` and can be overridden in `.env`.

Run the setup helper to fill in missing encryption and signing keys, dashboard
credentials, and a hexadecimal PostgreSQL password in the root `.env` file.
Git ignores this file. The helper preserves existing nonempty values.

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

## Automatic database initialization and startup

Run from the repository root:

```powershell
docker compose config --quiet
docker compose up -d --build --wait airflow-api-server airflow-scheduler airflow-dag-processor
# Optional read-only database diagnostics:
docker compose run --rm airflow-init db check
docker compose run --rm airflow-init db check-migrations --migration-wait-timeout 30
```

The database hostname inside Docker is `airflow-postgres`, port 5432; no database
port is published to Windows. Compose creates a database volume for each project.
The default project uses `movie-reco-airflow-postgres-data`. Ordinary
`docker compose down` preserves the database. Avoid `docker compose down -v`
when you want to keep it. PostgreSQL user, password, and database settings
initialize an empty volume. Changing `.env` does not update existing accounts.

## Start and verify the dashboard infrastructure

Initialize the database first, then run:

```powershell
docker compose up -d --build --wait airflow-api-server airflow-scheduler airflow-dag-processor
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

Database initialization is automatic during Compose up. The runtime services
wait for PostgreSQL to become healthy and for `airflow-init` to finish with exit
code 0 (`service_completed_successfully`). The init service has no profile and
only depends on healthy PostgreSQL, avoiding a self-dependency. It runs
`airflow db migrate`, which creates missing tables or applies pending migrations;
it does not reset the database. On migration failure, new runtime containers do
not start. Existing already-running services are not automatically stopped by
a dependency failure. `restart` or a Docker daemon restart does not replay this
Compose startup gate; use Compose up for the ordered startup. Starting the
infrastructure does not trigger the manual training pipeline.

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

## Run preparation, KNN training and prediction deployment

DAG: `airflow/dags/training_pipeline.py`, shown as `training_pipeline` in the UI.
It has three sequential tasks: `prepare_features -> train_knn -> deploy_predict`. The first uses
DockerOperator with `movie-reco-data-preparation:local`. The second uses a small
DockerOperator subclass with `movie-reco-train:knn`; it resolves MLflow credentials
only at task execution. Both create sibling containers through Docker Engine,
not Docker Compose commands. Preparation reads `split.current_part` from the
mounted `params.yaml`. No trigger parameter is required or used in this version.
The DAG ID is `training_pipeline`, covering preparation, training and deployment.
Historical runs under the old `data_preparation` ID remain in Airflow history;
that old DAG is no longer defined in the source. Use only `training_pipeline` for new runs.

The pinned official `apache/airflow:3.3.2` image already includes Docker provider
4.5.9, verified in the installed image, so no extra Python provider installation is necessary. `airflow/Dockerfile` now
adds the static Docker CLI and Compose plugin required for prediction deployment. Only the scheduler has the Docker socket mounted,
because LocalExecutor runs task processes there. Socket access gives that service
control over the host Docker Engine; the API and DAG processor do not get it.

### Setup and start (PowerShell, repository root)

```powershell
python airflow/setup_local.py
docker compose config --quiet
docker compose build data_preparation
$env:MODEL_TYPE = "knn"
docker compose build train airflow-scheduler
$env:PREDICT_MODEL_TYPE = "knn"
docker compose build predict
Remove-Item Env:PREDICT_MODEL_TYPE -ErrorAction SilentlyContinue
Remove-Item Env:MODEL_TYPE -ErrorAction SilentlyContinue
docker compose up -d --build --wait airflow-api-server airflow-scheduler airflow-dag-processor
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
8. Wait for `deploy_predict` to succeed, then inspect its exact model URI in the task log.
9. Open DagsHub MLflow and confirm that run and registered version exist.
10. Verify the host output files:

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
The final task recreates the three prediction replicas with that exact version, then checks each replica and nginx. `mount_tmp_dir=False`
avoids trying to mount a temporary directory that exists only in the scheduler.

If the DAG is not discovered, restart `airflow-dag-processor`. If an image is
missing, run `docker compose build data_preparation`. For Docker socket permission
errors, verify `AIRFLOW_DOCKER_GID` and recreate the scheduler. For mount errors,
verify the daemon-side path. Rebuild the preparation image after changes to its
code, Dockerfile or requirements; the DockerOperator does not build it for you.

Fresh database setup also uses the automatic Compose startup gate described
above. Compose creates the PostgreSQL volume and runs migrations.

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
The training task timeout is 30 minutes; deployment is limited to 20 minutes, and the DAG to 75 minutes.

## Exact-version prediction deployment

`train_model.py` prints `TRAINING_RESULT_JSON=...` as its last stdout line after
the MLflow run closes. `MLflowTrainingOperator` validates this record and returns
only model name, numeric version and training Run ID through XCom. It never uses
`latest` to decide what to deploy. If this handoff is missing/invalid, deployment
is blocked even if a model version was registered remotely.

`deploy_predict` calls `airflow/dags/prediction_deployment.py` at task execution:

1. Require three healthy, consistent running KNN replicas and a running nginx.
2. Read their actual served model version and immutable Docker image ID for rollback.
3. Start an isolated candidate API container with the newly built prediction image
   and the exact model version from training; check authenticated `/model` and
   `/predict` before touching the live service.
4. Use Compose to recreate only `predict`, with three replicas, an explicit image
   ID and model version. No build/pull or unrelated service restart happens here.
5. Check the version and a real seeded prediction on every replica, reload nginx
   DNS/upstreams, and verify both endpoints through nginx as well.
6. Persist `PREDICT_MODEL_TYPE`, `PREDICT_MODEL_NAME`, `PREDICT_MODEL_VERSION` in
   root `.env`, preserving other settings. Future normal Compose starts use that
   numeric version. There is no separate password or release JSON file.
7. On failure after rollout begins, recreate the previous model/image, verify it,
   and persist the restored version. The Airflow task remains failed so the
   unsuccessful release is visible. Preflight failure leaves live replicas alone.

The Scheduler mounts the project at the same absolute daemon-visible path so
Compose's relative bind paths resolve correctly on Docker Desktop. This mount
is writable because the task updates only the three serving-selection keys in
`.env`; it also makes the local `.env` accessible to that execution container.
The API and DAG processor do not get this project-root mount or Docker socket.
Temporary `.env.rollout-*` files are excluded from Git and Docker build context.

`PREDICT_SMOKE_USERNAME` and `PREDICT_SMOKE_PASSWORD` in the root `.env` select
an existing API account (for the demo account: `alice` / `alice123`). The task
obtains a fresh JWT from `/token` for each deployment. Set the shared
`AUTH_SECRET_KEY` as well; it is passed to the temporary candidate so the same
JWT is valid there. Rebuild predict after authentication changes and recreate
the scheduler after changing these settings:

```powershell
docker compose build predict
docker compose up -d --wait predict nginx airflow-scheduler
```

Old `PREDICT_SMOKE_TOKEN` settings are no longer used. The check selects an existing
user ID from the processed user matrix and expects ten distinct movie IDs. This
is a functional serving check, not a recommendation-quality evaluation.

The rollout recreates the replicas and may briefly interrupt requests; this is
not a zero-downtime deployment. Automatic rollback is attempted for handled task
errors, not guaranteed after a host crash or forced task termination. It restores
model/image selection, not historical processed CSVs. Do not edit `.env`, change
models, scale predict, or run another Compose/DVC preparation while this DAG is
running. Retain the previous local image and registered model for rollback.

To check the active selection from PowerShell after a successful run:

```powershell
$login = Invoke-RestMethod -Method Post http://localhost:8000/token -Body @{username="alice"; password="alice123"}
Invoke-RestMethod http://localhost:8000/model -Headers @{Authorization="Bearer $($login.access_token)"}
```

Use your actual API username/password if changed; obtain a new JWT after expiry. The returned model URI must match the
training result. Also check `docker compose ps predict` for three healthy replicas.
Updating `.env` serving selection does not change API login credentials.

## JWT authentication for deployment verification

The API authentication changed from fixed demo tokens to OAuth2 password login
and signed JWTs. Airflow's deployment helper now calls `POST /token` against a
running prediction replica at task execution, masks the returned JWT and password
in Airflow logs, and uses the JWT for baseline, candidate, replica and Nginx checks.
No token is stored in the DAG or persisted in `.env`. Training and data preparation
are unchanged.

The scheduler receives the API login credentials and shared `AUTH_SECRET_KEY`
through Compose. The temporary preflight container receives that same signing key;
otherwise a JWT issued by the running service would be rejected by the candidate.
The existing replicas must already use the same key and have the selected user.
JWTs expire after 30 minutes; each new deployment task requests a fresh token.
The task does not refresh a token during a single rollout.

### Configure and run an end-to-end check

1. In the repository root `.env`, set an existing prediction API account:

```dotenv
PREDICT_SMOKE_USERNAME=alice
PREDICT_SMOKE_PASSWORD=alice123
AUTH_SECRET_KEY=<your-existing-shared-key>
```

These are demo login values, not DagsHub credentials. Use your actual password
if customized. Preserve the existing signing key; do not paste the placeholder.
An obsolete `PREDICT_SMOKE_TOKEN` entry may be removed. Keep `.env` out of Git.

2. From the repository root, build the prediction image and apply configuration:

```powershell
docker compose config --quiet
docker compose build predict
docker compose up -d --wait predict nginx airflow-scheduler
```

3. In http://localhost:8081, trigger `training_pipeline`. Expect
`prepare_features`, `train_knn`, and `deploy_predict` all to succeed. This test
creates a new registered model version and deploys it; it is not read-only.
4. Run `docker compose ps predict`; expect three healthy replicas.
5. Open http://localhost:8000/docs, select **Authorize**, enter the API username
and password, then choose **Authorize** and **Close**. Swagger calls `/token`
for you. Reauthorize after expiry; never enter `alice-token`.
6. Execute **GET /model** using **Try it out -> Execute**. Expect HTTP 200 and a
`model_uri` matching the exact version printed in the training task log.
7. Select an actual recommendation profile ID:

```powershell
Import-Csv data/processed/user_matrix.csv | Select-Object -First 5 userId
```

8. Execute **POST /predict** with `{"user_ids": [4], "seed": 42}` only if profile
4 exists; otherwise substitute one of the printed IDs. Expect HTTP 200 with
one recommendation row containing that user ID and ten distinct movie IDs.
The API login account and the numeric recommendation profile are independent.

### Diagnose failures

- Missing deployment settings: set the three `.env` values above and recreate
  `airflow-scheduler`; restarting alone does not reload Compose environment values.
- Login returns 401: verify the API username/password and the user records in the
  prediction image. Training can succeed while deployment login fails.
- Login works but candidate checks fail with 401: verify that the scheduler,
  candidate and all live replicas use the same `AUTH_SECRET_KEY`, and rebuild
  the candidate image if authentication code or user records changed.
- Swagger returns 401: log out and authorize again to obtain a fresh JWT.
- Prediction returns 404 with `Unknown user ids`: select a profile from the
  current matrix; this is distinct from an authentication error.

For the equivalent PowerShell API requests, see
[manual prediction verification](../src/predict_service/README.md#manual-verification-after-airflow-deployment-powershell--swagger).

## Manual failure test: preparation blocks downstream tasks

This verifies `prepare_features -> train_knn -> deploy_predict` uses the default
`all_success` dependency rule. Run it only when no other pipeline run or manual
preparation is active, because `params.yaml` is shared by all preparation jobs.

1. Note the existing `split.current_part` value in root `params.yaml`.
2. Temporarily change only that value to `0`; leave `n_parts` unchanged:

```yaml
split:
  n_parts: 8
  current_part: 0
```

3. Open http://localhost:8081 and trigger a **new** `training_pipeline` run.
   No image rebuild or container restart is required: preparation reads the
   bind-mounted `params.yaml` on every run.
4. Wait for the scheduler to record the final states:

```text
prepare_features -> failed
train_knn        -> upstream_failed
deploy_predict   -> upstream_failed
```

5. Open the preparation task log. Expect
   `current_part must be a positive integer`. The downstream tasks must not
   start; `upstream_failed` indicates a blocked prerequisite, not an attempted
   training/deployment failure. The overall run is expected to fail.
6. Confirm no model version was registered by this run and the prediction
   service continues serving the previous version. Optionally compare the
   following output before and after the test:

```powershell
Invoke-RestMethod http://localhost:8000/model -Headers @{
    Authorization = "Bearer $($login.access_token)"
}
```

Obtain a fresh JWT using the login command above if the previous token expired. This validation error happens
before processed CSVs are replaced, so existing outputs remain unchanged.

7. Restore `split.current_part` to its original value immediately after the
   test, including if the test is interrupted. Do not commit the temporary `0`.
   You may trigger a new valid run afterward; that run will train/register and
   deploy a new version normally. Keep the intentional failed run as evidence.

This is a manual fault-injection check; it does not require a pytest file.


## Verify automatic startup ordering

Run from the repository root after local `.env` setup:

```powershell
docker compose up -d --build --wait airflow-api-server airflow-scheduler airflow-dag-processor
docker compose ps -a airflow-init airflow-postgres airflow-api-server airflow-scheduler airflow-dag-processor
docker compose logs --tail 30 airflow-init
```

Expected order: PostgreSQL `healthy` -> init `Exited (0)` -> the three Airflow
runtime services `healthy`. Init exiting is normal: it is a one-off migration
job, not a long-running API. Its logs should include `Database migration done!`.
A separate `docker compose run --rm airflow-init` is only needed for explicit
maintenance, not ordinary startup. No volume removal is required.

For an existing initialized database, running migrations again keeps the tables
and run history. To inspect startup order from a stopped state, first ensure no
DAG run is queued/running, then stop only the three Airflow runtime services and
run the startup command above. Do not use `down -v`. Training/prediction services
are not started or redeployed by this targeted command.
