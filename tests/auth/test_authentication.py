"""Unit/API tests for the shared authentication dependency."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from user_authentication_service.auth import (
    ALGORITHM,
    SECRET_KEY,
    require_admin,
    require_predict_access,
)
from user_authentication_service.auth import (
    router as auth_router,
)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(auth_router)

    @app.get('/predict', dependencies=[Depends(require_predict_access)])
    def prediction():
        return {'ok': True}

    @app.post('/ingest', dependencies=[Depends(require_admin)])
    def ingest():
        return {'ok': True}

    return TestClient(app)


def login(client, username, password):
    response = client.post('/token', data={'username': username, 'password': password})
    assert response.status_code == 200
    return {'Authorization': f'Bearer {response.json()["access_token"]}'}


@pytest.mark.parametrize(
    'username, password', [('nobody', 'wrong'), ('alice', 'wrong')]
)
def test_login_rejects_invalid_credentials(client, username, password):
    response = client.post('/token', data={'username': username, 'password': password})
    assert response.status_code == 401
    assert response.json()['detail'] == 'Invalid or missing credentials'


def test_predict_requires_token(client):
    response = client.get('/predict')
    assert response.status_code == 401


def test_predict_accepts_regular_user(client):
    response = client.get('/predict', headers=login(client, 'alice', 'alice123'))
    assert response.status_code == 200


def test_predict_rejects_unknown_token(client):
    response = client.get('/predict', headers={'Authorization': 'Bearer unknown-token'})
    assert response.status_code == 401


def test_predict_rejects_expired_token(client):
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    token = jwt.encode(
        {'sub': 'alice', 'exp': expired}, SECRET_KEY, algorithm=ALGORITHM
    )
    response = client.get('/predict', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 401


def test_ingest_forbids_regular_user(client):
    response = client.post('/ingest', headers=login(client, 'alice', 'alice123'))
    assert response.status_code == 403


def test_ingest_permits_admin(client):
    response = client.post('/ingest', headers=login(client, 'admin', 'admin123'))
    assert response.status_code == 200
