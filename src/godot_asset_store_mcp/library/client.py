"""Async client for the official Godot asset library REST API.

API reference:
    https://github.com/godotengine/godot-asset-library/blob/master/API.md
"""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_BASE_URL = "https://godotengine.org/asset-library/api"
DEFAULT_TIMEOUT = 30.0


class AssetLibraryError(RuntimeError):
    """Raised when the asset library returns an error payload."""

    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        super().__init__(f"asset library error {status}: {payload!r}")


class AssetLibraryClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> AssetLibraryClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _request(
        self, method: str, path: str, *, params: dict | None = None, json: dict | None = None
    ) -> Any:
        url = f"{self.base_url}{path}"
        response = await self._http().request(method, url, params=params, json=json)
        try:
            data = response.json()
        except ValueError:
            data = response.text
        if response.status_code >= 400:
            raise AssetLibraryError(response.status_code, data)
        # The API uses {"error": "..."} on logical failures with a 200 status too.
        if isinstance(data, dict) and data.get("error"):
            raise AssetLibraryError(response.status_code, data)
        return data

    # ---------------------------------------------------------------- auth

    async def register(self, username: str, password: str, email: str) -> dict:
        return await self._request(
            "POST", "/register", json={"username": username, "password": password, "email": email}
        )

    async def login(self, username: str, password: str) -> dict:
        return await self._request(
            "POST", "/login", json={"username": username, "password": password}
        )

    async def logout(self, token: str) -> dict:
        return await self._request("POST", "/logout", json={"token": token})

    async def change_password(self, token: str, old_password: str, new_password: str) -> dict:
        return await self._request(
            "POST",
            "/change_password",
            json={"token": token, "old_password": old_password, "new_password": new_password},
        )

    # ---------------------------------------------------------------- reads

    async def configure(
        self,
        *,
        asset_type: str | None = None,
        session: bool = False,
    ) -> dict:
        params: dict[str, Any] = {}
        if asset_type:
            params["type"] = asset_type
        if session:
            params["session"] = "1"
        return await self._request("GET", "/configure", params=params or None)

    async def search_assets(
        self,
        *,
        asset_type: str | None = None,
        category: int | str | None = None,
        support: str | list[str] | None = None,
        filter: str | None = None,
        user: str | None = None,
        cost: str | None = None,
        godot_version: str | None = None,
        max_results: int | None = None,
        page: int | None = None,
        offset: int | None = None,
        sort: str | None = None,
        reverse: bool = False,
    ) -> dict:
        params: dict[str, Any] = {}
        if asset_type:
            params["type"] = asset_type
        if category is not None:
            params["category"] = category
        if support:
            params["support"] = "+".join(support) if isinstance(support, list) else support
        if filter:
            params["filter"] = filter
        if user:
            params["user"] = user
        if cost:
            params["cost"] = cost
        if godot_version:
            params["godot_version"] = godot_version
        if max_results is not None:
            params["max_results"] = max_results
        if page is not None:
            params["page"] = page
        if offset is not None:
            params["offset"] = offset
        if sort:
            params["sort"] = sort
        if reverse:
            params["reverse"] = ""
        return await self._request("GET", "/asset", params=params or None)

    async def get_asset(self, asset_id: int | str) -> dict:
        return await self._request("GET", f"/asset/{asset_id}")

    # ----------------------------------------------------------- moderation

    async def delete_asset(self, asset_id: int | str, token: str) -> dict:
        return await self._request("POST", f"/asset/{asset_id}/delete", json={"token": token})

    async def undelete_asset(self, asset_id: int | str, token: str) -> dict:
        return await self._request("POST", f"/asset/{asset_id}/undelete", json={"token": token})

    async def set_support_level(self, asset_id: int | str, support_level: str, token: str) -> dict:
        return await self._request(
            "POST",
            f"/asset/{asset_id}/support_level",
            json={"support_level": support_level, "token": token},
        )

    # ---------------------------------------------------------------- edits

    async def submit_edit(
        self,
        *,
        token: str,
        asset_id: int | str | None = None,
        edit_id: int | str | None = None,
        fields: dict,
    ) -> dict:
        """Create a new edit (POST /asset), edit an existing asset (POST /asset/{id}),
        or update a pending edit (POST /asset/edit/{edit_id})."""
        if edit_id is not None:
            path = f"/asset/edit/{edit_id}"
        elif asset_id is not None:
            path = f"/asset/{asset_id}"
        else:
            path = "/asset"
        payload = {"token": token, **fields}
        return await self._request("POST", path, json=payload)

    async def get_edit(self, edit_id: int | str) -> dict:
        return await self._request("GET", f"/asset/edit/{edit_id}")

    async def request_review(self, edit_id: int | str, token: str) -> dict:
        return await self._request(
            "POST", f"/asset/edit/{edit_id}/review", json={"token": token}
        )
