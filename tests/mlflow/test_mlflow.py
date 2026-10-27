import mlflow
from pathlib import Path
import tempfile

mlflow.set_tracking_uri("http://localhost:5000")
mlflow.set_experiment("movie-recommendation-test")

with mlflow.start_run(run_name="artifact-storage-test") as run:

    mlflow.log_param("model_type", "collaborative_filtering")
    mlflow.log_param("epochs", 10)

    mlflow.log_metric("rmse", 0.85)
    mlflow.log_metric("mae", 0.62)

    # Create a temporary artifact file
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_file = Path(temp_dir) / "model_info.txt"

        artifact_file.write_text(
            "Movie Recommendation Model\n"
            "Algorithm: Collaborative Filtering\n"
            "RMSE: 0.85\n",
            encoding="utf-8",
        )

        # Upload artifact to MLflow Server
        mlflow.log_artifact(str(artifact_file))

    print("Run ID:", run.info.run_id)
    print("Artifact URI:", mlflow.get_artifact_uri())

print("Artifact storage test successful!")