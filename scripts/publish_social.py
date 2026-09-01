#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "da_nina.json"


def fail(message):
    raise RuntimeError(message)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def graph_request(method, graph_version, endpoint, token, params=None):
    params = dict(params or {})
    params["access_token"] = token
    base = f"https://graph.facebook.com/{graph_version}/{endpoint.lstrip('/')}"

    if method == "GET":
        url = base + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET")
    else:
        body = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(base, data=body, method=method)

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if token:
            body = body.replace(token, "[REDACTED]")
        fail(f"Meta API HTTP {exc.code}: {body}")
    except urllib.error.URLError as exc:
        fail(f"Meta API connection error: {exc}")

    data = json.loads(payload or "{}")
    if "error" in data:
        safe = json.dumps(data["error"], ensure_ascii=False)
        if token:
            safe = safe.replace(token, "[REDACTED]")
        fail(f"Meta API error: {safe}")
    return data


def try_graph_get(graph_version, endpoint, token, params=None):
    try:
        return graph_request("GET", graph_version, endpoint, token, params)
    except RuntimeError:
        return None


def verify_public_image(url):
    if not url.startswith("https://"):
        fail("image_url must use HTTPS")

    last_error = None
    for _ in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DaNinaSocialPublisher/1.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                content_type = response.headers.get("Content-Type", "")
                response.read(32)
                if response.status == 200 and content_type.startswith("image/"):
                    return
                last_error = f"HTTP {response.status}, Content-Type={content_type}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(3)
    fail(f"Public image could not be verified: {last_error}")


def build_image_url(request_data):
    if request_data.get("image_url"):
        return request_data["image_url"]

    image_path = request_data.get("image_path")
    if not image_path:
        fail("Request must contain image_path or image_url")

    normalized = Path(image_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        fail("image_path must be a safe relative repository path")
    if not str(normalized).replace("\\", "/").startswith("public/"):
        fail("Automated repository images must be stored under public/")

    local_path = ROOT / normalized
    if not local_path.is_file():
        fail(f"Image file not found in checkout: {image_path}")

    repository = os.environ.get("GITHUB_REPOSITORY")
    commit_sha = os.environ.get("GITHUB_SHA")
    if not repository or not commit_sha:
        fail("GITHUB_REPOSITORY and GITHUB_SHA are required")

    encoded_path = urllib.parse.quote(str(normalized).replace("\\", "/"), safe="/")
    return f"https://raw.githubusercontent.com/{repository}/{commit_sha}/{encoded_path}"


def preflight(config, token):
    version = os.environ.get("META_GRAPH_VERSION", config["graph_version"])
    graph_request("GET", version, config["facebook_page_id"], token, {"fields": "id,name"})
    graph_request(
        "GET",
        version,
        config["instagram_business_account_id"],
        token,
        {"fields": "id,username"},
    )
    return version


def resolve_page_access_token(config, version, system_token):
    page_id = config["facebook_page_id"]

    direct = try_graph_get(
        version,
        page_id,
        system_token,
        {"fields": "id,name,access_token"},
    )
    if direct and direct.get("access_token"):
        return direct["access_token"]

    for edge in ("me/accounts", "me/assigned_pages"):
        data = try_graph_get(
            version,
            edge,
            system_token,
            {"fields": "id,name,access_token,tasks", "limit": "100"},
        )
        if not data:
            continue
        for page in data.get("data", []):
            if str(page.get("id")) == str(page_id) and page.get("access_token"):
                return page["access_token"]

    fail(
        "Facebook Page access token could not be derived from the configured system-user token. "
        "The Page is assigned and readable, but Facebook publishing requires a Page access token."
    )


def publish_instagram(config, version, token, image_url, caption):
    ig_id = config["instagram_business_account_id"]
    created = graph_request(
        "POST",
        version,
        f"{ig_id}/media",
        token,
        {"image_url": image_url, "caption": caption},
    )
    container_id = created.get("id")
    if not container_id:
        fail("Instagram did not return a media container ID")

    for attempt in range(21):
        status = graph_request(
            "GET",
            version,
            container_id,
            token,
            {"fields": "status_code,status"},
        )
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code == "PUBLISHED":
            return {"container_id": container_id, "media_id": container_id, "status": code}
        if code in {"ERROR", "EXPIRED"}:
            fail(f"Instagram container failed: {json.dumps(status, ensure_ascii=False)}")
        if attempt == 20:
            fail(f"Instagram container was not ready after 5 minutes: {json.dumps(status, ensure_ascii=False)}")
        time.sleep(15)

    published = graph_request(
        "POST",
        version,
        f"{ig_id}/media_publish",
        token,
        {"creation_id": container_id},
    )
    media_id = published.get("id")
    if not media_id:
        fail("Instagram media_publish did not return a media ID")
    return {"container_id": container_id, "media_id": media_id, "status": "PUBLISHED"}


def publish_facebook(config, version, system_token, image_url, caption):
    page_id = config["facebook_page_id"]
    page_token = resolve_page_access_token(config, version, system_token)
    published = graph_request(
        "POST",
        version,
        f"{page_id}/photos",
        page_token,
        {"url": image_url, "caption": caption, "published": "true"},
    )
    photo_id = published.get("id") or published.get("post_id")
    if not photo_id:
        fail(f"Facebook did not return a photo/post ID: {json.dumps(published, ensure_ascii=False)}")
    return published


def main():
    if len(sys.argv) != 2:
        print("Usage: publish_social.py <request.json>", file=sys.stderr)
        return 2

    request_path = Path(sys.argv[1])
    if not request_path.is_file():
        fail(f"Request file not found: {request_path}")

    config = load_json(CONFIG_PATH)
    request_data = load_json(request_path)

    if request_data.get("approved_by_user") is not True:
        fail("Safety check failed: approved_by_user must be true")
    if request_data.get("publish_mode") != "live":
        fail("Safety check failed: publish_mode must be 'live'")
    if request_data.get("confirmation") != "PUBLISH_DA_NINA":
        fail("Safety check failed: confirmation must equal PUBLISH_DA_NINA")

    caption = request_data.get("caption", "").strip()
    if not caption:
        fail("caption cannot be empty")

    targets = request_data.get("targets", [])
    if not isinstance(targets, list) or not targets:
        fail("targets must be a non-empty list")
    allowed = {"instagram", "facebook"}
    unknown = set(targets) - allowed
    if unknown:
        fail(f"Unsupported targets: {sorted(unknown)}")

    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        fail("META_ACCESS_TOKEN GitHub Actions secret is not configured")

    image_url = build_image_url(request_data)
    print(f"Using public image URL: {image_url}")
    verify_public_image(image_url)

    version = preflight(config, token)
    print(f"Meta preflight succeeded using Graph API {version}")

    results = {}
    if "instagram" in targets:
        results["instagram"] = publish_instagram(config, version, token, image_url, caption)
        print("Instagram publication succeeded")
        print("INSTAGRAM_RESULT=" + json.dumps(results["instagram"], ensure_ascii=False))

    if "facebook" in targets:
        results["facebook"] = publish_facebook(config, version, token, image_url, caption)
        print("Facebook publication succeeded")
        print("FACEBOOK_RESULT=" + json.dumps(results["facebook"], ensure_ascii=False))

    print("RESULT_JSON=" + json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
