.PHONY: run-api kill-api test-api

run-api:
	uv run uvicorn predict_service.predict:app --app-dir src --reload

run-api-container:
	docker run --rm -p 8000:8000 movie-reco-api

test-api:
	curl -X POST 'localhost:8000/predict' \
     -H 'Content-Type: application/json' \
     -d '{"user_ids": [21525]}'

start-project:
	docker compose up -d --build

stop-project:
	docker compose down
