.PHONY: run-api kill-api test-api

run-api:
	uv run uvicorn predict.predict:app --reload

test-api:
	curl -X POST 'localhost:8000/predict' \
     -H 'Content-Type: application/json' \
     -d '{"user_ids": [21525]}'
