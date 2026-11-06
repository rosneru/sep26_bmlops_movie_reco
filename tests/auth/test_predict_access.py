"""Integration-style tests of /predict without ML artifacts or external services.

We replace the MLflow model loader with a fake and provide a tiny user matrix,
so these tests need neither mlflow nor the DVC datasets. Authentication itself
is not mocked.
"""

import importlib
import sys
import types

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY


class FakeRecommender:
    genres = ('feature',)
    movie_ids = np.arange(1, 21)
    uri = 'models:/fake/1'
    model_type = 'fake'

    def candidates(self, users, n_neighbors):
        raise AssertionError('The unknown-ID request must fail before model inference')


@pytest.fixture
def predict_client(tmp_path, monkeypatch):
    user_path = tmp_path / 'users.csv'
    pd.DataFrame({'userId': [21525], 'feature': [1.0]}).to_csv(user_path, index=False)
    monkeypatch.setenv('USER_MATRIX_PATH', str(user_path))

    # predict.py imports load_registered_model from this module. The fake
    # module returns a FakeRecommender, so mlflow is never imported.
    fake_loader = types.ModuleType('predict_service.model_loader')
    fake_loader.load_registered_model = FakeRecommender
    monkeypatch.setitem(sys.modules, 'predict_service.model_loader', fake_loader)

    sys.modules.pop('predict_service.predict', None)
    module = importlib.import_module('predict_service.predict')
    try:
        yield TestClient(module.app)
    finally:
        # The next test imports predict.py again, which registers the counter again
        REGISTRY.unregister(module.PREDICTION_REQUESTS)
        sys.modules.pop('predict_service.predict', None)


def login(client, username, password):
    return client.post('/token', data={'username': username, 'password': password})


def test_unknown_movielens_user_id_returns_404_after_auth(predict_client):
    token = login(predict_client, 'alice', 'alice123').json()['access_token']
    response = predict_client.post(
        '/predict',
        headers={'Authorization': f'Bearer {token}'},
        json={'user_ids': [999999999]},
    )
    assert response.status_code == 404
    assert response.json() == {'detail': 'Unknown user ids: [999999999]'}


def test_unknown_login_username_is_rejected_at_login(predict_client):
    response = login(predict_client, 'nonexistent', 'some-password')
    assert response.status_code == 401


def test_predict_requires_authentication(predict_client):
    response = predict_client.post('/predict', json={'user_ids': [21525]})
    assert response.status_code == 401
