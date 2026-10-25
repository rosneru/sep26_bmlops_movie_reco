import argparse
import hashlib
import json
import tempfile
from pathlib import Path

import mlflow
import mlflow.pytorch as mlflow_pytorch
import numpy as np
import torch
from mlflow import MlflowClient

from src.config import (
    MLFLOW_TRACKING_URI,
    MLFLOW_REGISTERED_MODEL_NAME,
    MODELS_DIR,
)
from src.train_service.train_model import TwoTower


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_json(path):
    return json.loads(
        Path(path).read_text(encoding='utf-8')
    )


def file_sha256(path):
    digest = hashlib.sha256()

    with Path(path).open('rb') as stream:
        for chunk in iter(
            lambda: stream.read(1024 * 1024),
            b'',
        ):
            digest.update(chunk)

    return digest.hexdigest()


def download_artifact(client, run_id, name, directory):
    return Path(
        client.download_artifacts(
            run_id,
            name,
            str(directory),
        )
    )


def restore_checkpoint(path):
    checkpoint = torch.load(
        path,
        map_location='cpu',
        weights_only=True,
    )

    model = TwoTower(
        input_dim=checkpoint['input_dim'],
        hidden_dim=checkpoint['hidden_dim'],
        embedding_dim=checkpoint['embedding_dim'],
    )

    model.load_state_dict(
        checkpoint['model_state_dict']
    )

    return model.eval(), checkpoint


def compare_predictions(first, second, input_dim):
    """Check prediction consistency on fixed probe inputs."""
    generator = torch.Generator().manual_seed(12345)

    users = torch.rand(
        32,
        input_dim,
        generator=generator,
    )
    movies = torch.rand(
        32,
        input_dim,
        generator=generator,
    )

    users = torch.nn.functional.normalize(
        users,
        dim=1,
    )
    movies = torch.nn.functional.normalize(
        movies,
        dim=1,
    )

    first.eval()
    second.eval()

    with torch.no_grad():
        expected = first(users, movies)
        actual = second(users, movies)

    require(
        torch.isfinite(expected).all().item(),
        'Reference predictions contain invalid values',
    )
    require(
        torch.isfinite(actual).all().item(),
        'Loaded model predictions contain invalid values',
    )

    torch.testing.assert_close(
        actual,
        expected,
        rtol=1e-6,
        atol=1e-7,
    )

    return float(
        (actual - expected).abs().max().item()
    )


def test_tracking(client, run_id):
    run = client.get_run(run_id)

    require(
        run.info.status == 'FINISHED',
        f'Expected FINISHED run, got {run.info.status}',
    )

    for name in (
        'epochs',
        'batch_size',
        'learning_rate',
        'pairs_per_user',
        'eval_pairs_per_user',
        'label',
    ):
        require(
            name in run.data.params,
            f'Missing parameter: {name}',
        )

    require(
        run.data.params['label'] == 'genre_cosine',
        'Unexpected training label type',
    )

    epochs = int(run.data.params['epochs'])
    require(epochs > 0, 'Invalid epoch count')

    histories = {}

    for name in ('train_rmse', 'val_rmse'):
        history = client.get_metric_history(
            run_id,
            name,
        )
        histories[name] = history

        require(
            len(history) == epochs,
            f'Unexpected number of values for {name}',
        )

        require(
            {metric.step for metric in history}
            == set(range(1, epochs + 1)),
            f'Incomplete epoch history: {name}',
        )

        require(
            all(
                np.isfinite(metric.value)
                and metric.value >= 0
                for metric in history
            ),
            f'Invalid values in {name}',
        )

    with tempfile.TemporaryDirectory() as directory:
        path = download_artifact(
            client,
            run_id,
            'training/metrics.json',
            directory,
        )
        saved = read_json(path)

    expected_metrics = {
        'best_epoch': saved['best_epoch'],
        'best_val_rmse': saved['best_val_rmse'],
        'test_rmse': saved['test']['rmse'],
        'test_mae': saved['test']['mae'],
        'test_cosine_baseline_rmse': (
            saved['test']['cosine_baseline_rmse']
        ),
    }

    for name, expected in expected_metrics.items():
        require(
            name in run.data.metrics,
            f'Missing metric: {name}',
        )

        actual = run.data.metrics[name]

        require(
            np.isfinite(actual)
            and np.isfinite(expected),
            f'Non-finite metric: {name}',
        )

        require(
            np.isclose(
                actual,
                expected,
                rtol=1e-7,
                atol=1e-9,
            ),
            f'Metric differs from metrics.json: {name}',
        )

    best_validation = min(
        histories['val_rmse'],
        key=lambda metric: (
            metric.value,
            metric.step,
        ),
    )

    require(
        run.data.metrics['best_epoch']
        == best_validation.step,
        'Best epoch differs from validation history',
    )

    require(
        np.isclose(
            run.data.metrics['best_val_rmse'],
            best_validation.value,
        ),
        'Best validation RMSE differs from history',
    )

    print(
        'PASS: experiment tracking, epoch history, '
        'best epoch, and saved metrics'
    )

    return run


def test_artifacts(client, run_id):
    local_checkpoint = (
        MODELS_DIR
        / 'two_tower'
        / run_id
        / 'checkpoint.pt'
    )

    require(
        local_checkpoint.is_file(),
        f'Local checkpoint not found: {local_checkpoint}',
    )

    artifact_names = (
        'training/checkpoint.pt',
        'training/metrics.json',
        'training/registration.json',
        'data/metadata.json',
        'data/data_manifest.json',
    )

    hashes = {}

    with tempfile.TemporaryDirectory() as directory:
        paths = {}

        for name in artifact_names:
            path = download_artifact(
                client,
                run_id,
                name,
                directory,
            )

            require(
                path.is_file(),
                f'Artifact not downloaded: {name}',
            )

            hashes[name] = file_sha256(path)
            paths[name] = path

        require(
            file_sha256(local_checkpoint)
            == hashes['training/checkpoint.pt'],
            'Local and downloaded checkpoint hashes differ',
        )

        downloaded_model, checkpoint = restore_checkpoint(
            paths['training/checkpoint.pt']
        )

        local_model, _ = restore_checkpoint(
            local_checkpoint
        )

        metadata = read_json(
            paths['data/metadata.json']
        )

        require(
            checkpoint['genres'] == metadata['genres'],
            'Checkpoint and metadata genre order differ',
        )

        max_difference = compare_predictions(
            local_model,
            downloaded_model,
            checkpoint['input_dim'],
        )

    print(
        'PASS: artifact download, checkpoint hash, '
        'genre schema, and prediction equality'
    )
    print(
        f'Max prediction difference: {max_difference:.10f}'
    )

    return hashes


def test_registry(client, run_id, model_name, version):
    model_version = client.get_model_version(
        model_name,
        str(version),
    )

    require(
        model_version.status == 'READY',
        f'Model version is not READY: {model_version.status}',
    )

    require(
        model_version.run_id == run_id,
        'Model version belongs to a different training run',
    )

    with tempfile.TemporaryDirectory() as directory:
        registration_path = download_artifact(
            client,
            run_id,
            'training/registration.json',
            directory,
        )
        registration = read_json(registration_path)

        require(
            registration['model_name'] == model_name
            and str(registration['model_version'])
            == str(version),
            'Requested version differs from registration.json',
        )

        checkpoint_path = download_artifact(
            client,
            run_id,
            'training/checkpoint.pt',
            directory,
        )

        reference_model, checkpoint = restore_checkpoint(
            checkpoint_path
        )

        registry_uri = (
            f'models:/{model_name}/{version}'
        )

        loaded_model = mlflow_pytorch.load_model(
            registry_uri,
            map_location='cpu',
        )

        max_difference = compare_predictions(
            reference_model,
            loaded_model,
            checkpoint['input_dim'],
        )

    print(
        'PASS: registered version provenance, '
        'model loading, and prediction equality'
    )
    print(f'Registry URI: {registry_uri}')
    print(
        f'Max prediction difference: {max_difference:.10f}'
    )


def persistence_snapshot(client, run_id):
    run = test_tracking(client, run_id)
    hashes = test_artifacts(client, run_id)

    return {
        'run_id': run_id,
        'experiment_id': run.info.experiment_id,
        'status': run.info.status,
        'params': run.data.params,
        'metrics': run.data.metrics,
        'artifact_hashes': hashes,
    }


def test_persistence(client, run_id, stage):
    snapshot_path = (
        MODELS_DIR
        / 'two_tower'
        / run_id
        / 'persistence_snapshot.json'
    )

    if stage == 'before-restart':
        require(
            not snapshot_path.exists(),
            'Snapshot already exists. Run after-restart '
            'before starting another persistence test.',
        )

        snapshot = persistence_snapshot(
            client,
            run_id,
        )

        snapshot_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        snapshot_path.write_text(
            json.dumps(snapshot, indent=2),
            encoding='utf-8',
        )

        print(
            f'PASS: pre-restart snapshot saved: {snapshot_path}'
        )

    else:
        require(
            snapshot_path.is_file(),
            'Run before-restart first',
        )

        previous = read_json(snapshot_path)
        current = persistence_snapshot(
            client,
            run_id,
        )

        require(
            current == previous,
            'Run information or artifacts changed after restart',
        )

        print(
            'PASS: run information, metrics, artifacts, '
            'and checkpoint predictions survived restart'
        )


def main():
    parser = argparse.ArgumentParser(
        description='Validate MLflow using an existing training run'
    )

    parser.add_argument(
        '--stage',
        required=True,
        choices=(
            'tracking',
            'artifacts',
            'before-restart',
            'after-restart',
            'registry',
        ),
    )
    parser.add_argument(
        '--run-id',
        required=True,
    )
    parser.add_argument(
        '--model-name',
        default=MLFLOW_REGISTERED_MODEL_NAME,
    )
    parser.add_argument(
        '--version',
        default='1',
    )

    args = parser.parse_args()

    mlflow.set_tracking_uri(
        MLFLOW_TRACKING_URI
    )
    mlflow.set_registry_uri(
        MLFLOW_TRACKING_URI
    )

    client = MlflowClient()

    if args.stage == 'tracking':
        test_tracking(
            client,
            args.run_id,
        )

    elif args.stage == 'artifacts':
        test_artifacts(
            client,
            args.run_id,
        )

    elif args.stage == 'registry':
        test_registry(
            client,
            args.run_id,
            args.model_name,
            args.version,
        )

    else:
        test_persistence(
            client,
            args.run_id,
            args.stage,
        )


if __name__ == '__main__':
    main()