# CloudBase synthetic demo and governed assistant proxy

This deployment uses a normal CloudBase event function instead of Cloud Run.
It therefore works without a custom domain and does not require enabling the
Cloud Run pay-as-you-go switch. The WeChat client calls the function through
`wx.cloud.callFunction`.

The deployed bundle contains the constrained synthetic service, its metric
registry, and the synthetic CSV fixture. It contains no database credentials,
production rows, or free-form SQL execution path.

The Node.js compatibility function also contains an optional server-side proxy
for the existing assistant API. It does not implement a second assistant and it
does not accept a client-supplied target. Only fixed assistant routes are
forwarded. If `METRO_ASSISTANT_API_BASE_URL` is absent, assistant requests return
503 while the synthetic query and forecast routes continue working.

Build and deploy from the repository root:

```sh
python3 scripts/build_cloudbase_function.py
npx --yes --package @cloudbase/cli@latest tcb \
  --config-file infra/cloudbase/cloudbaserc.json \
  fn deploy metroAgentApi \
  --dir artifacts/cloudbase-function/metroAgentApi \
  --runtime Python3.11
```

The function writes full synthetic audit records only to its ephemeral `/tmp`
directory. The redacted audit summary is returned with every result and cached
by the Mini Program so its audit detail remains available after scale-to-zero.
Production audit retention would require an explicitly governed durable store.

## WeChat-bound environment compatibility bundle

The WeChat IDE can create Node.js functions only. When an official Mini Program
is bound to a WeChat Cloud Development environment that cannot import the
Python environment above, build the equivalent constrained Node.js handler:

```sh
python3 scripts/build_wechat_cloud_function.py
```

Deploy `clients/wechat-miniprogram/cloudfunctions/metroAgentApi` as a normal
cloud function named `metroAgentApi`. This is the conventional WeChat IDE
function root and is ignored because it is a generated deployment artifact.
The build copies the canonical metric registry and synthetic CSV into that
artifact; neither source fixture is duplicated in Git. The compatibility
handler implements the same allowlisted QueryIR aggregations and cannot execute
free-form SQL.

For an authorized staging integration, configure these values in the CloudBase
function environment rather than in source control:

```text
METRO_ASSISTANT_API_BASE_URL=https://assistant-staging.example
METRO_ASSISTANT_API_ACCESS_TOKEN=<server-side secret>
METRO_ASSISTANT_PROXY_TIMEOUT_MS=55000
```

The backend URL must be HTTPS. Plain HTTP is accepted only for an explicit
loopback test with `METRO_ASSISTANT_ALLOW_HTTP=true`. The current free WeChat
CloudBase environment caps function execution at 60 seconds; configure the
function to 60 seconds and keep the proxy timeout below it (55 seconds above).
Environments that support longer execution should use at least 120 seconds.
The function health route actively probes the upstream for five seconds and
reports configured and reachable separately. This configuration or any public
deployment still requires the repository's explicit release gate.
