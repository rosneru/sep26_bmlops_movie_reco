"""Prediction rollout helpers, called at task execution (not during DAG parsing)."""

import csv
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import docker
import requests
from docker.types import Mount

logger = logging.getLogger(__name__)
PROJECT = 'movie-reco'
REPLICAS = 3


def _replicas(client):
    return client.containers.list(
        filters={
            'label': [
                f'com.docker.compose.project={PROJECT}',
                'com.docker.compose.service=predict',
                'com.docker.compose.oneoff=False',
            ]
        }
    )


def _url(container, network):
    container.reload()
    address = container.attrs['NetworkSettings']['Networks'][network]['IPAddress']
    return f'http://{address}:8000'


def _login(url, username, password):
    """Obtain a fresh JWT without exposing credentials in task logs."""
    from airflow.sdk.log import mask_secret

    response = requests.post(
        url + '/token',
        data={'username': username, 'password': password},
        timeout=10,
    )
    response.raise_for_status()
    token = response.json()['access_token']
    if not isinstance(token, str) or not token.strip():
        raise ValueError('Login did not return a valid access token')
    mask_secret(token)
    return {'Authorization': 'Bearer ' + token}


def _smoke(url, headers, model, user_id, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = requests.get(url + '/model', headers=headers, timeout=5)
            response.raise_for_status()
            if response.json() != model:
                raise ValueError(
                    'Served model does not match selected registry version'
                )
            response = requests.post(
                url + '/predict',
                headers=headers,
                json={'user_ids': [user_id], 'seed': 42},
                timeout=5,
            )
            response.raise_for_status()
            rows = response.json()['recommendations']
            ids = rows[0]['movie_ids']
            if (
                len(rows) != 1
                or rows[0]['user_id'] != user_id
                or len(ids) != 10
                or len(set(ids)) != 10
            ):
                raise ValueError('Unexpected prediction response')
            return
        except (requests.RequestException, ValueError, KeyError, IndexError):
            time.sleep(2)
    raise RuntimeError(f'Prediction smoke check failed for {url}')


def _compose(root, image, name, version):
    # JSON is valid YAML. This override contains version selection, not secrets.
    override = {
        'services': {
            'predict': {
                'image': image,
                'environment': {
                    'PREDICT_MODEL_TYPE': 'knn',
                    'PREDICT_MODEL_NAME': name,
                    'PREDICT_MODEL_VERSION': version,
                },
            }
        }
    }
    with tempfile.TemporaryDirectory(prefix='predict-rollout-') as temporary:
        path = Path(temporary) / 'override.json'
        path.write_text(json.dumps(override))
        command = [
            'docker',
            'compose',
            '--project-directory',
            str(root),
            '-p',
            PROJECT,
            '-f',
            str(root / 'docker-compose.yml'),
            '-f',
            str(path),
            'up',
            '-d',
            '--no-deps',
            '--no-build',
            '--pull',
            'never',
            '--force-recreate',
            '--scale',
            f'predict={REPLICAS}',
            '--wait',
            '--wait-timeout',
            '180',
            'predict',
        ]
        environment = dict(os.environ)
        environment['DAGSHUB_TOKEN'] = os.environ['MLFLOW_TRACKING_PASSWORD']
        # Compose progress is useful in the task log; no credentials in argv.
        subprocess.run(command, env=environment, check=True, timeout=240)


def _reload_nginx(client):
    containers = client.containers.list(
        filters={
            'label': [
                f'com.docker.compose.project={PROJECT}',
                'com.docker.compose.service=nginx',
            ]
        }
    )
    if len(containers) != 1:
        raise RuntimeError('Exactly one running nginx service is required')
    for command in (['nginx', '-t'], ['nginx', '-s', 'reload']):
        if containers[0].exec_run(command).exit_code != 0:
            raise RuntimeError('Nginx validation/reload failed')


def _persist_selection(root, name, version):
    # Preserve credentials/other local settings; update only serving selection.
    path = root / '.env'
    content = path.read_text(encoding='utf-8-sig')
    for key, value in {
        'PREDICT_MODEL_TYPE': 'knn',
        'PREDICT_MODEL_NAME': name,
        'PREDICT_MODEL_VERSION': version,
    }.items():
        pattern = re.compile(rf'^{key}=.*$', re.MULTILINE)
        if pattern.search(content):
            content = pattern.sub(lambda _, line=f'{key}={value}': line, content)
        else:
            content = content.rstrip() + f'\n{key}={value}\n'
    temporary = root / ('.env.rollout-' + uuid4().hex)
    try:
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def deploy_prediction(training_result):
    """Preflight, replace 3 Compose replicas, verify API; restore baseline on error."""
    from airflow.sdk.log import mask_secret

    root = Path(os.environ['AIRFLOW_DOCKER_PROJECT_DIR'])
    name, version = training_result['model_name'], str(training_result['model_version'])
    if name != 'movie-genre-knn' or not version.isdecimal() or int(version) < 1:
        raise ValueError('Expected a specific registered KNN version from training')
    username = os.environ.get('PREDICT_SMOKE_USERNAME', '')
    password = os.environ.get('PREDICT_SMOKE_PASSWORD', '')
    secret = os.environ.get('AUTH_SECRET_KEY', '')
    if not all(value.strip() for value in (username, password, secret)):
        raise ValueError(
            'Set PREDICT_SMOKE_USERNAME, PREDICT_SMOKE_PASSWORD and '
            'AUTH_SECRET_KEY in .env, then recreate airflow-scheduler'
        )
    mask_secret(password)
    mask_secret(secret)
    mask_secret(os.environ['MLFLOW_TRACKING_PASSWORD'])
    with (root / 'data/processed/user_matrix.csv').open() as stream:
        user_id = int(next(csv.DictReader(stream))['userId'])
    expected = {'model_uri': f'models:/{name}/{version}', 'model_type': 'knn'}

    with closing(docker.from_env()) as client:
        existing = _replicas(client)
        if len(existing) != REPLICAS:
            raise RuntimeError(
                'Start exactly three healthy predict replicas before deployment'
            )
        network = next(iter(existing[0].attrs['NetworkSettings']['Networks']))
        headers = _login(_url(existing[0], network), username, password)
        baseline = []
        for container in existing:
            if container.attrs['State'].get('Health', {}).get('Status') != 'healthy':
                raise RuntimeError(
                    'Previous prediction service must be healthy before rollout'
                )
            response = requests.get(
                _url(container, network) + '/model', headers=headers, timeout=10
            )
            response.raise_for_status()
            baseline.append(response.json())
        if (
            any(item != baseline[0] for item in baseline)
            or baseline[0]['model_type'] != 'knn'
        ):
            raise RuntimeError(
                'Previous replicas must serve one consistent KNN version'
            )
        old_name, old_version = (
            baseline[0]['model_uri'].removeprefix('models:/').rsplit('/', 1)
        )
        old_images = {container.attrs['Image'] for container in existing}
        if len(old_images) != 1 or not old_version.isdecimal():
            raise RuntimeError('Cannot capture an unambiguous rollback model/image')
        old_image = next(iter(old_images))
        candidate_image = client.images.get('movie-reco-predict:knn').id

        # Prove that the candidate loads and predicts before touching live replicas.
        environment = {
            key: os.environ[key]
            for key in (
                'MLFLOW_TRACKING_URI',
                'MLFLOW_TRACKING_USERNAME',
                'MLFLOW_TRACKING_PASSWORD',
            )
        }
        environment.update(
            AUTH_SECRET_KEY=secret,
            PREDICT_MODEL_TYPE='knn',
            PREDICT_MODEL_NAME=name,
            PREDICT_MODEL_VERSION=version,
        )
        candidate = client.containers.run(
            candidate_image,
            detach=True,
            network=network,
            environment=environment,
            mounts=[
                Mount(
                    '/app/data/processed',
                    str(root / 'data/processed'),
                    type='bind',
                    read_only=True,
                )
            ],
            labels={
                'project': PROJECT,
                'managed_by': 'airflow',
                'job': 'predict_preflight',
            },
        )
        try:
            _smoke(_url(candidate, network), headers, expected, user_id)
        finally:
            candidate.remove(force=True)

        logger.info('Candidate passed preflight; deploying KNN version %s', version)
        try:
            _compose(root, candidate_image, name, version)
            replicas = _replicas(client)
            if len(replicas) != REPLICAS:
                raise RuntimeError('Prediction replica count differs from three')
            for replica in replicas:
                _smoke(_url(replica, network), headers, expected, user_id, timeout=30)
            _reload_nginx(client)
            _smoke('http://nginx:80', headers, expected, user_id, timeout=30)
            _persist_selection(root, name, version)
        except Exception as error:
            logger.error(
                'Rollout failed; restoring previous model version %s', old_version
            )
            try:
                _compose(root, old_image, old_name, old_version)
                restored = _replicas(client)
                if len(restored) != REPLICAS:
                    raise RuntimeError('Rollback replica count is incorrect')
                for replica in restored:
                    _smoke(
                        _url(replica, network),
                        headers,
                        baseline[0],
                        user_id,
                        timeout=30,
                    )
                _reload_nginx(client)
                _smoke('http://nginx:80', headers, baseline[0], user_id, timeout=30)
                _persist_selection(root, old_name, old_version)
            except Exception as rollback_error:
                raise RuntimeError(
                    'Rollout AND rollback failed; inspect predict/nginx immediately'
                ) from rollback_error
            raise RuntimeError(
                'Rollout failed; previous model/image restored and verified'
            ) from error
    logger.info(
        'Deployment verified: %s on all three replicas and nginx', expected['model_uri']
    )
    return {
        'model_uri': expected['model_uri'],
        'replicas': REPLICAS,
        'training_run_id': training_result['run_id'],
    }
