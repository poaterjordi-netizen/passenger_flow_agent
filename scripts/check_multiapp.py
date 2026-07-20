#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = ROOT / "clients" / "wechat-multiapp"
SOURCE_ROOT = CLIENT_ROOT / "miniprogram"
PACKAGE_NAME = "com.sunxb.metroflow"
DISPLAY_NAME = "客流智控"
VERSION = "0.1.0"
VERSION_CODE = 1
APP_ID = "wxcec9562590faa1a0"


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid JSON: {path.relative_to(ROOT)}: {exc}") from exc


def main() -> int:
    project = _load_json(CLIENT_ROOT / "project.config.json")
    native = _load_json(CLIENT_ROOT / "project.miniapp.json")
    manifest = _load_json(CLIENT_ROOT / "multiapp.manifest.json")
    names = _load_json(CLIENT_ROOT / "i18n" / "base.json")
    app = _load_json(SOURCE_ROOT / "app.json")
    adapter = _load_json(SOURCE_ROOT / "app.miniapp.json")

    if project.get("projectArchitecture") != "multiPlatform":
        raise SystemExit("project.config.json must use multiPlatform architecture")
    if project.get("miniprogramRoot") != "miniprogram/":
        raise SystemExit("project.config.json must isolate source under miniprogram/")
    if native.get("miniVersion") != "v2":
        raise SystemExit("project.miniapp.json must use miniVersion v2")
    if native.get("name") != DISPLAY_NAME:
        raise SystemExit(f"project.miniapp.json name must be {DISPLAY_NAME}")
    if native.get("version") != VERSION or native.get("versionCode") != VERSION_CODE:
        raise SystemExit(f"project.miniapp.json must use version {VERSION} ({VERSION_CODE})")
    for platform in ("mini-android", "mini-ios", "mini-ohos"):
        if not isinstance(native.get(platform), dict) or not native[platform].get("sdkVersion"):
            raise SystemExit(f"missing SDK version for {platform}")
    native_packages = {
        "mini-android": "packageName",
        "mini-ios": "bundleId",
        "mini-ohos": "bundleName",
    }
    for platform, field in native_packages.items():
        if native[platform].get(field) != PACKAGE_NAME:
            raise SystemExit(f"project.miniapp.json {platform}.{field} must be {PACKAGE_NAME}")
    if manifest.get("display_name") != DISPLAY_NAME:
        raise SystemExit("multiapp.manifest.json has the wrong display name")
    if manifest.get("version") != VERSION or manifest.get("version_code") != VERSION_CODE:
        raise SystemExit("multiapp.manifest.json has the wrong version")
    if project.get("appid") != APP_ID or manifest.get("wechat_miniprogram_app_id") != APP_ID:
        raise SystemExit("multi-app files must use the expected Mini Program AppID")
    packages = manifest.get("package_names", {})
    if set(packages) != {"android", "ios", "harmonyos"}:
        raise SystemExit("multiapp.manifest.json must declare all three package names")
    if any(value != PACKAGE_NAME for value in packages.values()):
        raise SystemExit(f"all package names must be {PACKAGE_NAME}")
    if manifest.get("targets") != ["android", "ios", "harmonyos"]:
        raise SystemExit("multiapp.manifest.json must declare all three targets")
    for scope in ("common", "android", "ios"):
        if names.get(scope, {}).get("name") != DISPLAY_NAME:
            raise SystemExit(f"i18n/base.json has the wrong {scope} display name")
    if app.get("window", {}).get("navigationBarTitleText") != DISPLAY_NAME:
        raise SystemExit("app.json has the wrong navigation title")
    if adapter.get("adapteByMiniprogram", {}).get("userName") != "gh_9ea2b88d951a":
        raise SystemExit("app.miniapp.json is not bound to the expected Mini Program")

    request_source = (SOURCE_ROOT / "utils" / "request.js").read_text(encoding="utf-8")
    if "syntheticRequest" not in request_source:
        raise SystemExit("multi-app request adapter must include the offline synthetic transport")
    forbidden_cloud = re.compile(r"\bwx\.cloud\b")
    for path in SOURCE_ROOT.rglob("*.js"):
        if forbidden_cloud.search(path.read_text(encoding="utf-8")):
            raise SystemExit(f"native source must not call wx.cloud: {path.relative_to(ROOT)}")

    pages = app.get("pages")
    if not isinstance(pages, list) or not pages:
        raise SystemExit("app.json must declare pages")
    for page in pages:
        for suffix in (".js", ".json", ".wxml", ".wxss"):
            path = SOURCE_ROOT / f"{page}{suffix}"
            if not path.is_file():
                raise SystemExit(f"missing multi-app page file: {path.relative_to(ROOT)}")

    print(f"Multi-app structure valid: {DISPLAY_NAME}, {PACKAGE_NAME}, 3 targets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
