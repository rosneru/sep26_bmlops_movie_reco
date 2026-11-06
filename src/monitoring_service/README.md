# Monitoring service

Prometheus scrapes itself and each prediction replica every 15 seconds. Grafana
automatically loads the Prometheus data source and the **Movie Recommendation
API Monitoring** dashboard from the repository.

The dashboard shows prediction requests per replica since startup, the combined
request rate over five minutes, and the number of reachable prediction replicas.
The handler graph shows cumulative requests that reached the prediction handler
on each replica. The status table includes authentication failures too.
Use the status counter alone for overall traffic totals.

The counter records each POST to `/predict` by HTTP status, including requests
rejected during authentication. A restart resets that replica's counters. Data drift detection and alerts are outside the
current monitoring scope.

## Prerequisites

Install Docker with Docker Compose. Prometheus and Grafana run in containers; no local Python packages are needed for these monitoring services. Starting the full application also requires the model and data described in the root README.

Run the commands below from the repository root.

## Configure credentials

If you do not already have a local `.env`, copy the example:

```bash
cp .env.example .env
```

If `.env` already exists, preserve its contents and add any missing variables from `.env.example` instead. Set `GRAFANA_ADMIN_USER` and a nonempty `GRAFANA_ADMIN_PASSWORD`. The local `.env` is ignored by Git; never commit or share credentials. Shell environment variables can also supply these values and take precedence over `.env`.

Compose reports an error if either required variable is missing or empty. Grafana uses these credentials to initialize the admin account on first startup. Once its database exists, editing `.env` does not change the existing account's password; use Grafana's account settings to change it.

## Start

Validate the configuration without printing resolved credentials:

```bash
docker compose config --quiet
```

Start just the monitoring services:

```bash
docker compose up -d prometheus grafana
```

Or start the entire prepared application:

```bash
docker compose up -d --build
```

Inspect service status and logs:

```bash
docker compose ps
docker compose logs --tail=50 prometheus grafana
```

## Verify

1. Open http://localhost:9090/targets. The `prometheus` target should be **UP**. With prediction running, the `prediction` job should show three **UP** targets.
2. Open http://localhost:3000 and sign in with your configured credentials.
3. Under **Connections → Data sources**, confirm that **Prometheus** already exists.
4. Open **Explore**, select **Prometheus**, switch the query editor to **Code**, and run:

   ```promql
   up{job="prometheus"}
   ```

   A value of `1` confirms that Grafana can query Prometheus and Prometheus successfully scraped itself. Allow at least one scrape interval after startup.

Grafana connects to `http://prometheus:9090` using Compose service discovery. Prometheus scrapes `localhost:9090` because that target is inside its own container. Browser URLs use the ports published on the host.

## Generate demo traffic

With Nginx and the prediction replicas running, use the
[prediction demo script](../../scripts/demo_prediction.py) from the repository root:

```bash
python3 scripts/demo_prediction.py --user-id 4 --authenticated 30 --unauthenticated 10
```

The script prompts for the API password. It defaults to the demo username
`alice`. Use `--username` for a different account and choose a user ID in the
loaded dataset. The script summarizes the HTTP responses. With valid credentials
and a valid user ID, expect 30 responses with HTTP 200 and 10 with HTTP 401.

After the next scrape, open **Movie Recommendation API Monitoring** in Grafana.
The per-replica counters should increase by 40 in total. To see the outcomes
separately, run this query in Grafana Explore:

```promql
sum by (status) (prediction_requests_total{job="prediction",status!=""})
```

Compare the values before and after the demo. HTTP 200 should increase by 30
and HTTP 401 by 10.

## Configuration and storage

- `prometheus/prometheus.yml`: scrape configuration, mounted read-only.
- `grafana/provisioning/datasources/prometheus.yml`: automatically provisions the default Prometheus data source, mounted read-only.
- `grafana/provisioning/dashboards/prediction.yml` and `grafana/dashboards/`: dashboard provider and versioned dashboard JSON, mounted read-only.
- `prometheus_data`: named volume mounted at `/prometheus` to preserve collected metrics across container recreation, subject to Prometheus retention settings.
- `grafana_data`: named volume mounted at `/var/lib/grafana` to preserve Grafana's database, accounts, and saved dashboards.

Grafana uses `restart: unless-stopped`: Docker restarts it automatically unless it was deliberately stopped. Its `depends_on` starts Prometheus first but does not wait for Prometheus readiness.

Stop the monitoring containers without removing their volumes:

```bash
docker compose stop grafana prometheus
```

`docker compose down` removes the project's containers and network but preserves named volumes. **`docker compose down -v` also deletes the project's named volumes**, including monitoring history and Grafana accounts/settings. Do not use `-v` for a routine restart.
