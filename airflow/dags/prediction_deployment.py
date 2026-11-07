"""Prediction rollout helpers, called at task execution (not during DAG parsing)."""

import csv
import logging
import os
import subprocess
import time
from contextlib import closing
from pathlib import Path

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


def _start_prediction(root, model_name):
    environment = dict(
        os.environ,
        DAGSHUB_TOKEN=os.environ['MLFLOW_TRACKING_PASSWORD'],
        PREDICT_MODEL_TYPE='knn',
        PREDICT_MODEL_NAME=model_name,
    )
    subprocess.run(
        [
            'docker',
            'compose',
            '-p',
            PROJECT,
            '-f',
            str(root / 'docker-compose.yml'),
            'up',
            '-d',
            '--no-build',
            '--wait',
            '--wait-timeout',
            '180',
            '--scale',
            f'predict={REPLICAS}',
            'predict',
            'nginx',
        ],
        env=environment,
        check=True,
        timeout=240,
    )


def _candidate_login(url, username, password):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            return _login(url, username, password)
        except requests.ConnectionError:
            time.sleep(2)
    raise RuntimeError('Candidate API did not start in time')


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


def _registry_alias(method, name, alias, version=None, allow_missing=False):
    endpoint = (
        os.environ['MLFLOW_TRACKING_URI'].rstrip('/')
        + '/api/2.0/mlflow/registered-models/alias'
    )
    auth = (
        os.environ['MLFLOW_TRACKING_USERNAME'],
        os.environ['MLFLOW_TRACKING_PASSWORD'],
    )
    fields = {'name': name, 'alias': alias}
    if method == 'GET':
        if allow_missing:
            # Missing-alias error codes differ across registry implementations.
            # Read aliases from the model instead; missing models/auth failures
            # must still raise rather than being mistaken for an absent alias.
            response = requests.get(
                endpoint.removesuffix('/alias') + '/get',
                params={'name': name},
                auth=auth,
                timeout=15,
            )
            response.raise_for_status()
            aliases = response.json()['registered_model'].get('aliases', [])
            return next(
                (str(item['version']) for item in aliases if item['alias'] == alias),
                None,
            )
        response = requests.get(endpoint, params=fields, auth=auth, timeout=15)
        response.raise_for_status()
        return str(response.json()['model_version']['version'])

    if method == 'DELETE':
        response = requests.delete(endpoint, json=fields, auth=auth, timeout=15)
    else:
        response = requests.post(
            endpoint, json={**fields, 'version': version}, auth=auth, timeout=15
        )
    response.raise_for_status()


def _deployment_containers(client):
    """Inventory only this project's serving containers, including stopped ones."""
    return [
        container
        for service in ('predict', 'nginx')
        for container in client.containers.list(
            all=True,
            filters={
                'label': [
                    f'com.docker.compose.project={PROJECT}',
                    f'com.docker.compose.service={service}',
                ]
            },
        )
    ]


def _recover_initial_deployment(client, before_ids, name, alias, version, previous):
    """Restore the alias and remove newly created serving containers, not volumes."""
    errors = []
    try:
        selected = _registry_alias('GET', name, alias, allow_missing=True)
        if selected not in (version, previous):
            raise RuntimeError('Alias changed externally; refusing to overwrite it')
        if selected != previous:
            if previous is None:
                _registry_alias('DELETE', name, alias)
            else:
                _registry_alias('POST', name, alias, previous)
        if _registry_alias('GET', name, alias, allow_missing=True) != previous:
            raise RuntimeError('Initial alias restoration could not be verified')
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as error:
        errors.append(error)
    # Cleanup is still attempted if restoring the registry fails.
    for container in _deployment_containers(client):
        if container.id not in before_ids:
            try:
                container.remove(force=True)
            except docker.errors.DockerException as error:
                errors.append(error)
    if errors:
        raise RuntimeError(
            'Initial deployment recovery was incomplete; inspect alias and serving containers'
        ) from errors[0]


def deploy_prediction(training_result):
    """Preflight, promote, and verify a KNN version on the prediction replicas."""
    from airflow.sdk.log import mask_secret

    root = Path(os.environ['AIRFLOW_DOCKER_PROJECT_DIR'])
    name, version = training_result['model_name'], str(training_result['model_version'])
    if name != 'movie-genre-knn' or not version.isdecimal() or int(version) < 1:
        raise ValueError('Expected a specific registered KNN version from training')
    selector = os.environ.get('PREDICT_MODEL_VERSION', '')
    if not selector.startswith('@') or not selector[1:].strip():
        raise ValueError(
            'Set PREDICT_MODEL_VERSION in .env to an MLflow alias selector, '
            'for example @latest-verified, before deployment.'
        )
    alias = selector[1:]
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
        if existing and len(existing) != REPLICAS:
            raise RuntimeError(
                'Expected either no running prediction replicas or three'
            )
        if existing:
            network = next(iter(existing[0].attrs['NetworkSettings']['Networks']))
            headers = _login(_url(existing[0], network), username, password)
            baseline = []
            for container in existing:
                if (
                    container.attrs['State'].get('Health', {}).get('Status')
                    != 'healthy'
                ):
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
            if old_name != name or any(
                f'PREDICT_MODEL_VERSION={selector}'
                not in container.attrs['Config']['Env']
                for container in existing
            ):
                raise RuntimeError(
                    'All replicas must be configured for the same serving alias'
                )
            previous_alias_version = _registry_alias('GET', name, alias)
            if previous_alias_version != old_version:
                logger.warning(
                    'Serving alias points to version %s, but replicas serve %s; '
                    'continuing with candidate validation. Rollback after promotion '
                    'will restore the actually served version %s.',
                    previous_alias_version,
                    old_version,
                    old_version,
                )
            candidate_image = next(iter(old_images))

        else:
            initial_containers = _deployment_containers(client)
            if any(
                container.labels.get('com.docker.compose.service') == 'predict'
                for container in initial_containers
            ):
                raise RuntimeError(
                    'Stopped prediction containers exist; reconcile or remove them '
                    'before an initial deployment'
                )
            before_ids = {container.id for container in initial_containers}
            previous_alias_version = _registry_alias(
                'GET', name, alias, allow_missing=True
            )
            network = f'{PROJECT}_default'
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
            candidate_url = _url(candidate, network)
            if not existing:
                headers = _candidate_login(candidate_url, username, password)
            _smoke(candidate_url, headers, expected, user_id)
        finally:
            candidate.remove(force=True)

        logger.info('Candidate passed preflight; deploying KNN version %s', version)
        if (
            _registry_alias('GET', name, alias, allow_missing=not existing)
            != previous_alias_version
        ):
            raise RuntimeError('The serving alias changed during candidate preflight')
        rollout_started = False
        try:
            _registry_alias('POST', name, alias, version)
            rollout_started = True
            if existing:
                for replica in existing:
                    replica.restart(timeout=15)
            else:
                _start_prediction(root, name)
            replicas = _replicas(client)
            if len(replicas) != REPLICAS:
                raise RuntimeError('Prediction replica count differs from three')
            for replica in replicas:
                _smoke(_url(replica, network), headers, expected, user_id, timeout=30)
            _reload_nginx(client)
            _smoke('http://nginx:80', headers, expected, user_id, timeout=30)
            if _registry_alias('GET', name, alias) != version:
                raise RuntimeError('The serving alias changed during rollout')
        except Exception as error:
            if not existing:
                _recover_initial_deployment(
                    client, before_ids, name, alias, version, previous_alias_version
                )
                raise RuntimeError(
                    'Initial prediction deployment failed; previous alias state '
                    'restored and newly created serving containers removed'
                ) from error
            logger.error(
                'Rollout failed; restoring previous model version %s', old_version
            )
            try:
                selected = _registry_alias('GET', name, alias)
                if selected not in (version, previous_alias_version):
                    raise RuntimeError(
                        'Alias changed externally; refusing to overwrite it'
                    )
                # A registry write may succeed even if its response is lost.
                restore_served = rollout_started or (
                    selected == version and selected != previous_alias_version
                )
                rollback_version = (
                    old_version if restore_served else previous_alias_version
                )
                if selected != rollback_version:
                    _registry_alias('POST', name, alias, rollback_version)
                if restore_served:
                    for replica in existing:
                        replica.restart(timeout=15)
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
