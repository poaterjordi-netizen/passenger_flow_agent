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
- `METRO_DB_TLS_CERT_SHA256` (optional exact SHA-256 pin for a CA-verified leaf certificate)
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

When a legacy MySQL certificate has no usable DNS/IP subject alternative name, set both
`METRO_DB_SSL_CA` and `METRO_DB_TLS_CERT_SHA256`. The adapter first validates the certificate
chain against the configured CA and then compares the live leaf certificate DER fingerprint
in constant time before creating a cursor or issuing SQL. Audit provenance reports
`ca_and_certificate_pin`; the pin, certificate, host, user, and password stay outside Git.

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

## Assistant production-shadow mode

The HTTP assistant remains synthetic by default. A real database can enter the governed
assistant loop only through explicit `production-shadow` mode. Shadow results are not admitted
for operational decisions, and `production-readonly` is intentionally not selectable yet.

In addition to the verified-TLS database variables above, the runtime must inject approved
metadata:

```bash
export METRO_API_DATA_MODE="production-shadow"
export METRO_API_ACCESS_TOKEN="<runtime-secret>"
export METRO_PRODUCTION_SOURCE_STATUS="approved"
export METRO_PRODUCTION_CITY="<approved-city-id>"
export METRO_PRODUCTION_SOURCE_VERSION="<approved-source-version>"
export METRO_PRODUCTION_TIME_GRAIN="<10m|15m|30m|hour|day>"
export METRO_PRODUCTION_DEFAULT_START="<timezone-aware-start>"
export METRO_PRODUCTION_DEFAULT_END="<timezone-aware-end>"
export METRO_PRODUCTION_REGISTRY_PATH="/approved/external/source-registry.json"
export METRO_LOGICAL_REGISTRY_PATH="config/logical_data_products.json"
export METRO_PRODUCTION_ASSISTANT_ENABLED="false"
export METRO_PROMOTION_GATE_PATH="/approved/runtime/config/production_promotion_gates.json"
export METRO_ACCESS_SUBJECT_ID="<gateway-subject>"
export METRO_ACCESS_TENANT_OR_DEPARTMENT="<department>"
export METRO_ACCESS_ROLES="shadow-reader"
export METRO_ACCESS_ALLOWED_CITIES="<approved-city-id>"
export METRO_ACCESS_ALLOWED_METRICS="entries,exits,net_inflow"
export METRO_ACCESS_ALLOWED_DATASET_ROLES="actual"
export METRO_ACCESS_MAX_TIME_RANGE_HOURS="24"
export METRO_ACCESS_ROW_LIMIT="100"
export METRO_ACCESS_EXPORT_POLICY="deny"
export METRO_ACCESS_POLICY_SNAPSHOT_ID="<immutable-policy-version>"
export METRO_MODEL_ENDPOINT_POLICY_ID="<approved-or-denied-policy-version>"
export METRO_MODEL_DATA_EGRESS="deny"
export METRO_MODEL_INTENT_EGRESS="deny"
export METRO_MODEL_ALLOWED_PROVIDER="<exact-approved-provider>"
export METRO_MODEL_ALLOWED_MODEL="<exact-approved-model>"
export METRO_MODEL_ALLOWED_TARGET_HASH="<sha256-from-governance-status>"
```

Registry 被拆成两层：`config/logical_data_products.json` 可入 Git，管理逻辑数据产品、指标、
维度、时间语义、质量门 ID 和访问策略 ID；仓库外 registry 遵循
`schemas/data_source_registry.schema.json`，只在部署侧解析固定物理 mapping、不可变版本和
内部负责人信息。物理 mapping hash 由实际执行的固定 SQL adapter 源码与 adapter 版本计算，启动时与外部登记值精确比对，不再用登记行自身的 hash 代替可执行 mapping 证据。执行证据同时记录 logical registry、physical mapping 和 query template 的版本/哈希。
`approved-current`、`latest` 等动态别名会被拒绝。

启动时还必须构造完整的服务端 `AccessContext`。它不从请求正文、Prompt 或记忆读取，包含
subject、tenant/department、roles、可用城市/指标/数据角色、最大时间范围、行数、导出策略、
模型出域策略和策略快照。session、run、audit 都绑定 owner 与 access scope hash，回读时重新
执行对象级授权。静态 token 适配器当前只适合单 subject 部署，生产仍应由网关/IdP 替换。

Startup fails closed if metadata is missing, the registry has no single exact approved match,
its quality gate is not `pass`, access context is incomplete, an API access token is absent, or
verified TLS cannot be configured. The shadow
adapter currently admits only `entries`, `exits`, and `net_inflow`
from the fixed station-flow route. It requires matching city, source version, actual-data role,
one service day, an admitted grain, and bounded filters. Truncated source results are rejected.
查询结果对必需客流列执行 fail-closed 质量检查：缺列、`NULL`、字符串、布尔值、NaN/无穷大和负数均不会被默认为 0。Catalog 中的“注册质量通过”与“本次运行质量通过”分离；本次查询前 runtime quality 是 `unknown`，查询通过后才在 provenance/audit 记录源行数、缺失/非法行数、TLS、只读回滚事务和查询模板 hash。

生产 ToolRegistry 注册批准的 P0 查询工具以及只返回缺口的能力准入检查工具；不注册会生成数值
预测、公交匹配、GIS、SOP、实体解析或报告导出的合成实现。大型活动问题会先读取真实实际客流
上下文，再返回场馆映射、活动时间、相似活动实绩、模型回测和 SOP 的准入缺口；不会套用合成
活动系数，也不会把可用实绩窗口冒充活动预测基线。
生产 Assistant 默认关闭；离线比对需要显式启用，真实 Evidence 默认不得发送到模型。

The transport-neutral MCP façade is in `metro_agent.mcp_facade`. It delegates to the same
`ToolRegistry` and has no arbitrary SQL, table browsing, file-system, shell, write, notification,
or operational-action tool. Rank/growth operations are not exposed through MCP because their
completeness guarantee depends on server-originated upstream results, not caller-supplied rows.

## Local real-data + GPT-5.6 Sol shadow

`scripts/run_live_local.sh` is the single local launcher for the currently approved test path.
It retrieves the database password from macOS Keychain, reads connection metadata, CA and leaf
pin from a private external config directory, performs a bounded read-only preflight, then starts
FastAPI and the Web dashboard. The browser never receives the API token: Vite adds it only in the
server-side production-preview proxy. The built Web assets use the `/real-shadow/` base path and
the proxy admits only `/health` and `/api` upstream routes; Vite source and filesystem routes are
not exposed.

Required external files (default directory
`~/.config/metro-passenger-flow-agent`, mode `0700`) are:

- `live.env`: `METRO_DB_HOST`, `METRO_DB_PORT`, `METRO_DB_USER`, and `METRO_DB_NAME` only;
- `mysql-ca.pem`: trusted MySQL CA certificate;
- `mysql-leaf.sha256`: exact lowercase SHA-256 leaf certificate fingerprint.

Store the password under the Keychain service
`com.metro-passenger-flow-agent.mysql`, then launch explicitly:

```bash
METRO_LOCAL_LIVE_SHADOW_ACKNOWLEDGED=true ./scripts/run_live_local.sh
```

The launcher binds Hermes Codex to the exact `gpt-5.6-sol` model and audits each evidence-egress
payload hash, provider/model/target binding, outcome, and token usage. Results are labeled local
`production-shadow`: database values are real, but source city/business semantics and formal
production promotion are still unverified. Therefore the website must not present them as a
current operational view or enable write, notification, export, arbitrary SQL, or automatic
control actions.

The temporary password-gated Aliyun ingress, one-click operator controls, outage behavior, and
acceptance checks are documented in [`real_shadow_demo.md`](real_shadow_demo.md). It is an
explicitly approved tender-demo exception, not a production promotion.

For server-side OpenAI testing, use `METRO_ASSISTANT_PROVIDER=openai` with a runtime-injected
`OPENAI_API_KEY` and set `METRO_ASSISTANT_REASONING_EFFORT` explicitly. The adapter uses the
stateless Responses API (`/v1/responses`, `store:false`) and strict `text.format` JSON Schemas.
Keep `METRO_MODEL_DATA_EGRESS=deny` while validating real database semantics. Test model egress
separately with synthetic Evidence before approving only aggregated, redacted Evidence Packets.
