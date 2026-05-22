"""Local credential and session storage.

Credentials are kept in a single JSON file under the user's config directory
with mode 600. Two backends share the same file:

* ``library`` — token from the old asset library REST API.
* ``store``   — Keycloak/session cookies for the new asset store.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

APP_NAME = "godot-asset-store-mcp"


@dataclass
class LibraryCreds:
    username: str | None = None
    token: str | None = None


@dataclass
class StoreCreds:
    # Keycloak/Flask session cookie returned by store.godotengine.org once
    # OIDC has completed. Stored opaquely — we never need to parse it.
    session_cookie: str | None = None
    username: str | None = None


@dataclass
class Credentials:
    library: LibraryCreds = field(default_factory=LibraryCreds)
    store: StoreCreds = field(default_factory=StoreCreds)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Credentials:
        return cls(
            library=LibraryCreds(**(data.get("library") or {})),
            store=StoreCreds(**(data.get("store") or {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"library": asdict(self.library), "store": asdict(self.store)}


def config_path() -> Path:
    override = os.environ.get("GODOT_ASSET_STORE_MCP_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path(user_config_dir(APP_NAME)) / "credentials.json"


def load() -> Credentials:
    path = config_path()
    if not path.exists():
        return Credentials()
    try:
        return Credentials.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return Credentials()


def save(creds: Credentials) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(creds.to_dict(), indent=2), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Best effort — Windows or unusual filesystems.
        pass
    return path


def clear_library() -> None:
    creds = load()
    creds.library = LibraryCreds()
    save(creds)


def clear_store() -> None:
    creds = load()
    creds.store = StoreCreds()
    save(creds)
