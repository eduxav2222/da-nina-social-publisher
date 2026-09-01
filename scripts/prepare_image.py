#!/usr/bin/env python3
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SOURCE_HOSTS = {"daninas.com", "www.daninas.com"}


def fail(message):
    raise RuntimeError(message)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_public_path(value):
    p = Path(value)
    if p.is_absolute() or ".." in p.parts:
        fail("generated_image_path must be a safe relative path")
    normalized = str(p).replace("\\", "/")
    if not normalized.startswith("public/"):
        fail("generated_image_path must be under public/")
    return p


def download_source(url, destination):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SOURCE_HOSTS:
        fail("source_image_url must be HTTPS and hosted on daninas.com")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DaNinaSocialPublisher/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        content_type = response.headers.get("Content-Type", "")
        if response.status != 200 or not content_type.startswith("image/"):
            fail(f"Source image download failed: HTTP {response.status}, Content-Type={content_type}")
        destination.write_bytes(response.read())


def open_expected_popup(source):
    img = Image.open(source).convert("RGB")
    if img.size != (1024, 1536):
        img.close()
        fail(f"Unexpected popup source dimensions: {img.size}; expected 1024x1536")
    return img


def transform_popup_to_instagram_4x5(source, output):
    with open_expected_popup(source) as img:
        # Exactly matches the user-approved feed preview transformation:
        # crop 24 px from the top, preserve the next 1280 px, then resize to 1080x1350.
        cropped = img.crop((0, 24, 1024, 1304))
        social = cropped.resize((1080, 1350), Image.Resampling.LANCZOS)
        output.parent.mkdir(parents=True, exist_ok=True)
        social.save(output, "JPEG", quality=95, subsampling=0, optimize=True)


def transform_popup_to_story_9x16(source, output):
    with open_expected_popup(source) as img:
        # Story-safe 9:16 full-bleed version. Preserve the complete left-side offer/text
        # and crop only the far-right decorative portion of the approved popup artwork.
        cropped = img.crop((0, 0, 864, 1536))
        story = cropped.resize((1080, 1920), Image.Resampling.LANCZOS)
        output.parent.mkdir(parents=True, exist_ok=True)
        story.save(output, "JPEG", quality=95, subsampling=0, optimize=True)


def main():
    if len(sys.argv) != 2:
        print("Usage: prepare_image.py <request.json>", file=sys.stderr)
        return 2

    request_path = Path(sys.argv[1])
    data = load_json(request_path)

    source_url = data.get("source_image_url")
    generated_path = data.get("generated_image_path")
    transform = data.get("image_transform")

    if not source_url:
        print("No source_image_url supplied; no generated image needed")
        return 0
    if not generated_path:
        fail("generated_image_path is required when source_image_url is used")

    transforms = {
        "popup_1024x1536_to_instagram_4x5_v1": transform_popup_to_instagram_4x5,
        "popup_1024x1536_to_story_9x16_v1": transform_popup_to_story_9x16,
    }
    transform_fn = transforms.get(transform)
    if not transform_fn:
        fail("Unsupported image_transform")

    output = ROOT / safe_public_path(generated_path)
    temp = ROOT / ".tmp_da_nina_source_image"
    try:
        download_source(source_url, temp)
        transform_fn(temp, output)
    finally:
        temp.unlink(missing_ok=True)

    print(f"Generated approved social image: {generated_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
