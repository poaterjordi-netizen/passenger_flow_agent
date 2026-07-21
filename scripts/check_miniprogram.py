#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = ROOT / "clients" / "wechat-miniprogram"
SOURCE_ROOT = CLIENT_ROOT / "miniprogram"


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid JSON: {path.relative_to(ROOT)}: {exc}") from exc


def main() -> int:
    project = _load_json(CLIENT_ROOT / "project.config.json")
    app = _load_json(SOURCE_ROOT / "app.json")
    _load_json(SOURCE_ROOT / "sitemap.json")

    if project.get("miniprogramRoot") != "miniprogram/":
        raise SystemExit("project.config.json must isolate source under miniprogram/")
    pages = app.get("pages")
    if not isinstance(pages, list) or not pages:
        raise SystemExit("app.json must declare at least one page")

    missing: list[str] = []
    for page in pages:
        if not isinstance(page, str) or not re.fullmatch(r"pages/[a-z-]+/[a-z-]+", page):
            raise SystemExit(f"invalid page path: {page!r}")
        for suffix in (".js", ".json", ".wxml", ".wxss"):
            path = SOURCE_ROOT / f"{page}{suffix}"
            if not path.is_file():
                missing.append(str(path.relative_to(ROOT)))
        _load_json(SOURCE_ROOT / f"{page}.json")
    if missing:
        raise SystemExit("missing Mini Program files:\n" + "\n".join(missing))

    declared_pages = set(pages)
    for tab in app.get("tabBar", {}).get("list", []):
        if tab.get("pagePath") not in declared_pages:
            raise SystemExit(f"tabBar page is not declared: {tab.get('pagePath')}")

    forbidden = re.compile(
        r"(?:appsecret\s*[:=]\s*[^\s\"']+|METRO_DB_PASSWORD\s*[:=]\s*[^\s\"']+|BEGIN (?:RSA|OPENSSH) PRIVATE KEY)",
        re.IGNORECASE,
    )
    for path in CLIENT_ROOT.rglob("*"):
        if path.is_file() and path.name != "README.md" and not path.name.startswith("."):
            text = path.read_text(encoding="utf-8")
            if forbidden.search(text):
                raise SystemExit(f"possible secret material in {path.relative_to(ROOT)}")

    print(f"Mini Program structure valid: {len(pages)} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
