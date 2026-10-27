"""Coordinate training, tracking and export through the selected implementation."""

import tempfile
from pathlib import Path

import mlflow

from src import config
from src.train_service.models import implementation


def main():
    for name, value in {
        'MLFLOW_TRACKING_URI': config.MLFLOW_TRACKING_URI,
        'MLFLOW_EXPERIMENT_NAME': config.MLFLOW_EXPERIMENT_NAME,
        'MLFLOW_REGISTERED_MODEL_NAME': config.MLFLOW_REGISTERED_MODEL_NAME,
    }.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{name} cannot be empty')

    settings = implementation.resolve_settings(config)

    mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
    mlflow.set_registry_uri(config.MLFLOW_TRACKING_URI)
    mlflow.set_experiment(config.MLFLOW_EXPERIMENT_NAME)

    with mlflow.start_run(run_name=config.MLFLOW_RUN_NAME) as run:
        data = implementation.load_data(config.PROCESSED_DATA_DIR)
        parameters = implementation.parameters(settings, data)

        mlflow.log_params(parameters)
        mlflow.set_tags(implementation.run_tags())
        mlflow.log_dict(data['metadata'], 'data/metadata.json')
        result = implementation.train(
            data,
            settings,
            on_epoch=lambda epoch, metrics: mlflow.log_metrics(metrics, step=epoch),
        )
        mlflow.log_metrics(result['metrics'])
        with tempfile.TemporaryDirectory() as temporary:
            model_directory = Path(temporary) / 'model'
            implementation.export(
                result,
                data,
                parameters,
                model_directory,
                source_root=config.PROJECT_ROOT / 'src',
                run_id=run.info.run_id,
            )
            # Upload the exported model, then create a version in the registry.
            mlflow.log_artifacts(str(model_directory), artifact_path='model')
            model_uri = f'runs:/{run.info.run_id}/model'
            version = mlflow.register_model(model_uri, config.MLFLOW_REGISTERED_MODEL_NAME)

        client = mlflow.MlflowClient()

        # TODO Registration can succeed before tagging fails
        version_tags = {
            **implementation.registry_tags(data),
            'source_training_run_id': run.info.run_id,
        }
        for key, value in version_tags.items():
            client.set_model_version_tag(
                config.MLFLOW_REGISTERED_MODEL_NAME, str(version.version), key, str(value)
            )

        print(f'MLflow run ID: {run.info.run_id}')
        print(f'Registry URI: models:/{config.MLFLOW_REGISTERED_MODEL_NAME}/{version.version}')


if __name__ == '__main__':
    main()
