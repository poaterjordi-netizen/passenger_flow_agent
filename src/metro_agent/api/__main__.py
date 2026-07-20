from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("METRO_API_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("METRO_API_PORT", "8000"))
    except ValueError as exc:
        raise SystemExit("METRO_API_PORT must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise SystemExit("METRO_API_PORT must be between 1 and 65535")
    uvicorn.run("metro_agent.api.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
