"""Streaming asset downloader shared by both backends."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

DEFAULT_CHUNK = 64 * 1024


def _filename_from_url(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name or "download.bin"
    # GitHub-style URLs end in /archive/master.zip — keep them as-is.
    return name


def _filename_from_headers(headers: httpx.Headers) -> str | None:
    cd = headers.get("content-disposition")
    if not cd:
        return None
    # Prefer RFC 5987 filename*=
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", cd, re.IGNORECASE)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.IGNORECASE)
    if m:
        return unquote(m.group(1).strip())
    return None


async def stream_download(
    url: str,
    dest_dir: Path,
    *,
    client: httpx.AsyncClient | None = None,
    filename: str | None = None,
    expected_sha256: str | None = None,
) -> dict:
    """Stream ``url`` to ``dest_dir`` and return metadata.

    If ``expected_sha256`` is provided and non-empty, the downloaded file is
    deleted and an exception is raised on mismatch.
    """
    dest_dir = Path(dest_dir).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(follow_redirects=True, timeout=60.0)

    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            name = (
                filename
                or _filename_from_headers(response.headers)
                or _filename_from_url(str(response.url))
            )
            target = dest_dir / name
            sha = hashlib.sha256()
            total = 0
            with open(target, "wb") as fh:
                async for chunk in response.aiter_bytes(DEFAULT_CHUNK):
                    fh.write(chunk)
                    sha.update(chunk)
                    total += len(chunk)
    finally:
        if owns_client:
            await client.aclose()

    digest = sha.hexdigest()
    if expected_sha256 and expected_sha256.lower() != digest:
        try:
            os.remove(target)
        except OSError:
            pass
        raise ValueError(
            f"sha256 mismatch for {url}: expected {expected_sha256}, got {digest}"
        )

    return {
        "path": str(target),
        "size": total,
        "sha256": digest,
        "source_url": url,
    }
