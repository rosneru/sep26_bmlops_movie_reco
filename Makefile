.PHONY: run-dcs test-dcs-part test-dcs-next test-dcs-no-body test-dcs-invalid \
	run-api run-api-container test-api start-project stop-project train

# Targets that need the secrets (e.g. DAGSHUB_TOKEN) depend on this file.
# Only runs if .env does not exist yet, and then stops with a hint.
.env:
	@echo 'Missing .env: run "cp .env.example .env" and fill in the values.'
	@exit 1
# Logs in at /token and gives the access token: $(call token,PORT,USER,PASSWORD)
token = $$(curl -s -X POST localhost:$(1)/token -d 'username=$(2)&password=$(3)' \
	| python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Start the data collection service API,
# just for testing/debugging
#	uv run uvicorn data_collection_service.main:api --app-dir src --port 8001 --reload --env-file .env
run-dcs: .env src/data_collection_service/Dockerfile
	docker run --env-file .env -p 8001:8001 movie-reco-data-collection

# Test the data collection service
# Requests the data up to part 2
test-dcs-part:
	curl -i -X POST localhost:8001/ingest -H "Authorization: Bearer $(call token,8001,admin,admin123)" \
     -H 'Content-Type: application/json' \
     -d '{"requested_up_to": 2}'

# Requests only the part after the highest one in the bucket
test-dcs-next:
	curl -i -X POST localhost:8001/ingest -H "Authorization: Bearer $(call token,8001,admin,admin123)" \
     -H 'Content-Type: application/json' \
     -d '{"next_part": true}'

# Without body
# Requests the data up to current_part from params.yaml
test-dcs-no-body:
	curl -i -X POST localhost:8001/ingest -H "Authorization: Bearer $(call token,8001,admin,admin123)"

# Request Invalid value 0,
# Returns 422
test-dcs-invalid:
	curl -i -X POST localhost:8001/ingest -H "Authorization: Bearer $(call token,8001,admin,admin123)" \
     -H 'Content-Type: application/json' \
     -d '{"requested_up_to": 0}'

run-api:
	uv run uvicorn predict_service.predict:app --app-dir src --reload

run-api-container:
	docker run --rm -p 8000:8000 movie-reco-api

test-api:
	curl -X POST 'localhost:8000/predict' -H "Authorization: Bearer $(call token,8000,alice,alice123)" \
     -H 'Content-Type: application/json' \
     -d '{"user_ids": [21525]}'

start-project:
	docker compose up -d --build

stop-project:
	docker compose down

# Train the MODEL_TYPE selected in .env (default: knn), rebuilding as needed.
train: .env
	docker compose run --rm --build train
