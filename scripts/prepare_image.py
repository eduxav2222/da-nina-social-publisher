#!/usr/bin/env python3
import base64
import io
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


def safe_embedded_part_path(value):
    p = Path(value)
    if p.is_absolute() or ".." in p.parts:
        fail("embedded_base64_parts paths must be safe relative paths")
    normalized = str(p).replace("\\", "/")
    if not normalized.startswith("assets/embedded/"):
        fail("embedded_base64_parts must be under assets/embedded/")
    return p


def download_source(url, destination):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SOURCE_HOSTS:
        fail("source_image_url must be HTTPS and hosted on daninas.com")

    req = urllib.request.Request(url, headers={"User-Agent": "DaNinaSocialPublisher/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        content_type = response.headers.get("Content-Type", "")
        if response.status != 200 or not content_type.startswith("image/"):
            fail(f"Source image download failed: HTTP {response.status}, Content-Type={content_type}")
        destination.write_bytes(response.read())


def open_expected_popup(source):
    img = Image.open(source).convert("RGB")
    if img.size != (1024, 1536):
        actual = img.size
        img.close()
        fail(f"Unexpected popup source dimensions: {actual}; expected 1024x1536")
    return img


def save_jpeg(img, output, size):
    rendered = img.resize(size, Image.Resampling.LANCZOS)
    output.parent.mkdir(parents=True, exist_ok=True)
    rendered.save(output, "JPEG", quality=95, subsampling=0, optimize=True)


def transform_popup_to_instagram_4x5(source, output):
    with open_expected_popup(source) as img:
        cropped = img.crop((0, 24, 1024, 1304))
        save_jpeg(cropped, output, (1080, 1350))


def transform_popup_to_facebook_1x1(source, output):
    with open_expected_popup(source) as img:
        cropped = img.crop((0, 0, 1024, 1024))
        save_jpeg(cropped, output, (1080, 1080))


def transform_popup_to_story_9x16(source, output):
    with open_expected_popup(source) as img:
        cropped = img.crop((0, 0, 864, 1536))
        save_jpeg(cropped, output, (1080, 1920))


TRANSFORMS = {
    "popup_1024x1536_to_instagram_4x5_v1": transform_popup_to_instagram_4x5,
    "popup_1024x1536_to_facebook_1x1_v1": transform_popup_to_facebook_1x1,
    "popup_1024x1536_to_story_9x16_v1": transform_popup_to_story_9x16,
}


def materialize_embedded_base64(encoded, output, expected_size=None, normalize_jpeg=False):
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        fail(f"Invalid embedded base64: {exc}")

    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.verify()
        with Image.open(io.BytesIO(raw)) as img:
            actual_size = list(img.size)
    except Exception as exc:
        fail(f"Embedded base64 is not a valid image: {exc}")

    if expected_size is not None and actual_size != list(expected_size):
        fail(f"Embedded image dimensions {actual_size} do not match expected {list(expected_size)}")

    output.parent.mkdir(parents=True, exist_ok=True)
    if normalize_jpeg:
        try:
            with Image.open(io.BytesIO(raw)) as img:
                normalized = img.convert("RGB")
                normalized.save(
                    output,
                    "JPEG",
                    quality=95,
                    subsampling=0,
                    optimize=True,
                    progressive=False,
                )
        except Exception as exc:
            fail(f"Could not normalize approved JPEG: {exc}")
    else:
        output.write_bytes(raw)


def read_embedded_parts(parts):
    if not isinstance(parts, list) or not parts:
        fail("embedded_base64_parts must be a non-empty list")
    chunks = []
    for value in parts:
        part_path = ROOT / safe_embedded_part_path(value)
        chunks.append(part_path.read_text(encoding="ascii").strip())
    return "".join(chunks)


def generate_one(spec, default_source_url, index):
    generated_path = spec.get("generated_image_path")
    if not generated_path:
        fail(f"generated_images[{index}] is missing generated_image_path")

    output = ROOT / safe_public_path(generated_path)
    embedded = spec.get("embedded_base64")
    parts = spec.get("embedded_base64_parts")
    if embedded or parts:
        encoded = embedded if embedded else read_embedded_parts(parts)
        materialize_embedded_base64(
            encoded,
            output,
            spec.get("expected_size"),
            bool(spec.get("normalize_jpeg", False)),
        )
        action = "Normalized" if spec.get("normalize_jpeg") else "Materialized"
        print(f"{action} approved embedded social image: {generated_path}")
        return

    source_url = spec.get("source_image_url") or default_source_url
    transform = spec.get("image_transform")
    if not source_url:
        fail(f"generated_images[{index}] is missing source_image_url or embedded image data")

    transform_fn = TRANSFORMS.get(transform)
    if not transform_fn:
        fail(f"Unsupported image_transform for generated_images[{index}]: {transform}")

    temp = ROOT / f".tmp_da_nina_source_image_{index}"
    try:
        download_source(source_url, temp)
        transform_fn(temp, output)
    finally:
        temp.unlink(missing_ok=True)

    print(f"Generated approved social image: {generated_path}")


def main():
    if len(sys.argv) != 2:
        print("Usage: prepare_image.py <request.json>", file=sys.stderr)
        return 2

    request_path = Path(sys.argv[1])
    data = load_json(request_path)

    generated_images = data.get("generated_images")
    if generated_images is not None:
        if not isinstance(generated_images, list) or not generated_images:
            fail("generated_images must be a non-empty list when supplied")
        for index, spec in enumerate(generated_images):
            if not isinstance(spec, dict):
                fail(f"generated_images[{index}] must be an object")
            generate_one(spec, data.get("source_image_url"), index)
        return 0

    source_url = data.get("source_image_url")
    generated_path = data.get("generated_image_path")
    transform = data.get("image_transform")

    if not source_url:
        print("No source_image_url supplied; no generated image needed")
        return 0
    if not generated_path:
        fail("generated_image_path is required when source_image_url is used")

    generate_one({"source_image_url": source_url, "generated_image_path": generated_path, "image_transform": transform}, None, 0)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
