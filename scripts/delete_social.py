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


def try_get(version, endpoint, token, fields="id"):
    try:
        return graph_request("GET", version, endpoint, token, {"fields": fields})
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
        after_error_check = try_get(version, object_id, token)
        if before is None and after_error_check is None:
            print(f"DELETE_ALREADY_INACCESSIBLE {label} {object_id}: {exc}")
            return True
        print(f"DELETE_FAILED {label} {object_id}: {exc}", file=sys.stderr)
        return False

    after = try_get(version, object_id, token)
    if after is None:
        print(f"DELETE_VERIFIED {label} {object_id}: inaccessible after deletion")
        return True
    if result.get("success") is True:
        print(f"DELETE_ACCEPTED {label} {object_id}: Meta returned success=true")
        return True
    print(f"DELETE_UNVERIFIED {label} {object_id}: object still readable", file=sys.stderr)
    return False


def find_active_facebook_story(config, version, page_token, target_ids):
    page_id = config["facebook_page_id"]
    try:
        data = graph_request(
            "GET", version, f"{page_id}/stories", page_token,
            {"fields": "status,creation_time,media_id,post_id,url", "limit": "50"},
        )
    except Exception as exc:
        print(f"FACEBOOK_STORY_VERIFY_ERROR={exc}", file=sys.stderr)
        return None
    targets = {str(x) for x in target_ids}
    matches = []
    for story in data.get("data", []):
        if str(story.get("post_id")) in targets or str(story.get("media_id")) in targets or str(story.get("id")) in targets:
            matches.append(story)
    print("FACEBOOK_STORY_ACTIVE_MATCHES=" + json.dumps(matches, ensure_ascii=False))
    return matches


def find_instagram_media(config, version, token, target_feed_ids, target_story_ids):
    ig_id = config["instagram_business_account_id"]
    report = {"feed_matches": None, "story_matches": None}
    try:
        feed = graph_request(
            "GET", version, f"{ig_id}/media", token,
            {"fields": "id,media_type,permalink,timestamp", "limit": "50"},
        )
        targets = {str(x) for x in target_feed_ids}
        report["feed_matches"] = [m for m in feed.get("data", []) if str(m.get("id")) in targets]
    except Exception as exc:
        print(f"INSTAGRAM_FEED_VERIFY_ERROR={exc}", file=sys.stderr)
    try:
        stories = graph_request(
            "GET", version, f"{ig_id}/stories", token,
            {"fields": "id,media_type,permalink,timestamp", "limit": "50"},
        )
        targets = {str(x) for x in target_story_ids}
        report["story_matches"] = [m for m in stories.get("data", []) if str(m.get("id")) in targets]
    except Exception as exc:
        print(f"INSTAGRAM_STORY_VERIFY_ERROR={exc}", file=sys.stderr)
    print("INSTAGRAM_ACTIVE_REPORT=" + json.dumps(report, ensure_ascii=False))
    return report


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

    for label in ("facebook_story", "facebook"):
        for object_id in objects.get(label, []):
            if not delete_one(version, object_id, page_token, label):
                failures.append((label, object_id))

    # Instagram published Business media cannot normally be deleted through the Graph API,
    # but attempt the requested IDs once and then verify whether they remain active.
    for label in ("instagram_story", "instagram"):
        for object_id in objects.get(label, []):
            if not delete_one(version, object_id, token, label):
                failures.append((label, object_id))

    fb_story_matches = find_active_facebook_story(config, version, page_token, objects.get("facebook_story", []))
    ig_report = find_instagram_media(
        config, version, token,
        objects.get("instagram", []), objects.get("instagram_story", []),
    )

    if fb_story_matches == []:
        print("FACEBOOK_STORY_REMOVAL_CONFIRMED=true")
        failures = [f for f in failures if f[0] != "facebook_story"]

    if ig_report.get("feed_matches") == []:
        failures = [f for f in failures if f[0] != "instagram"]
        print("INSTAGRAM_FEED_REMOVAL_CONFIRMED=true")
    if ig_report.get("story_matches") == []:
        failures = [f for f in failures if f[0] != "instagram_story"]
        print("INSTAGRAM_STORY_REMOVAL_CONFIRMED=true")

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
