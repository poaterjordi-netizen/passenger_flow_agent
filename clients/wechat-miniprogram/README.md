# Metro Passenger Flow WeChat Mini Program

This directory is a self-contained native WeChat Mini Program client. It calls
the repository's synthetic-only HTTP API and never connects to a database or
accepts free-form SQL.

## Import into WeChat DevTools

1. Start the API from the repository root with `metro-agent-api`.
2. Open WeChat DevTools and import this directory.
3. Use a real Mini Program AppID in your private DevTools configuration, or keep
   `touristappid` for local development.
4. Open the Settings tab in the Mini Program and save the API base URL.
5. For a phone preview, use an HTTPS staging URL reachable from the phone.

Do not commit AppSecret, database credentials, access tokens, or
`project.private.config.json`.
