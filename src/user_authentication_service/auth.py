import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)

ADMIN = 'admin'
USER = 'user'

# Demo users for the training project. Each one can log in either with
# username and password (Basic) or with the token (Bearer).
USERS = {
    'admin': {'password': 'admin123', 'token': 'admin-token', 'role': ADMIN},
    'alice': {'password': 'alice123', 'token': 'alice-token', 'role': USER},
    'bob': {'password': 'bob123', 'token': 'bob-token', 'role': USER},
}

# auto_error=False: a missing header is not an error yet, because the client
# may have sent the other scheme
basic_scheme = HTTPBasic(auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    basic: HTTPBasicCredentials | None = Depends(basic_scheme),
    bearer: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Returns the user that sent valid Basic or Bearer credentials."""
    # compare_digest takes the same time for any input, so the response time
    # gives no hint about how much of a password or token was right
    if basic is not None:
        user = USERS.get(basic.username)
        if user and secrets.compare_digest(basic.password, user['password']):
            return {'username': basic.username, 'role': user['role']}
    if bearer is not None:
        for username, user in USERS.items():
            if secrets.compare_digest(bearer.credentials, user['token']):
                return {'username': username, 'role': user['role']}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='Invalid or missing credentials',
        headers={'WWW-Authenticate': 'Basic, Bearer'},
    )


def require_role(*roles: str):
    """Dependency that lets only users with one of the given roles pass."""

    def check(user: dict = Depends(get_current_user)) -> dict:
        if user['role'] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Not allowed for this user',
            )
        return user

    return check


# The admin can access all services, the users only predict
require_admin = require_role(ADMIN)
require_predict_access = require_role(ADMIN, USER)
