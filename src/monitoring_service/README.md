# Monitoring service

The current baseline runs Prometheus and Grafana through the root Docker Compose configuration. Prometheus scrapes its own metrics every 15 seconds. Grafana's Prometheus data source is provisioned automatically from versioned YAML.

Prediction API metrics, drift detection, application dashboards, and alerts are not implemented yet. A healthy Prometheus self-target does not establish prediction API availability or model quality.

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

1. Open http://localhost:9090/targets. The `prometheus` target should be **UP**.
2. Open http://localhost:3000 and sign in with your configured credentials.
3. Under **Connections → Data sources**, confirm that **Prometheus** already exists.
4. Open **Explore**, select **Prometheus**, switch the query editor to **Code**, and run:

   ```promql
   up{job="prometheus"}
   ```

   A value of `1` confirms that Grafana can query Prometheus and Prometheus successfully scraped itself. Allow at least one scrape interval after startup.

Grafana connects to `http://prometheus:9090` using Compose service discovery. Prometheus scrapes `localhost:9090` because that target is inside its own container. Browser URLs use the ports published on the host.

## Configuration and storage

- `prometheus/prometheus.yml`: scrape configuration, mounted read-only.
- `grafana/provisioning/datasources/prometheus.yml`: automatically provisions the default Prometheus data source, mounted read-only.
- `prometheus_data`: named volume mounted at `/prometheus` to preserve collected metrics across container recreation, subject to Prometheus retention settings.
- `grafana_data`: named volume mounted at `/var/lib/grafana` to preserve Grafana's database, accounts, and saved dashboards.

Grafana uses `restart: unless-stopped`: Docker restarts it automatically unless it was deliberately stopped. Its `depends_on` starts Prometheus first but does not wait for Prometheus readiness.

Stop the monitoring containers without removing their volumes:

```bash
docker compose stop grafana prometheus
```

`docker compose down` removes the project's containers and network but preserves named volumes. **`docker compose down -v` also deletes the project's named volumes**, including monitoring history and Grafana accounts/settings. Do not use `-v` for a routine restart.
