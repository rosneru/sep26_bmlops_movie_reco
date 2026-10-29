"""Unit/API tests for the shared demo authentication dependency."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from user_authentication_service.auth import require_admin, require_predict_access


@pytest.fixture
def client():
    app = FastAPI()

    @app.get('/predict', dependencies=[Depends(require_predict_access)])
    def prediction():
        return {'ok': True}

    @app.post('/ingest', dependencies=[Depends(require_admin)])
    def ingest():
        return {'ok': True}

    return TestClient(app)


@pytest.mark.parametrize('auth', [None, ('nobody', 'wrong'), ('alice', 'wrong')])
def test_predict_rejects_missing_or_invalid_basic_credentials(client, auth):
    response = client.get('/predict', auth=auth)
    assert response.status_code == 401
    assert response.json()['detail'] == 'Invalid or missing credentials'


def test_predict_accepts_regular_user_basic_credentials(client):
    response = client.get('/predict', auth=('alice', 'alice123'))
    assert response.status_code == 200


def test_predict_accepts_valid_bearer_token(client):
    response = client.get('/predict', headers={'Authorization': 'Bearer bob-token'})
    assert response.status_code == 200


def test_predict_rejects_unknown_bearer_token(client):
    response = client.get('/predict', headers={'Authorization': 'Bearer unknown-token'})
    assert response.status_code == 401


def test_ingest_forbids_regular_user(client):
    response = client.post('/ingest', auth=('alice', 'alice123'))
    assert response.status_code == 403


def test_ingest_permits_admin(client):
    response = client.post('/ingest', auth=('admin', 'admin123'))
    assert response.status_code == 200
