# User authentication service

Protects the endpoints of the project's APIs. Every request must say who sends it (authentication), and the sender's role decides which endpoints they may call (authorization).

It is not a separate API, but a module (`auth.py`) that the other services import.

## Users

The demo users are defined in the `USERS` dictionary in `auth.py`. Each one can log in either with username and password (Basic) or with the token (Bearer).

| User    | Password   | Token         | Role    | Access                               |
| ------- | ---------- | ------------- | ------- | ------------------------------------ |
| `admin` | `admin123` | `admin-token` | `admin` | all services (`/predict`, `/ingest`) |
| `alice` | `alice123` | `alice-token` | `user`  | only `/predict`                      |
| `bob`   | `bob123`   | `bob-token`   | `user`  | only `/predict`                      |

## Sending credentials

Both schemes use the HTTP header `Authorization`:

| Scheme | Header                                        | curl                                       |
| ------ | --------------------------------------------- | ------------------------------------------ |
| Basic  | `Authorization: Basic <base64 of user:pass>`  | `-u alice:alice123`                        |
| Bearer | `Authorization: Bearer <token>`               | `-H 'Authorization: Bearer alice-token'`   |

Example:

```bash
curl -X POST localhost:8000/predict -u alice:alice123 \
     -H 'Content-Type: application/json' \
     -d '{"user_ids": [21525]}'
```

In the API docs (e.g. <http://localhost:8000/docs>), click *Authorize* and fill in either the HTTPBasic or the HTTPBearer box.

## Responses

| Code  | Meaning                                         | Example                                   |
| ----- | ----------------------------------------------- | ----------------------------------------- |
| `200` | Authenticated and allowed                       | `alice` calls `/predict`                  |
| `401` | Not authenticated: missing or wrong credentials | no header, wrong password, unknown token  |
| `403` | Authenticated, but the role is not allowed      | `alice` calls `/ingest`                   |

The `401` message does not say whether the username or the password was wrong, so it gives no hint which usernames exist.

## How it works

A request passes these steps before the endpoint runs:

```
request ──► HTTPBasic / HTTPBearer ──► get_current_user ──► require_role ──► endpoint
            read the header             who is it? (401)      allowed? (403)
```

1. **`basic_scheme` and `bearer_scheme`** (FastAPI's `HTTPBasic` and `HTTPBearer`) read the `Authorization` header. They use `auto_error=False`, so a missing header gives `None` instead of an immediate `401`. Otherwise a Bearer request would be rejected by the Basic scheme before its token is checked.
2. **`get_current_user`** looks up the Basic username and compares the password, or searches the user whose token matches. It returns `{'username': ..., 'role': ...}` or raises `401`. The comparison uses `secrets.compare_digest` to reduce timing differences caused by matching credential contents. **It does not make the entire authentication operation constant-time:** unknown usernames take a different lookup path, tokens are checked against users in a loop, and input length or other operations may affect response timing. It is one defense against timing attacks, not a guarantee of timing-attack resistance.
3. **`require_role(*roles)`** creates a dependency that first runs `get_current_user` and then raises `403` if the role is not in `roles`.

The ready-made rules are:

```python
require_admin = require_role(ADMIN)                 # only the admin
require_predict_access = require_role(ADMIN, USER)  # admin and users
```

If a check fails, the endpoint code never runs. For example, a user calling `/ingest` uploads nothing.

## Protecting an endpoint

Add the rule to the endpoint's `dependencies`, as `src/data_collection_service/main.py` does:

```python
from fastapi import Depends

from user_authentication_service.auth import require_admin


@api.post('/ingest', dependencies=[Depends(require_admin)])
def ingest(request: IngestRequest | None = None):
    ...
```

If the endpoint needs to know who calls it, take the user as a parameter instead:

```python
@app.post('/predict')
def predict(request: PredictRequest, user: dict = Depends(require_predict_access)):
    print(user['username'], user['role'])
```

A service whose Docker image copies single files must also copy this module, see `src/predict_service/Dockerfile`:

```dockerfile
COPY src/user_authentication_service/ src/user_authentication_service/
```

New roles are added as a constant (like `ADMIN` and `USER`), assigned in `USERS` and used in a `require_role(...)` rule.

## Limitations

This is kept simple for the training project. A production system would:

- store only password hashes (e.g. bcrypt), not plain-text passwords
- issue expiring tokens (e.g. JWT from a `POST /token` login endpoint) instead of fixed ones
- load the users from a database or secrets, not from the code in Git
- serve the APIs over HTTPS only, since Basic credentials are only Base64-encoded, not encrypted

MLflow, Prometheus and Grafana are third-party tools and are not protected by this module. Grafana has its own login (see `.env`).

## Automated authentication tests

From the repository root, install the development dependencies and run:

```bash
uv sync --group dev
PYTHONPATH=src uv run pytest -q tests/auth
```

The tests check missing and invalid Basic credentials, unknown bearer tokens, valid
users, and the `/ingest` admin-only rule. They also exercise the real `/predict`
route with lightweight fake ML artifacts: an **unknown login username** is rejected
with `401`, whereas a valid account requesting an **unknown MovieLens user ID**
is rejected with `404`. No external dataset or Docker service is required.

### Test an unknown user manually

Run the prediction API as described in the main README, then in another shell:

```bash
# Unknown authentication account -> HTTP 401
curl -i -u 'nonexistent:some-password' \
  -H 'Content-Type: application/json' \
  -d '{"user_ids":[21525]}' http://localhost:8000/predict

# Known account, nonexistent MovieLens profile -> HTTP 404
curl -i -u 'alice:alice123' \
  -H 'Content-Type: application/json' \
  -d '{"user_ids":[999999999]}' http://localhost:8000/predict
```

The second test assumes ID `999999999` does not exist in the currently loaded
user matrix. These fixed demo credentials are **not suitable for deployment**.
