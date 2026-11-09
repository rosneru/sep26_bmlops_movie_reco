"""Offline integration checks using a disposable registry and real model exports."""

import asyncio
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import jwt
import mlflow
import numpy as np
import pandas as pd
from mlflow.exceptions import MlflowException

SOURCE_ROOT = Path(__file__).resolve().parents[2] / 'src'
sys.path.append(str(SOURCE_ROOT))
from predict_service.model_loader import load_registered_model
from src.train_service.models import knn
from user_authentication_service.auth import ALGORITHM, SECRET_KEY


class RegistryPredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.old_cwd = Path.cwd()
        os.chdir(cls.root)
        cls.env = patch.dict(
            os.environ,
            {
                'MLFLOW_TRACKING_URI': os.getenv(
                    'MLFLOW_TEST_TRACKING_URI', f'sqlite:///{cls.root}/registry.db'
                ),
                'PREDICT_MODEL_TYPE': 'knn',
                'PREDICT_MODEL_NAME': 'review-knn',
                'PREDICT_MODEL_VERSION': '1',
            },
        )
        cls.env.start()
        mlflow.set_tracking_uri(os.environ['MLFLOW_TRACKING_URI'])
        mlflow.set_registry_uri(mlflow.get_tracking_uri())
        mlflow.set_experiment('prediction-integration')
        cls.movies = pd.DataFrame(
            {
                'movieId': np.arange(100, 130),
                'Action': np.arange(30) % 2,
                'Drama': np.arange(30) % 3,
            }
        )
        cls.movies.to_csv(cls.root / 'movie_matrix.csv', index=False)
        cls.data = knn.load_data(cls.root)
        cls.settings = {
            'n_neighbors': 20,
            'algorithm': 'ball_tree',
            'metric': 'euclidean',
        }
        cls.result = knn.train(cls.data, cls.settings)
        for number in [1, 2]:
            with mlflow.start_run() as run:
                directory = cls.root / f'knn-{number}'
                knn.export(
                    cls.result,
                    cls.data,
                    knn.parameters(cls.settings, cls.data),
                    directory,
                    source_root=SOURCE_ROOT,
                    run_id=run.info.run_id,
                )
                mlflow.log_artifacts(str(directory), artifact_path='model')
                mlflow.register_model(f'runs:/{run.info.run_id}/model', 'review-knn')

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        os.chdir(cls.old_cwd)
        cls.temp.cleanup()

    def test_pinned_version_and_reordered_features(self):
        recommender = load_registered_model()
        self.assertTrue(recommender.uri.endswith('/1'))
        users = pd.DataFrame({'Drama': [1.0], 'unused': [99], 'Action': [0.0]})
        expected = self.result['model'].kneighbors(
            users[['Action', 'Drama']], return_distance=False
        )
        np.testing.assert_array_equal(recommender.candidates(users, 20), expected)
        np.testing.assert_array_equal(recommender.movie_ids, self.movies.movieId)

    def test_invalid_version(self):
        for version in ['0', '-1', 'invalid']:
            with (
                self.subTest(version=version),
                patch.dict(os.environ, {'PREDICT_MODEL_VERSION': version}),
                self.assertRaisesRegex(ValueError, 'positive registry'),
            ):
                load_registered_model()

    def test_latest_resolves_to_newest_numeric_version(self):
        for version in ['', 'latest']:
            with (
                self.subTest(version=version),
                patch.dict(os.environ, {'PREDICT_MODEL_VERSION': version}),
            ):
                recommender = load_registered_model()
                self.assertEqual(recommender.uri, 'models:/review-knn/2')

    def test_alias_resolves_once_to_loaded_numeric_version(self):
        client = mlflow.MlflowClient()
        client.set_registered_model_alias('review-knn', 'latest-verified', '1')
        with patch.dict(os.environ, {'PREDICT_MODEL_VERSION': '@latest-verified'}):
            first = load_registered_model()
            client.set_registered_model_alias('review-knn', 'latest-verified', '2')
            self.assertEqual(first.uri, 'models:/review-knn/1')
            self.assertEqual(load_registered_model().uri, 'models:/review-knn/2')

    def test_empty_registry_requires_training(self):
        with (
            patch.dict(
                os.environ,
                {'PREDICT_MODEL_VERSION': '', 'PREDICT_MODEL_NAME': 'not-registered'},
            ),
            self.assertRaisesRegex(ValueError, 'run training first'),
        ):
            load_registered_model()

    def test_missing_version_does_not_fall_back(self):
        with (
            patch.dict(os.environ, {'PREDICT_MODEL_VERSION': '999'}),
            self.assertRaises(MlflowException),
        ):
            load_registered_model()

    def test_old_model_without_catalog_requires_retraining(self):
        with mlflow.start_run() as run:
            directory = self.root / 'legacy-model'
            mlflow.sklearn.save_model(
                self.result['model'],
                str(directory),
                pip_requirements=['scikit-learn==1.4.2'],
                serialization_format='pickle',
            )
            mlflow.log_artifacts(str(directory), artifact_path='model')
            mlflow.register_model(f'runs:/{run.info.run_id}/model', 'legacy-knn')
        with (
            patch.dict(os.environ, {'PREDICT_MODEL_NAME': 'legacy-knn'}),
            self.assertRaisesRegex(ValueError, 'retrain'),
        ):
            load_registered_model()

    def test_type_mismatch(self):
        with (
            patch.dict(os.environ, {'PREDICT_MODEL_TYPE': 'two_tower'}),
            self.assertRaisesRegex(ValueError, 'type does not match'),
        ):
            load_registered_model()

    def test_api_auth_seed_and_registered_movie_mapping(self):
        user_file = self.root / 'users.csv'
        pd.DataFrame({'userId': [1], 'Drama': [1.0], 'Action': [0.0]}).to_csv(
            user_file, index=False
        )
        with patch.dict(os.environ, {'USER_MATRIX_PATH': str(user_file)}):
            sys.modules.pop('predict_service.predict', None)
            api = importlib.import_module('predict_service.predict').app

        async def request(path, body, authorized=True):
            messages = []
            headers = [(b'content-type', b'application/json')]
            if authorized:
                expire = datetime.now(timezone.utc) + timedelta(minutes=5)
                token = jwt.encode(
                    {'sub': 'alice', 'exp': expire}, SECRET_KEY, algorithm=ALGORITHM
                )
                headers.append((b'authorization', f'Bearer {token}'.encode()))

            scope = {
                'type': 'http',
                'asgi': {'version': '3.0'},
                'http_version': '1.1',
                'method': 'POST' if path == '/predict' else 'GET',
                'scheme': 'http',
                'path': path,
                'raw_path': path.encode(),
                'query_string': b'',
                'root_path': '',
                'headers': headers,
                'server': ('test', 80),
                'client': ('test', 1),
            }

            async def receive():
                return {
                    'type': 'http.request',
                    'body': json.dumps(body).encode(),
                    'more_body': False,
                }

            async def send(message):
                messages.append(message)

            await api(scope, receive, send)
            status = next(
                m['status'] for m in messages if m['type'] == 'http.response.start'
            )
            payload = b''.join(
                m.get('body', b'')
                for m in messages
                if m['type'] == 'http.response.body'
            )
            return status, json.loads(payload)

        body = {'user_ids': [1], 'seed': 42}
        first = asyncio.run(request('/predict', body))
        self.assertEqual(first, asyncio.run(request('/predict', body)))
        self.assertEqual(first[0], 200)
        ids = first[1]['recommendations'][0]['movie_ids']
        self.assertEqual(len(set(ids)), 10)
        self.assertTrue(set(ids) <= set(self.movies.movieId))
        self.assertEqual(asyncio.run(request('/predict', body, False))[0], 401)
        self.assertEqual(asyncio.run(request('/predict', {'user_ids': [999]}))[0], 404)
        self.assertEqual(
            asyncio.run(request('/model', {}))[1]['model_uri'], 'models:/review-knn/1'
        )
        bad_file = self.root / 'bad-users.csv'
        pd.DataFrame({'userId': [1], 'Action': [1]}).to_csv(bad_file, index=False)
        with patch.dict(os.environ, {'USER_MATRIX_PATH': str(bad_file)}):
            sys.modules.pop('predict_service.predict', None)
            with self.assertRaisesRegex(ValueError, 'lacks model genres'):
                importlib.import_module('predict_service.predict')

    @unittest.skipUnless(
        importlib.util.find_spec('torch'), 'optional PyTorch image required'
    )
    def test_two_tower_catalog_export_and_scoring(self):
        import torch

        from src.train_service.models.two_tower import TwoTower, export

        model = TwoTower(2, 4, 2).eval()
        movies = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
        movies /= np.linalg.norm(movies, axis=1, keepdims=True)
        data = {
            'genres': ['Action', 'Drama'],
            'movie_ids': np.array([30, 10, 20]),
            'movies': torch.from_numpy(movies),
        }
        with mlflow.start_run() as run:
            directory = self.root / 'two-tower'
            export(
                {'model': model},
                data,
                {'serialization_format': 'pickle', 'model_type': 'two_tower'},
                directory,
                source_root=SOURCE_ROOT,
                run_id=run.info.run_id,
            )
            mlflow.log_artifacts(str(directory), artifact_path='model')
            mlflow.register_model(f'runs:/{run.info.run_id}/model', 'review-two-tower')
        with patch.dict(
            os.environ,
            {
                'PREDICT_MODEL_TYPE': 'two_tower',
                'PREDICT_MODEL_NAME': 'review-two-tower',
            },
        ):
            recommender = load_registered_model()
        users = pd.DataFrame({'Drama': [4.0], 'Action': [3.0]})
        with torch.inference_mode():
            scores = (
                model.encode_users(torch.tensor([[0.6, 0.8]]))
                @ model.encode_movies(data['movies']).T
            )
        np.testing.assert_array_equal(
            recommender.candidates(users, 3), torch.topk(scores, 3).indices.numpy()
        )
        np.testing.assert_array_equal(recommender.movie_ids, data['movie_ids'])
        with self.assertRaisesRegex(ValueError, 'without genre'):
            recommender.candidates(pd.DataFrame({'Action': [0.0], 'Drama': [0.0]}), 3)
