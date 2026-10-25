import mlflow
import mlflow.sklearn

from sklearn.datasets import load_iris
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

# Connect to MLflow Server
mlflow.set_tracking_uri("http://localhost:5000")

# Select experiment
mlflow.set_experiment("movie-recommendation-test")

# Load sample dataset
X, y = load_iris(return_X_y=True)

X_train, X_test, y_train, y_test = train_test_split(
    X, y,
    test_size=0.2,
    random_state=42,
)

# Train a simple model
model = RandomForestClassifier(
    n_estimators=100,
    random_state=42,
)

model.fit(X_train, y_train)

# Evaluate model
predictions = model.predict(X_test)
accuracy = accuracy_score(y_test, predictions)

# Track experiment and register model
with mlflow.start_run(run_name="model-registry-test"):

    mlflow.log_param("model_type", "RandomForest")
    mlflow.log_param("n_estimators", 100)
    mlflow.log_metric("accuracy", accuracy)

    model_info = mlflow.sklearn.log_model(
        sk_model=model,
        name="model",
        registered_model_name="movie-recommender-test",
        input_example=X_train[:2],
        skops_trusted_types=[
            "sklearn.tree._tree.Tree"
        ],
    )

    print("Model URI:", model_info.model_uri)
    print("Accuracy:", accuracy)

print("Model registration completed!")