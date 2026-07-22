# WeChat Mini Program, intelligent analysis, and mobile API

## Scope

The mobile client contains the original synthetic query/forecast experience and
an Intelligent Analysis tab backed by the same assistant API as the Web console.
It keeps the existing product boundary intact:

- the client cannot connect to MySQL;
- the client cannot submit SQL or unknown metrics;
- free language is compiled to strict SemanticFrame and then constrained QueryIR;
- every query compiles through the existing QueryIR validator and deterministic
  engine;
- every successful mobile query and forecast produces a server-side audit;
- the Mini Program renders entity/metric linking, semantic memory, model runtime,
  evidence, tool results, state-machine events, and verification status;
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
    pages/assistant/                 GPT-first intelligent analysis and trace UI
    pages/audit/                     sanitized audit summary
    pages/settings/                  API environment selection
scripts/check_miniprogram.py         dependency-free structure check
infra/cloudbase/...-nodejs/          synthetic API plus allowlisted assistant proxy
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

When the API is started with the governed Hermes provider and production-shadow
data adapter, the Mini Program's local HTTP mode calls the same real
`metroflow + gpt-5.6-sol` assistant as the Web page. Assistant requests may take
up to 180 seconds; query and forecast requests keep the shorter timeout.
With `scripts/run_live_local.sh`, set the Mini Program HTTP base URL to
`http://127.0.0.1:5173`; the Web development proxy supplies the ephemeral API
token. Do not copy that token into the client.

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

For a phone preview, the checked-in default is the fixed Aliyun ingress
`https://metro.9m-zx.com/assistant-bridge`. Add
`https://metro.9m-zx.com` to the Mini Program's permitted request domains, then
use DevTools Preview or Remote Debugging. The ECS Nginx instance strips the
`/assistant-bridge` prefix and forwards traffic over an SSH reverse tunnel to
the local Vite proxy. Vite injects the ephemeral API bearer token, so no token,
database credential, or model credential is stored in the Mini Program, Git, or
the ECS Nginx configuration.

If a phone or strict DevTools build reports `request:fail url not in domain
list`, the request was blocked before it reached Nginx, the reverse tunnel, or
Hermes. Verify that the WeChat console is managing AppID
`wxcec9562590faa1a0`, and that `https://metro.9m-zx.com` is visibly saved under
Development Settings -> Server Domains -> request legal domains. After saving,
clear the DevTools network cache and completely close and reopen the Mini
Program. Keep request-domain validation enabled so a simulator cannot hide a
phone-only configuration failure.

The bridge uses the externally stored SSH identity and known-hosts file already
used by the read-only database tunnel:

```bash
scripts/manage_assistant_bridge.sh foreground
scripts/manage_assistant_bridge.sh status
```

The production-like phone path is therefore:

```text
Mini Program -> metro.9m-zx.com/assistant-bridge -> ECS Nginx
  -> 127.0.0.1:18080 -> restricted SSH reverse tunnel
  -> local Vite proxy -> local FastAPI -> metroflow + Hermes gpt-5.6-sol
```

The fixed domain survives tunnel reconnects and process restarts. The Mac must
remain powered on, logged in, and online because Hermes is intentionally kept
local in this transitional deployment.

The runtime config schema is versioned. Existing experience-version users whose
stored selection predates this release are migrated once to the fixed Aliyun
ingress, including old CloudBase, localhost, and temporary-tunnel selections. A
CloudBase or local-debug choice saved after this release remains available as an
explicit fallback.

On the current Mac, two user LaunchAgents keep the local runtime and reverse
tunnel alive and restart them after network interruption or user login:

```text
com.metro-passenger-flow-agent.live
com.metro-passenger-flow-agent.assistant-bridge
```

Their source plists live under `infra/macos/`; installed copies belong under
`~/Library/LaunchAgents/`. Runtime logs stay outside Git under
`~/.local/share/metro-passenger-flow-agent/logs/`.

Alternatively, configure the CloudBase function's allowlisted server-side proxy:

```text
METRO_ASSISTANT_API_BASE_URL=https://assistant-staging.example
METRO_ASSISTANT_API_ACCESS_TOKEN=<server-side secret>
METRO_ASSISTANT_PROXY_TIMEOUT_MS=55000
```

Set the function timeout to the environment's maximum supported value. The
current free WeChat CloudBase environment permits 60 seconds, so use a proxy
timeout below that boundary (for example `55000`) to return a structured error
before the platform terminates the function. Paid/staging environments that
support it should use at least 120 seconds. Do not put these values in the Mini
Program package or Git. The proxy accepts only the fixed
assistant capabilities/session/message/run/events/feedback routes. Its target is
not client-controlled, and an unconfigured proxy returns HTTP 503.

The CloudBase `/health` response actively probes the configured upstream and
reports `assistant_proxy.reachable`; it does not treat a stored URL as proof of
availability. The Settings page additionally calls capabilities and creates a
real session. It only displays “service and intelligent analysis are both
normal” after that handshake, and shares the established session with the
Intelligent Analysis tab.

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
- run a first-turn database question and a follow-up that inherits semantic memory;
- inspect SemanticFrame, entity/metric resolution, model usage, QueryIR tools,
  evidence, verifier status, and result rows on the Intelligent Analysis tab;
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
