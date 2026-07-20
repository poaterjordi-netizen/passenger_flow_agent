from __future__ import annotations

import json
from pathlib import Path

from metro_agent.api.app import create_app


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "clients" / "web" / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(target)


if __name__ == "__main__":
    main()
