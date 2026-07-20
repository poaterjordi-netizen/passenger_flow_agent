# Metro Passenger Flow WeChat Mini Program

This directory is a self-contained native WeChat Mini Program client. Its
experience build calls the synthetic-only CloudBase function through
`wx.cloud.callFunction`, so no custom domain is required. A local HTTP mode is
kept for development. Neither mode connects the client to a database or accepts
free-form SQL.

## Import into WeChat DevTools

1. Open WeChat DevTools and import this directory.
2. Use the project's real Mini Program AppID.
3. Associate the AppID with the CloudBase environment configured in
   `miniprogram/config/index.js`.
4. Deploy `metroAgentApi` as described in `../../infra/cloudbase/README.md`.
5. Compile or preview the Mini Program; the default “stable demo” mode needs no
   HTTP domain configuration.

For local API development, start `metro-agent-api`, choose “local debug” on the
Settings tab, and keep `http://127.0.0.1:8000` in the simulator.

Do not commit AppSecret, database credentials, access tokens, or
`project.private.config.json`.
