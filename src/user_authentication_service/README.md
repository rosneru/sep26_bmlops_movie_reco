# User authentication service

Protects the endpoints of the project's APIs. Every request must say who sends it (authentication), and the sender's role decides which endpoints they may call (authorization).

It is not a separate API, but a module (`auth.py`) that the other services import. It uses the OAuth2 password flow: a user logs in once at `POST /token` and gets a signed, expiring access token (a JWT), which is then sent with every request.

## Users

The users are stored in `users.json` next to `auth.py`, with a password **hash** (argon2) and a role. The file is not in Git. If it is missing (e.g. in CI or a fresh clone), the committed demo users from `users.example.json` are used:

| User    | Password   | Role    | Access                               |
| ------- | ---------- | ------- | ------------------------------------ |
| `admin` | `admin123` | `admin` | all services (`/predict`, `/ingest`) |
| `alice` | `alice123` | `user`  | only `/predict`                      |
| `bob`   | `bob123`   | `user`  | only `/predict`                      |

The file is read once when a service starts. The environment variable `AUTH_USERS_FILE` can point to another file.

### Adding a user

1. Hash the password:

   ```bash
   uv run python -c "from pwdlib import PasswordHash; print(PasswordHash.recommended().hash('the-password'))"
   ```

2. Add an entry to `users.json`:

   ```json
   "carol": {"password_hash": "<the printed hash>", "role": "user"}
   ```

3. Restart the services. With Docker, rebuild them, since the file is copied into the images: `docker compose up -d --build`.

## Logging in

1. Get a token with username and password. Each API has its own `/token` endpoint (`localhost:8000` for prediction, `localhost:8001` for data collection), and a token from one is valid in all of them:

   ```bash
   TOKEN=$(curl -s -X POST localhost:8000/token -d 'username=alice&password=alice123' \
     | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
   ```

2. Send the token in the `Authorization` header:

   ```bash
   curl -X POST localhost:8000/predict -H "Authorization: Bearer $TOKEN" \
        -H 'Content-Type: application/json' \
        -d '{"user_ids": [21525]}'
   ```

The token expires after 30 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`). Then log in again.

In the API docs (e.g. <http://localhost:8000/docs>), click *Authorize* and enter username and password. The page then gets and sends the token itself.

## Responses

| Code  | Meaning                                    | Example                                                       |
| ----- | ------------------------------------------ | ------------------------------------------------------------- |
| `200` | Authenticated and allowed                  | `alice` calls `/predict` with a valid token                   |
| `401` | Not authenticated                          | wrong password at `/token`; missing, invalid or expired token |
| `403` | Authenticated, but the role is not allowed | `alice` calls `/ingest`                                       |

A failed login does not say whether the username or the password was wrong, so it gives no hint which usernames exist. Unknown usernames are checked against a dummy hash, so they take about as long as a wrong password.

## How it works

Logging in, once:

```
POST /token (username, password) ──► login: verify the password hash ──► signed JWT {"sub": user, "exp": ...}
```

Every protected request:

```
request ──► oauth2_scheme ──► get_current_user ──► require_role ──► endpoint
            read the Bearer     check signature,      allowed? (403)
            token (401)         expiry, user (401)
```

1. **`login`** (`POST /token`) looks up the user, verifies the password against the stored hash and returns a JWT signed with `AUTH_SECRET_KEY` (HS256). The token contains only the username (`sub`) and the expiry time (`exp`). It is signed, not encrypted, so it holds no secrets.
2. **`oauth2_scheme`** (FastAPI's `OAuth2PasswordBearer`) reads the token from the `Authorization: Bearer ...` header. Without the header, FastAPI answers `401 Not authenticated`.
3. **`get_current_user`** checks the signature and the expiry, then looks the user up in `USERS` again, so deleted users lose access and role changes apply at once. It returns `{'username': ..., 'role': ...}` or raises `401`.
4. **`require_role(*roles)`** creates a dependency that first runs `get_current_user` and then raises `403` if the role is not in `roles`.

The server stores no tokens. Any service with the same `AUTH_SECRET_KEY` can check a token, which is why all predict replicas behind nginx accept the same token. nginx itself only forwards the requests and does not check anything.

The ready-made rules are:

```python
require_admin = require_role(ADMIN)                 # only the admin
require_predict_access = require_role(ADMIN, USER)  # admin and users
```

If a check fails, the endpoint code never runs. For example, a user calling `/ingest` uploads nothing.

## Configuration

| Variable          | Purpose                                             | Default                                 |
| ----------------- | --------------------------------------------------- | --------------------------------------- |
| `AUTH_SECRET_KEY` | Signs the tokens; must be the same for all services | an insecure key, only for local runs    |
| `AUTH_USERS_FILE` | Path of the users file                              | `users.json`, else `users.example.json` |

Docker Compose requires `AUTH_SECRET_KEY` in the root `.env`. Generate one with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Protecting an endpoint

Add the `/token` endpoint to the service once, and the rule to the endpoint's `dependencies`, as `src/data_collection_service/main.py` does:

```python
from fastapi import Depends

from user_authentication_service.auth import require_admin, router as auth_router

api.include_router(auth_router)


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

New roles are added as a constant (like `ADMIN` and `USER`), assigned in `users.json` and used in a `require_role(...)` rule.

## Limitations

This is kept simple for the training project. A production system would:

- load the users from a database instead of a file baked into the image
- offer a way to revoke tokens before they expire (e.g. a deny list or refresh tokens)
- limit failed login attempts
- serve the APIs over HTTPS only, since a stolen token works until it expires

MLflow, Prometheus and Grafana are third-party tools and are not protected by this module. Grafana has its own login (see `.env`).

## Automated authentication tests

From the repository root, install the development dependencies and run:

```bash
uv sync --group dev
PYTHONPATH=src uv run pytest -q tests/auth
```

The tests check logins with wrong credentials, requests without a token and with unknown or expired tokens, valid users, and the `/ingest` admin-only rule. They also exercise the real `/predict` route with a fake model loader: an **unknown login username** is rejected at `/token` with `401`, whereas a valid account requesting an **unknown MovieLens user ID** is rejected with `404`. No mlflow, external dataset or Docker service is required.

### Test an unknown user manually

Run the prediction API as described in the main README, then in another shell:

```bash
# Unknown authentication account -> HTTP 401 at login
curl -i -X POST localhost:8000/token -d 'username=nonexistent&password=some-password'

# Known account, nonexistent MovieLens profile -> HTTP 404
TOKEN=$(curl -s -X POST localhost:8000/token -d 'username=alice&password=alice123' \
  | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
curl -i -X POST localhost:8000/predict -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"user_ids":[999999999]}'
```

The second test assumes ID `999999999` does not exist in the currently loaded user matrix. The demo credentials are **not suitable for deployment**.
