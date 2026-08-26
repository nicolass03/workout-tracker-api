#!/usr/bin/env python3
"""Upload OpenGym media to the public `opengym-media` Supabase Storage bucket.

Create that bucket as public first. This script intentionally needs a service-role key
only at upload time; the API and iOS app use public, cacheable object URLs afterwards.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import certifi
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


def upload(base_url: str, token: str, bucket: str, source: Path, key_prefix: str) -> None:
    files = sorted(path for path in source.iterdir() if path.is_file())
    if not files:
        raise SystemExit(f"No media files found in {source}")
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    for index, path in enumerate(files, start=1):
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/storage/v1/object/{bucket}/{key_prefix}/{path.name}",
            data=path.read_bytes(),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": media_type,
                "x-upsert": "true",
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )
        try:
            with urllib.request.urlopen(request, context=ssl_context) as response:
                if response.status not in (200, 201):
                    raise SystemExit(f"Upload failed for {path.name}: HTTP {response.status}")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise SystemExit(f"Upload failed for {path.name}: HTTP {error.code} {detail}") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLCertVerificationError):
                raise SystemExit(
                    "TLS certificate verification failed. Update the virtual environment with "
                    "`pip install -r requirements.txt`; if your network intercepts HTTPS, configure "
                    "SSL_CERT_FILE with your organization's CA bundle."
                ) from error
            raise
        print(f"[{index}/{len(files)}] {key_prefix}/{path.name}")


def main() -> None:
    # Match the API's local configuration without overriding shell-provided values.
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-root", type=Path, required=True, help="Directory containing Images/GIFs or img/gif")
    parser.add_argument("--bucket", default="opengym-media", help="Public Supabase Storage bucket name")
    parser.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    parser.add_argument("--service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    args = parser.parse_args()
    if not args.supabase_url or not args.service_role_key:
        raise SystemExit("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY or pass both options.")
    images = args.media_root / "Images"
    gifs = args.media_root / "GIFs"
    if not images.is_dir():
        images = args.media_root / "img"
    if not gifs.is_dir():
        gifs = args.media_root / "gif"
    upload(args.supabase_url, args.service_role_key, args.bucket, images, "opengym/v1/images")
    upload(args.supabase_url, args.service_role_key, args.bucket, gifs, "opengym/v1/gifs")


if __name__ == "__main__":
    main()
