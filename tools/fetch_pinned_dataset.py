#!/usr/bin/env python3
"""Download the exact gated OfficeQA Pro v2 CSV without exposing its token."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DATASET_REPO = "databricks/officeqa-pro-v2"
DATASET_REVISION = "65a2b315780417bc50d7bfe6e5bdb904e63fda65"
DATASET_FILE = "officeqa_pro_v2.csv"
DATASET_SHA256 = "7e253ed35c2ad80f365140beacb4549f21733c9072938bf35cea41879b76182b"
DATASET_URL = (
    f"https://huggingface.co/datasets/{DATASET_REPO}/resolve/"
    f"{DATASET_REVISION}/{DATASET_FILE}?download=true"
)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward the gated-dataset bearer token to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https":
            raise urllib.error.HTTPError(
                newurl, code, "refusing a non-HTTPS dataset redirect", headers, fp
            )
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            source = urllib.parse.urlsplit(req.full_url)
            if source.netloc != target.netloc:
                redirected.remove_header("Authorization")
        return redirected


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(destination: Path, token: str) -> None:
    if not token.strip():
        raise ValueError("HF_TOKEN is required for the gated OfficeQA Pro v2 dataset")

    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        DATASET_URL,
        headers={
            "Authorization": f"Bearer {token.strip()}",
            "User-Agent": "officeqa-pro-v2-exact-release-gate/1.0",
        },
    )
    temporary: Path | None = None
    try:
        opener = urllib.request.build_opener(SafeRedirectHandler())
        with (
            opener.open(request, timeout=120) as response,
            tempfile.NamedTemporaryFile(
                mode="wb", dir=destination.parent, delete=False
            ) as handle,
        ):
            temporary = Path(handle.name)
            while block := response.read(1024 * 1024):
                handle.write(block)
        actual = sha256(temporary)
        if actual != DATASET_SHA256:
            raise ValueError(
                f"downloaded dataset SHA-256 is {actual}, expected {DATASET_SHA256}"
            )
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        fetch(args.destination, os.environ.get("HF_TOKEN", ""))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"FAIL: unable to fetch pinned dataset: {exc}", file=sys.stderr)
        return 1
    print(
        f"Fetched pinned {DATASET_REPO}@{DATASET_REVISION}/{DATASET_FILE} "
        f"to {args.destination}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
