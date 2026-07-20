# WeChat Mini Program and synthetic mobile API

## Scope

The first mobile version is an experience client for the repository's synthetic
fixtures. It keeps the existing product boundary intact:

- the client cannot connect to MySQL;
- the client cannot submit SQL or unknown metrics;
- every query compiles through the existing QueryIR validator and deterministic
  engine;
- every successful mobile query and forecast produces a server-side audit;
- the forecast is a reference-day copy baseline, not a production-accuracy
  claim and not a database write path.

Production data, WeChat login, deployment, and publication require separate
authorization.

## Source layout

```text
src/metro_agent/api/                 Python HTTP service
clients/wechat-miniprogram/          isolated WeChat DevTools project
  project.config.json
  miniprogram/
    pages/dashboard/                 metric overview
    pages/query/                     constrained query form and results
    pages/forecast/                  designated-day preview
    pages/audit/                     sanitized audit summary
    pages/settings/                  API environment selection
scripts/check_miniprogram.py         dependency-free structure check
tests/test_api_app.py                API route and boundary tests
tests/test_api_service.py            service, audit, query, forecast tests
```

## Run the API locally

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
metro-agent-api
```

The default endpoints are:

- health: `http://127.0.0.1:8000/health`
- OpenAPI: `http://127.0.0.1:8000/openapi.json`
- interactive docs: `http://127.0.0.1:8000/docs`

The defaults read only `examples/synthetic_data/` and write runtime audits under
the ignored `artifacts/api-audits/` directory. Override settings through process
environment variables, never by committing a secret file:

```bash
export METRO_API_HOST=0.0.0.0
export METRO_API_PORT=8000
export METRO_API_AUDIT_DIR=/var/lib/metro-agent/audits
export METRO_API_ACCESS_TOKEN='staging-only-token'
metro-agent-api
```

The bearer token is an optional staging guard, not a production user identity.
A production release must replace it with server-side WeChat login exchange and
role-based authorization. Never place a WeChat AppSecret or database credential
inside the Mini Program package.

## Open in WeChat DevTools

1. Install and sign in to WeChat DevTools.
2. Import `clients/wechat-miniprogram/` as the project directory.
3. Keep `touristappid` for a local simulator, or select the real Mini Program
   AppID in the untracked private project configuration.
4. Start the API and compile the Mini Program.
5. Open the Settings tab and test `http://127.0.0.1:8000` in the desktop
   simulator. For local HTTP only, disable request-domain validation in your
   untracked DevTools project settings; keep validation enabled for staging and
   release builds.

For a phone preview, deploy the API to a reachable HTTPS staging domain, add it
to the Mini Program's permitted request domains, save that URL on the Settings
tab, and then use DevTools Preview or Remote Debugging. A phone cannot use the
computer's `127.0.0.1` address.

## Experience-version test

1. Run all repository verification and inspect the generated OpenAPI contract.
2. Upload a fixed build from WeChat DevTools.
3. Set that uploaded build as the experience version in Mini Program management.
4. Add only authorized experience members.
5. Test on at least one current Android device and one current iPhone.
6. Record the build version, API environment, test cases, and audit IDs used for
   acceptance.

Suggested mobile acceptance cases:

- load the four metric cards and station ranking;
- query each registered metric with allowed dimensions;
- reject an end time that is not after the start time;
- filter by line, station, and direction;
- render empty results without inventing values;
- generate a target-day preview while retaining passenger counts;
- open the audit summary from both query and forecast results;
- handle an invalid token, unreachable host, timeout, and malformed response;
- confirm no screen or log displays credentials or raw SQL.

## Verification

```bash
python3 scripts/check_miniprogram.py
python3 -m unittest discover -s tests -v
metro-agent validate \
  --metrics examples/synthetic_data/metrics.json \
  --gold-cases examples/synthetic_data/gold_cases.json \
  --data examples/synthetic_data/passenger_flow.csv
```

Publishing, production access, and real-data testing are deliberately outside
this first version and require an explicit approval gate.
