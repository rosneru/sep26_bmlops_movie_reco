.PHONY: run-api kill-api test-api

# Start the data collection service API,
# just for testing/debugging
run-dcs:
	uv run uvicorn data_collection_service.ingest:api --app-dir src --port 8001 --reload

# Test the data collection service
# Requests the data up to part 2
test-dcs-part:
	curl -i -X POST localhost:8001/ingest \
     -H 'Content-Type: application/json' \
     -d '{"up_to_part": 2}'

# Without body
# Will later respond the current_part from params.yaml
test-dcs-no-body:
	curl -i -X POST localhost:8001/ingest

# Request Invalid value 0,
# Will later return 422
test-dcs-invalid:
	curl -i -X POST localhost:8001/ingest \
     -H 'Content-Type: application/json' \
     -d '{"up_to_part": 0}'

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
