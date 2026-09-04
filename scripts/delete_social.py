#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "da_nina.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def graph_request(method, graph_version, endpoint, token, params=None):
    params = dict(params or {})
    params["access_token"] = token
    base = f"https://graph.facebook.com/{graph_version}/{str(endpoint).lstrip('/')}"
    if method == "GET":
        url = base + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET")
    else:
        body = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(base, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if token:
            body = body.replace(token, "[REDACTED]")
        raise RuntimeError(f"HTTP {exc.code}: {body}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"connection error: {exc}")


def try_get(version, endpoint, token):
    try:
        return graph_request("GET", version, endpoint, token, {"fields": "id"})
    except Exception:
        return None


def resolve_page_access_token(config, version, system_token):
    page_id = config["facebook_page_id"]
    try:
        direct = graph_request("GET", version, page_id, system_token, {"fields": "id,name,access_token"})
        if direct.get("access_token"):
            return direct["access_token"]
    except Exception:
        pass
    for edge in ("me/accounts", "me/assigned_pages"):
        try:
            data = graph_request("GET", version, edge, system_token, {"fields": "id,name,access_token,tasks", "limit": "100"})
        except Exception:
            continue
        for page in data.get("data", []):
            if str(page.get("id")) == str(page_id) and page.get("access_token"):
                return page["access_token"]
    raise RuntimeError("Could not derive Facebook Page access token")


def delete_one(version, object_id, token, label):
    before = try_get(version, object_id, token)
    try:
        result = graph_request("DELETE", version, object_id, token)
        print(f"DELETE_RESULT {label} {object_id}=" + json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        # If the object is already inaccessible, treat it as already removed.
        after_error_check = try_get(version, object_id, token)
        if before is None and after_error_check is None:
            print(f"DELETE_ALREADY_GONE {label} {object_id}: {exc}")
            return True
        print(f"DELETE_FAILED {label} {object_id}: {exc}", file=sys.stderr)
        return False

    after = try_get(version, object_id, token)
    if after is None:
        print(f"DELETE_VERIFIED {label} {object_id}: inaccessible after deletion")
        return True
    # Some Meta deletes return success while reads remain briefly available; trust explicit success.
    if result.get("success") is True:
        print(f"DELETE_ACCEPTED {label} {object_id}: Meta returned success=true")
        return True
    print(f"DELETE_UNVERIFIED {label} {object_id}: object still readable", file=sys.stderr)
    return False


def main():
    if len(sys.argv) != 2:
        print("Usage: delete_social.py <request.json>", file=sys.stderr)
        return 2

    request_path = Path(sys.argv[1])
    request = load_json(request_path)
    config = load_json(CONFIG_PATH)

    if request.get("action") != "delete":
        raise RuntimeError("Safety check failed: action must equal delete")
    if request.get("approved_by_user") is not True:
        raise RuntimeError("Safety check failed: approved_by_user must be true")
    if request.get("delete_mode") != "live":
        raise RuntimeError("Safety check failed: delete_mode must equal live")
    if request.get("confirmation") != "DELETE_DA_NINA":
        raise RuntimeError("Safety check failed: confirmation must equal DELETE_DA_NINA")

    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("META_ACCESS_TOKEN is not configured")
    version = os.environ.get("META_GRAPH_VERSION", config.get("graph_version", "v26.0"))
    page_token = resolve_page_access_token(config, version, token)

    objects = request.get("objects", {})
    failures = []

    # Facebook first so the Page feed/story disappear immediately.
    for label in ("facebook_story", "facebook"):
        for object_id in objects.get(label, []):
            if not delete_one(version, object_id, page_token, label):
                failures.append((label, object_id))

    # Instagram published media IDs use the system/user token that created them.
    for label in ("instagram_story", "instagram"):
        for object_id in objects.get(label, []):
            if not delete_one(version, object_id, token, label):
                failures.append((label, object_id))

    if failures:
        print("DELETE_FAILURES=" + json.dumps(failures), file=sys.stderr)
        return 1
    print("DELETE_ALL_CONFIRMED=true")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
