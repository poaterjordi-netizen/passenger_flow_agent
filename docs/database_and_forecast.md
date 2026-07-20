# Read-only MySQL access and designated-day forecast

## Runtime configuration

Database credentials are runtime secrets and must not be committed. The package reads only these environment variables:

- `METRO_DB_HOST`
- `METRO_DB_PORT` (defaults to `3306`)
- `METRO_DB_USER`
- `METRO_DB_PASSWORD`
- `METRO_DB_NAME`
- `METRO_DB_CONNECT_TIMEOUT` (defaults to `8` seconds)
- `METRO_DB_READ_TIMEOUT` (defaults to `30` seconds)
- `METRO_DB_SSL_CA` (required CA bundle for verified server identity)
- `METRO_DB_ALLOW_INSECURE_TLS` (defaults to `false`; non-production escape hatch only)

The CLI can prompt for the password so it does not appear in shell history:

```bash
export METRO_DB_HOST="<database-host>"
export METRO_DB_PORT="3306"
export METRO_DB_USER="<database-user>"
export METRO_DB_NAME="<database-name>"
export METRO_DB_SSL_CA="/path/to/database-ca.pem"

metro-agent db-station-flow \
  --date 2023-09-27 \
  --limit 100 \
  --output /tmp/station-flow.json \
  --audit /tmp/station-flow-audit.json \
  --prompt-password
```

Do not place a real password in `.env.example`, source files, tests, logs, issue reports, or GitHub Actions.

## Query surface

The production adapter deliberately exposes no arbitrary-SQL method. Supported routes are:

- `db-tables`: bounded table metadata listing;
- `db-describe`: parameterized column metadata for a simple table identifier;
- `db-station-flow`: fixed-column, parameterized access to `clear_stationflow_day`;
- `db-od-flow`: fixed-column, parameterized access to a half-open time window in `Refer_ODFlow_day`.

OD timestamps must be naive service-local `DATETIME` values. Offset-aware ISO timestamps are rejected rather than silently losing their offset during MySQL serialization.

Every connection verifies the server certificate and hostname by default. Every operation executes inside `START TRANSACTION READ ONLY`, is rolled back, and is closed without a commit. Values are bound with PyMySQL parameters. Internally each bounded query reads at most `limit + 1` rows so exact-limit results are distinguished from truncation; exported rows remain capped at `limit`. Audit artifacts record truncation but not credential values, connection endpoints, usernames, or raw bound parameters.

Without `METRO_DB_SSL_CA`, connection setup fails closed. For isolated non-production diagnostics only, `METRO_DB_ALLOW_INSECURE_TLS=true` permits encrypted transport without server identity verification; it must not be used with production credentials. A dedicated database identity with only `SELECT` and metadata permissions is still required even though the client enforces a read-only transaction.

Output and audit paths must be distinct and must not already exist. Both files are prepared as same-directory temporary files; the CLI publishes them only after both writes succeed and removes a newly published output if audit publication fails. This prevents a failed invocation from presenting an old or unaudited artifact as its result.

## Designated-day forecast

The supplied legacy invocation:

```text
python Forecast_flow_designatedday.py -date_refer 2023-09-27 -date_pre 2024-09-29 -scheme_id 58
```

is represented by:

```bash
metro-agent forecast-designated-day \
  --reference-date 2023-09-27 \
  --target-date 2024-09-29 \
  --scheme-id 58 \
  --output /tmp/designated-day-forecast.csv \
  --audit /tmp/designated-day-audit.json \
  --prompt-password
```

The reusable API is `metro_agent.forecasting.forecast_designated_day`. Its active behavior matches the legacy script:

1. read station-level intervals from the first reference date;
2. preserve station, line, inflow, outflow, interval duration, and time-of-day, including cross-midnight intervals;
3. replace the interval calendar date with the target date;
4. add `CreateTime` and `SchemeID`;
5. return a DataFrame or write a local CSV/JSON artifact through the CLI.

It does not insert forecasts, update scheme state, or commit database changes. Those legacy write helpers were intentionally excluded from the runtime path. The old OD-distribution call was commented out in the supplied executable path; the new adapter preserves bounded OD reads but does not silently activate the legacy random allocation or write route.

## Verification boundary

Unit tests use fake database connections and pure DataFrame transformations. Real integration tests are opt-in, credential-injected, read-only, row-limited, and must write outputs only to ignored/local paths. Production rows, schemas inventories, forecast outputs, and query audits must not be committed.
