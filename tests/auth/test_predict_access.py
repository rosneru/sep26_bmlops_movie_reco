"""Integration-style tests of /predict without ML artifacts or external services.

We stub model loading and provide tiny CSV matrices so these tests can run
without downloading the DVC datasets. Authentication itself is not mocked.
"""

import importlib
import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient


class FakeNearestNeighbors:
    def kneighbors(self, users):
        raise AssertionError('The unknown-ID request must fail before model inference')


@pytest.fixture
def predict_client(tmp_path, monkeypatch):
    user_path = tmp_path / 'users.csv'
    movie_path = tmp_path / 'movies.csv'
    pd.DataFrame({'userId': [21525], 'feature': [1.0]}).to_csv(user_path, index=False)
    pd.DataFrame({'movieId': [1, 2]}).to_csv(movie_path, index=False)
    model_path = tmp_path / 'model.pkl'
    model_path.write_bytes(b'placeholder')

    monkeypatch.setenv('MODEL_PATH', str(model_path))
    monkeypatch.setenv('USER_MATRIX_PATH', str(user_path))
    monkeypatch.setenv('MOVIE_MATRIX_PATH', str(movie_path))

    # Avoid unpickling a large model or requiring an exact sklearn version.
    import pickle
    monkeypatch.setattr(pickle, 'load', lambda stream: FakeNearestNeighbors())
    sys.modules.pop('predict_service.predict', None)
    try:
        module = importlib.import_module('predict_service.predict')
        yield TestClient(module.app)
    finally:
        sys.modules.pop('predict_service.predict', None)


def test_unknown_movielens_user_id_returns_404_after_auth(predict_client):
    response = predict_client.post(
        '/predict', auth=('alice', 'alice123'), json={'user_ids': [999999999]}
    )
    assert response.status_code == 404
    assert response.json() == {'detail': 'Unknown user ids: [999999999]'}


def test_unknown_login_username_returns_401_before_user_lookup(predict_client):
    response = predict_client.post(
        '/predict', auth=('nonexistent', 'some-password'), json={'user_ids': [999999999]}
    )
    assert response.status_code == 401


def test_predict_requires_authentication(predict_client):
    response = predict_client.post('/predict', json={'user_ids': [21525]})
    assert response.status_code == 401
