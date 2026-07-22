# Metro Passenger Flow WeChat Mini Program

This directory is a self-contained native WeChat Mini Program client. Query and
designated-day forecast screens and the Intelligent Analysis tab use the same
fixed Aliyun HTTPS ingress by default. The Intelligent Analysis tab uses the same
assistant session API, SemanticFrame, constrained QueryIR tools, evidence packet,
and verifier as the Web console. CloudBase remains an optional fallback. The
client never connects to MySQL or
accepts free-form SQL.

## Import into WeChat DevTools

1. Open WeChat DevTools and import this directory.
2. Use the project's real Mini Program AppID.
3. Add `https://metro.9m-zx.com` to the Mini Program request-domain allowlist.
4. Start the local live service and restricted reverse bridge described in
   `../../docs/mobile_miniprogram.md`.
5. Compile or preview the Mini Program. Its default API base is
   `https://metro.9m-zx.com/assistant-bridge`.

The Intelligent Analysis tab is immediately usable in DevTools when local HTTP
mode points at the same running API as the Web console. CloudBase mode requires
the function's server-side assistant proxy to be configured; otherwise the page
returns an explicit configuration message rather than a fabricated answer.
The Settings connection test checks the fixed ingress, assistant capabilities,
and a real assistant session handshake. “Service and intelligent analysis are
both normal” is shown only after all three succeed.

For local API development, start `metro-agent-api`, choose “local debug” on the
Settings tab, and keep `http://127.0.0.1:8000` in the simulator.

When `scripts/run_live_local.sh` is running, use `http://127.0.0.1:5173` instead.
Its Vite same-origin proxy supplies the ephemeral server token without copying it
into the Mini Program or Git.

Do not commit AppSecret, database credentials, access tokens, or
`project.private.config.json`.
