import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pwdlib import PasswordHash
from prometheus_client import Counter

# No usernames as labels: they would expose users and create too many series
AUTH_EVENTS = Counter('auth_events_total', 'Authentication results.', ['result'])

ADMIN = 'admin'
USER = 'user'

# Shared by all services and replicas, so a token from one is valid in all.
# The fallback is only for local runs and tests.
SECRET_KEY = (
    os.environ.get('AUTH_SECRET_KEY')
    or 'dev-only-insecure-key-do-not-use-in-production'
)
ALGORITHM = 'HS256'
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# The real users are in users.json, which is not in Git. Without it (e.g. in
# CI or the tests) the committed demo users from users.example.json are used.
HERE = Path(__file__).parent
USERS_FILE = Path(os.environ.get('AUTH_USERS_FILE', HERE / 'users.json'))

if not USERS_FILE.exists():
    print(f'{USERS_FILE} not found, using the demo users')
    USERS_FILE = HERE / 'users.example.json'

with open(USERS_FILE) as f:
    USERS = json.load(f)

password_hash = PasswordHash.recommended()

# Used for unknown usernames, so they take about as long as a wrong password
DUMMY_HASH = password_hash.hash('dummy-password')

# tokenUrl tells the /docs "Authorize" button where to log in
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')
router = APIRouter(tags=['auth'])

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail='Invalid or missing credentials',
    headers={'WWW-Authenticate': 'Bearer'},
)


@router.post('/token')
def login(form: OAuth2PasswordRequestForm = Depends()) -> dict:
    """Exchanges username and password for an expiring access token."""
    user = USERS.get(form.username)
    stored_hash = user['password_hash'] if user else DUMMY_HASH
    if not password_hash.verify(form.password, stored_hash) or user is None:
        AUTH_EVENTS.labels('login_failed').inc()
        raise CREDENTIALS_ERROR

    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token = jwt.encode(
        {'sub': form.username, 'exp': expire}, SECRET_KEY, algorithm=ALGORITHM
    )
    AUTH_EVENTS.labels('login_success').inc()
    return {'access_token': token, 'token_type': 'bearer'}


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Returns the user of a valid, unexpired access token."""
    try:
        # decode also checks the signature and the 'exp' expiry time
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        AUTH_EVENTS.labels('token_rejected').inc()
        raise CREDENTIALS_ERROR
    # Look the user up again, so a removed user's tokens stop working
    username = payload.get('sub')
    user = USERS.get(username)
    if user is None:
        AUTH_EVENTS.labels('token_rejected').inc()
        raise CREDENTIALS_ERROR
    return {'username': username, 'role': user['role']}


def require_role(*roles: str):
    """Dependency that lets only users with one of the given roles pass."""

    def check(user: dict = Depends(get_current_user)) -> dict:
        if user['role'] not in roles:
            AUTH_EVENTS.labels('forbidden').inc()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Not allowed for this user',
            )
        return user

    return check


# The admin can access all services, the users only predict
require_admin = require_role(ADMIN)
require_predict_access = require_role(ADMIN, USER)
