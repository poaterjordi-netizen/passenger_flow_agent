# Password-gated real-data shadow demo

## Scope

`https://metro.9m-zx.com/real-shadow/` is a temporary, operator-supervised tender demo. It keeps
the existing synthetic site at `/` unchanged and exposes only the governed local
`production-shadow` runtime behind a separate HTTP Basic Auth realm.

The path is deliberately transitional:

- the Mac must be powered on, logged in, online, and able to use the existing Hermes/Codex login;
- the MySQL password remains only in macOS Keychain;
- the database is reached through the existing restricted SSH forward and the ECS VPC;
- the model receives only policy-approved intent metadata and aggregate Evidence Packets;
- the page displays a persistent non-production and human-review warning;
- write operations, export, notification, free-form SQL, source browsing, and operational control
  are unavailable.

It is not a 24×7 service and does not satisfy production promotion gates.

## Request path

```text
browser
  -> HTTPS /real-shadow/ + independent Basic Auth
  -> Aliyun ECS Nginx rate and concurrency limits
  -> ECS loopback 127.0.0.1:18080
  -> restricted reverse SSH tunnel
  -> local production-preview proxy on 127.0.0.1:5173
  -> ephemeral server-side Bearer token
  -> local FastAPI on 127.0.0.1:8000
  -> constrained QueryIR + fixed read-only MySQL adapter
  -> aggregate Evidence Packet + local Hermes/Codex gpt-5.6-sol
```

The browser, ECS, and Git repository never receive the database password, Hermes OAuth material,
or the ephemeral API Bearer token. Nginx binds the reverse endpoint only on ECS loopback. The
reverse bridge reuses the restricted `metro-tunnel` identity and pinned SSH host key already used
by the mobile experience.

## Operator controls

Two user LaunchAgents keep the local runtime and encrypted reverse bridge alive:

```text
com.metro-passenger-flow-agent.live
com.metro-passenger-flow-agent.assistant-bridge
```

Use the wrapper from the repository root:

```bash
scripts/manage_real_shadow.sh status
scripts/manage_real_shadow.sh start
scripts/manage_real_shadow.sh stop
```

`stop` unloads only the public reverse bridge and leaves the local read-only runtime running. It
also temporarily disconnects the Mini Program assistant because both approved public clients use
the same restricted bridge. `start` reloads both LaunchAgents, performs the bounded database
preflight, builds production Web assets, starts the local API and preview proxy, and waits for the
bridge to become healthy.

The separate Web password is stored outside Git in macOS Keychain:

```text
service: com.metro-passenger-flow-agent.real-shadow-basic
account: metro-shadow
```

Do not add it to this document, source code, shell history, Nginx configuration, or screenshots.
Only its one-way APR1 hash belongs on the ECS in the dedicated Nginx password file.

## Public gateway rules

The ECS Nginx configuration must keep these controls together:

- a dedicated `Metro real-shadow` Basic Auth realm and password file;
- a general API bucket sized for the dashboard's bounded QueryIR fan-out;
- an independent low-rate assistant-message bucket and a single concurrent model request per
  source IP, so page loading cannot consume the model-message allowance;
- `GET`/`HEAD` only for Web assets and health, and `GET`/`POST` only for approved API routes;
- a small request-body limit;
- 190-second upstream timeout for supervised model calls;
- `proxy_intercept_errors` with an explicit offline page that links back to the synthetic demo;
- no proxy route for `/docs`, `/redoc`, `/openapi.json`, arbitrary local paths, or Vite development
  endpoints.

When the Mac, network, Hermes session, or tunnel is unavailable, Nginx returns a clear `503`
message. It must not fall back to synthetic values under a real-data label and must not invent a
model answer.

## Verification

The minimum acceptance sequence is:

1. unauthenticated `/real-shadow/` returns `401` with realm `Metro real-shadow`;
2. the original `/` still uses its original password and returns `synthetic` after login;
3. authenticated `/real-shadow/health` returns `production-shadow` and `shadow-configured`;
4. catalog contains only registered metrics and the bounded approved time window;
5. a fixed query produces a verified, redacted audit and no database write;
6. one natural-language ranking case reports `gpt-5.6-sol`, model semantic compilation,
   deterministic planning, approved tools, and `verification.valid=true`;
7. stopping the bridge produces the explicit offline response while `/` remains available;
8. restarting the bridge restores the same fixed URL without changing browser credentials.

Before code handoff, also run the repository unit tests, Ruff, contract validation CLI, and Web
build. Never retain real query responses or source rows inside Git artifacts.

## Production replacement

Before any 24×7 or wider release, replace the high-privilege transitional database account with a
dedicated TLS-only `SELECT` account, move model execution to an approved server-side API or
enterprise model platform, use a real identity provider instead of shared Basic Auth, and complete
the repository's promotion, data-owner, security, and acceptance gates.
