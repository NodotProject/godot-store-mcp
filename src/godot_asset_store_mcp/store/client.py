"""Client for the new Godot Asset Store (store.godotengine.org).

The new store does not (yet) publish a JSON API, so this module talks to the
HTMX-driven HTML pages and scrapes structured data out of them. Endpoints and
selectors may change without notice while the store is in beta.

Authenticated state is carried by a single ``session`` cookie issued by the
Flask app once OIDC has completed. Use ``store/login.py`` to obtain one.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

DEFAULT_BASE_URL = "https://store.godotengine.org"
DEFAULT_TIMEOUT = 30.0
USER_AGENT = "godot-asset-store-mcp/0.1 (+https://github.com/jakecattrall/godot-asset-store-mcp)"


class StoreError(RuntimeError):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"store error {status}: {message}")


class AssetStoreClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session_cookie: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session_cookie = session_cookie
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> AssetStoreClient:
        self._ensure_client()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"User-Agent": USER_AGENT, "Accept": "text/html, */*"}
            cookies = httpx.Cookies()
            if self._session_cookie:
                # Bind the cookie to the store host so that server-issued
                # Set-Cookie headers (Flask rotates `session` on every response)
                # REPLACE our seed rather than coexisting as a second entry —
                # otherwise the server reads the stale value and rejects writes.
                cookies.set(
                    "session",
                    self._session_cookie,
                    domain=self._host(),
                    path="/",
                )
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers=headers,
                cookies=cookies,
            )
        return self._client

    def set_session_cookie(self, cookie: str | None) -> None:
        self._session_cookie = cookie
        if self._client is not None:
            if cookie:
                self._client.cookies.set("session", cookie, domain=self._host())
            else:
                self._client.cookies.delete("session", domain=self._host())

    def _host(self) -> str:
        return urlparse(self.base_url).hostname or ""

    async def _get_html(self, path: str, params: dict | None = None) -> tuple[BeautifulSoup, str]:
        client = self._ensure_client()
        url = path if path.startswith("http") else urljoin(self.base_url + "/", path.lstrip("/"))
        response = await client.get(url, params=params)
        if response.status_code >= 400:
            raise StoreError(response.status_code, response.text[:200])
        return BeautifulSoup(response.text, "lxml"), str(response.url)

    # ---------------------------------------------------------------- parse

    @staticmethod
    def _parse_asset_card(card: Any) -> dict[str, Any]:
        asset_link = card.find("a", href=lambda h: h and h.startswith("/asset/"))
        href = asset_link["href"] if asset_link else None
        publisher = slug = None
        if href:
            parts = [p for p in href.split("/") if p]
            if len(parts) >= 3:
                publisher = parts[1]
                slug = parts[2]
        title_el = card.find(class_="name") or card.find(class_="title") or card.find("h3")
        title = None
        if title_el:
            inner_a = title_el.find("a")
            title = (inner_a or title_el).get_text(strip=True)
        publisher_el = card.find("a", href=lambda h: h and h.startswith("/publisher/"))
        img_el = card.find("img", class_="thumbnail") or card.find("img")
        rating_el = card.find(class_="rating")
        return {
            "publisher_slug": publisher,
            "asset_slug": slug,
            "url": href,
            "title": title,
            "publisher": publisher_el.get_text(strip=True) if publisher_el else None,
            "thumbnail": img_el.get("src") if img_el else None,
            "rating": rating_el.get_text(strip=True) if rating_el else None,
        }

    # ---------------------------------------------------------------- reads

    async def search(
        self,
        query: str | None = None,
        scroll: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if query is not None:
            params["query"] = query
        if scroll:
            params["scroll"] = scroll
        soup, final_url = await self._get_html("/search/", params=params or None)
        cards = soup.select(".item")
        results = [
            self._parse_asset_card(c)
            for c in cards
            if c.find("a", href=lambda h: h and h.startswith("/asset/"))
        ]
        # Deduplicate by URL — search page sometimes wraps the same card twice.
        seen: set[str] = set()
        unique = []
        for r in results:
            key = r.get("url") or ""
            if key and key not in seen:
                seen.add(key)
                unique.append(r)
        next_scroll = None
        scroll_el = soup.find(attrs={"hx-get": True})
        if scroll_el:
            href = scroll_el.get("hx-get", "")
            if "scroll=" in href:
                next_scroll = href.split("scroll=", 1)[1].split("&", 1)[0]
        return {
            "query": query,
            "results": unique,
            "count": len(unique),
            "next_scroll": next_scroll,
            "source_url": final_url,
        }

    async def get_asset(self, publisher: str, slug: str) -> dict[str, Any]:
        soup, final_url = await self._get_html(f"/asset/{publisher}/{slug}/")
        title_el = soup.select_one("h1")
        publisher_el = soup.select_one(".publisher a") or soup.select_one(".publisher")
        desc_el = soup.find("meta", attrs={"property": "og:description"})
        thumb_el = soup.find("meta", attrs={"property": "og:image"})

        tags = [t.get_text(strip=True) for t in soup.select(".tags a") if t.get_text(strip=True)]

        # External links: license, source, etc.
        info_panel = soup.select_one(".info") or soup
        external_links = []
        for a in info_panel.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http"):
                external_links.append({"text": a.get_text(strip=True), "href": href})

        # Download options carry data-* attributes.
        downloads: list[dict[str, Any]] = []
        for opt in soup.select("#version-dropdown option"):
            data = opt.attrs
            downloads.append(
                {
                    "id": data.get("data-id"),
                    "version": data.get("data-version"),
                    "size": data.get("data-size"),
                    "notes": data.get("data-notes"),
                    "min_godot_version": data.get("data-min-display-version"),
                    "max_godot_version": data.get("data-max-display-version"),
                    "direct_url": data.get("data-url"),
                    "selected": opt.has_attr("selected"),
                }
            )

        # Download button template tells us how to construct the in-store
        # download URL once we know the id.
        download_template = None
        btn = soup.select_one("#download-button")
        if btn:
            download_template = btn.get("data-download-url-template") or btn.get("href")

        return {
            "publisher_slug": publisher,
            "asset_slug": slug,
            "url": final_url,
            "title": title_el.get_text(strip=True) if title_el else None,
            "publisher": publisher_el.get_text(strip=True) if publisher_el else None,
            "description": desc_el.get("content") if desc_el else None,
            "thumbnail": thumb_el.get("content") if thumb_el else None,
            "tags": tags,
            "external_links": external_links,
            "downloads": downloads,
            "download_url_template": download_template,
        }

    async def list_publisher_assets(self, publisher: str) -> dict[str, Any]:
        soup, final_url = await self._get_html(f"/publisher/{publisher}/")
        cards = soup.select("a[href^='/asset/']")
        seen: set[str] = set()
        results = []
        for a in cards:
            href = a.get("href", "")
            if href in seen:
                continue
            seen.add(href)
            # Wrap the anchor to reuse the card parser.
            results.append(self._parse_asset_card(a.parent or a))
        return {"publisher": publisher, "results": results, "source_url": final_url}

    # ------------------------------------------------------- write actions

    async def create_asset(
        self,
        *,
        name: str,
        url_slug: str,
        publisher_id: str | int | None = None,
    ) -> dict[str, Any]:
        """Create a new asset stub on the new store.

        Posts the ``/asset/new/`` HTMX form: ``publisher_id`` + ``name`` +
        ``url_slug`` + ``agree_terms`` plus the CSRF token scraped from a fresh
        GET of the same page. The store creates a draft listing and 302s to
        its detail/edit page — description, screenshots, versions, and download
        archives must still be filled in via the web UI.

        ``publisher_id`` defaults to the only existing publisher on the
        account, or raises if there's more than one (the caller must pick).
        """
        client = self._ensure_client()
        form_url = urljoin(self.base_url + "/", "asset/new/")
        page = await client.get(form_url)
        if page.status_code >= 400:
            raise StoreError(page.status_code, page.text[:200])

        soup = BeautifulSoup(page.text, "lxml")
        form = next(
            (
                f
                for f in soup.find_all("form")
                if f.find("input", {"name": "csrf_token"})
                and f.find(["select", "input"], {"name": "publisher_id"})
            ),
            None,
        )
        if form is None:
            raise StoreError(
                500,
                "Could not locate the /asset/new/ form (page layout may have changed).",
            )
        csrf_input = form.find("input", {"name": "csrf_token"})
        csrf_token = csrf_input.get("value") if csrf_input else None
        if not csrf_token:
            raise StoreError(500, "No CSRF token on /asset/new/ form.")

        publisher_select = form.find("select", {"name": "publisher_id"})
        publisher_options: list[dict[str, Any]] = []
        if publisher_select is not None:
            for opt in publisher_select.find_all("option"):
                publisher_options.append(
                    {
                        "value": opt.get("value"),
                        "label": opt.get_text(strip=True),
                    }
                )

        if publisher_id is None:
            existing = [
                opt for opt in publisher_options if (opt["value"] or "").upper() != "NEW"
            ]
            if len(existing) == 1:
                publisher_id = existing[0]["value"]
            else:
                raise StoreError(
                    400,
                    "publisher_id is required: multiple publishers (or none) "
                    f"available — {publisher_options!r}",
                )

        data: dict[str, str] = {
            "csrf_token": csrf_token,
            "publisher_id": str(publisher_id),
            "name": name,
            "url_slug": url_slug,
        }
        # The terms checkbox / new-publisher fields only render when the user
        # picks "Create a new publisher" (publisher_id=NEW). For existing
        # publishers a real browser sends none of these — mirror that.
        if str(publisher_id).upper() == "NEW":
            data["agree_terms"] = "on"

        # Send as multipart since the form declares enctype=multipart/form-data.
        # httpx builds a valid multipart body when given `files={}` alongside
        # `data=`. follow_redirects=False so we can inspect the redirect target
        # — the store signals success either with a 30x Location header or, for
        # HTMX-driven submits, a 200 carrying an `HX-Redirect` header.
        response = await client.post(
            form_url,
            data=data,
            files={},
            headers={"Referer": form_url},
            follow_redirects=False,
        )

        redirect_to = (
            response.headers.get("hx-redirect")
            or response.headers.get("location")
            if response.status_code in (200, 301, 302, 303)
            else None
        )
        if redirect_to and "/asset/" in redirect_to:
            if redirect_to.startswith("/"):
                redirect_to = urljoin(self.base_url + "/", redirect_to.lstrip("/"))
            parts = [p for p in urlparse(redirect_to).path.split("/") if p]
            publisher_slug = parts[1] if len(parts) >= 3 and parts[0] == "asset" else None
            asset_slug = parts[2] if len(parts) >= 3 and parts[0] == "asset" else None
            return {
                "created": True,
                "url": redirect_to,
                "publisher_slug": publisher_slug,
                "asset_slug": asset_slug,
                "status": response.status_code,
            }

        # Validation failure: store re-renders the form with inline errors.
        soup = BeautifulSoup(response.text, "lxml")
        errors: list[str] = []
        for el in soup.select(".error, .errors li, .alert-error, .invalid-feedback"):
            text = el.get_text(" ", strip=True)
            if text:
                errors.append(text)
        raise StoreError(
            response.status_code,
            "Asset creation rejected: " + ("; ".join(errors) or response.text[:200]),
        )

    async def add_to_library(self, publisher: str, slug: str) -> dict[str, Any]:
        client = self._ensure_client()
        url = urljoin(self.base_url + "/", f"library/{publisher}/{slug}/")
        response = await client.put(url)
        if response.status_code >= 400:
            raise StoreError(response.status_code, response.text[:200])
        return {
            "added": True,
            "status": response.status_code,
            "response_fragment": response.text[:400],
        }

    async def remove_from_library(self, publisher: str, slug: str) -> dict[str, Any]:
        client = self._ensure_client()
        url = urljoin(self.base_url + "/", f"library/{publisher}/{slug}/")
        response = await client.delete(url)
        if response.status_code >= 400:
            raise StoreError(response.status_code, response.text[:200])
        return {"removed": True, "status": response.status_code}

    # ---------------------------------------------------- manage-page helpers

    async def _fetch_manage(self, publisher: str, slug: str) -> BeautifulSoup:
        """GET the /manage/ page and return its parsed soup.

        Raises ``StoreError`` if not authenticated or the asset is unmanageable
        by the current session.
        """
        soup, final_url = await self._get_html(f"/asset/{publisher}/{slug}/manage/")
        if "/manage/" not in final_url:
            # Server redirected away from the manage page → not authorized.
            raise StoreError(403, f"Not authorized to manage {publisher}/{slug}.")
        if not soup.find("input", {"name": "csrf_token"}):
            raise StoreError(401, "No CSRF token on manage page; session may be expired.")
        return soup

    @staticmethod
    def _csrf_token(soup: BeautifulSoup) -> str:
        token = soup.find("input", {"name": "csrf_token"})
        if not token or not token.get("value"):
            raise StoreError(500, "csrf_token input missing on manage page.")
        return token["value"]

    @staticmethod
    def _form_errors(html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        errors: list[str] = []
        for el in soup.select(".error, .errors li, .alert-error, .invalid-feedback, .request-error"):
            text = el.get_text(" ", strip=True)
            if text:
                errors.append(text)
        return errors

    async def _post_manage_form(
        self,
        endpoint: str,
        data: dict[str, str],
        files: dict[str, Any] | None = None,
        *,
        publisher: str,
        slug: str,
    ) -> dict[str, Any]:
        client = self._ensure_client()
        url = urljoin(self.base_url + "/", endpoint.lstrip("/"))
        referer = urljoin(self.base_url + "/", f"asset/{publisher}/{slug}/manage/")
        # All HTMX-driven manage forms expect a multipart body.
        files = files or {}
        response = await client.post(
            url,
            data=data,
            files=files,
            headers={"Referer": referer, "HX-Request": "true"},
            follow_redirects=False,
        )
        ok = 200 <= response.status_code < 300
        if not ok:
            errors = self._form_errors(response.text)
            raise StoreError(
                response.status_code,
                "; ".join(errors) or response.text[:300] or "no response body",
            )
        # The HTML fragment returned IS the new tab content — surface inline
        # errors even on 200 OK so callers don't have to re-fetch to detect them.
        errors = self._form_errors(response.text)
        return {
            "ok": True,
            "status": response.status_code,
            "endpoint": endpoint,
            "errors": errors,
        }

    # ---------------------------------------------------- tag autocomplete

    async def suggest_tags(self, query: str) -> list[dict[str, str]]:
        client = self._ensure_client()
        url = urljoin(self.base_url + "/", "possible-tags/")
        response = await client.get(url, params={"q": query})
        if response.status_code >= 400:
            raise StoreError(response.status_code, response.text[:200])
        return list(response.json())

    async def _resolve_tag_slug(self, tag: str) -> str:
        """Resolve a free-text tag into the store's canonical slug.

        Tries the autocomplete endpoint and picks an exact match on either the
        slug or the display name (case-insensitive). Falls back to the input.
        """
        suggestions = await self.suggest_tags(tag)
        lowered = tag.lower()
        for s in suggestions:
            if s.get("slug", "").lower() == lowered or s.get("display_name", "").lower() == lowered:
                return s["slug"]
        # No exact match — return the user's input verbatim so the server can
        # decide whether to accept (it does accept arbitrary slugs).
        return tag

    # ---------------------------------------------------- settings tab

    @staticmethod
    def _scrape_settings(soup: BeautifulSoup) -> dict[str, Any]:
        """Extract the current values of the Settings form so callers can patch
        a subset of fields without overwriting the rest with empty strings."""
        settings_form = next(
            (
                f
                for f in soup.find_all("form")
                if f.get("hx-post", "").endswith("/settings/update/")
            ),
            None,
        )
        if settings_form is None:
            raise StoreError(500, "Settings form not found on manage page.")
        out: dict[str, Any] = {}
        for inp in settings_form.find_all(["input", "textarea", "select"]):
            name = inp.get("name")
            if not name or name == "csrf_token":
                continue
            if inp.name == "textarea":
                text = inp.get_text() or ""
                # HTML5 textarea parsing strips a single leading LF in the
                # element's content — BeautifulSoup doesn't, so each round-trip
                # would otherwise prepend another newline. Mirror the spec.
                if text.startswith("\n"):
                    text = text[1:]
                out[name] = text
            elif inp.name == "select":
                selected = inp.find("option", selected=True)
                out[name] = selected.get("value", "") if selected else ""
            elif inp.get("type") == "checkbox":
                out[name] = "y" if inp.has_attr("checked") else ""
            else:
                out[name] = inp.get("value", "") or ""
        existing_tag_slugs: list[str] = []
        for tag_input in settings_form.select(".tag-data"):
            v = tag_input.get("value")
            if v:
                existing_tag_slugs.append(v)
        out["_existing_tags"] = existing_tag_slugs
        return out

    async def edit_settings(
        self,
        publisher: str,
        slug: str,
        *,
        name: str | None = None,
        description: str | None = None,
        body: str | None = None,
        tags: list[str] | None = None,
        type_: str | None = None,
        license_predefined: str | None = None,
        license_type: str | None = None,
        license_url: str | None = None,
        source: str | None = None,
        uses_ai: bool | None = None,
        uses_ai_reason: str | None = None,
    ) -> dict[str, Any]:
        """Patch the Settings tab. Only fields explicitly passed are changed —
        the rest are read from the current manage page and re-submitted so the
        server-side validator sees a full form."""
        soup = await self._fetch_manage(publisher, slug)
        csrf = self._csrf_token(soup)
        current = self._scrape_settings(soup)

        # Type translation: accept "addon"/"project" as friendlier aliases.
        if type_ is not None:
            type_value = {"addon": "0", "project": "1"}.get(type_, str(type_))
        else:
            type_value = current.get("type", "0")

        data: dict[str, str] = {
            "csrf_token": csrf,
            "name": name if name is not None else current.get("name", ""),
            "description": description if description is not None else current.get("description", ""),
            "body_raw": body if body is not None else current.get("body_raw", ""),
            "type": type_value,
            "license_predefined": (
                license_predefined
                if license_predefined is not None
                else current.get("license_predefined", "")
            ),
            "license_type": (
                license_type if license_type is not None else current.get("license_type", "")
            ),
            "license_url": (
                license_url if license_url is not None else current.get("license_url", "")
            ),
            "source": source if source is not None else current.get("source", ""),
        }
        if uses_ai is not None:
            if uses_ai:
                data["uses_ai"] = "y"
        elif current.get("uses_ai") == "y":
            data["uses_ai"] = "y"
        data["uses_ai_reason"] = (
            uses_ai_reason if uses_ai_reason is not None else current.get("uses_ai_reason", "")
        )

        # Tags: if caller passed `tags`, REPLACE the current set; otherwise
        # preserve whatever was already on the asset.
        slugs: list[str]
        if tags is not None:
            slugs = []
            for raw in tags:
                resolved = await self._resolve_tag_slug(raw)
                if resolved and resolved not in slugs:
                    slugs.append(resolved)
        else:
            slugs = current.get("_existing_tags", []) or []
        for i, s in enumerate(slugs, start=1):
            data[f"tags-{i}"] = s

        return await self._post_manage_form(
            f"asset/{publisher}/{slug}/settings/update/",
            data,
            publisher=publisher,
            slug=slug,
        )

    # ---------------------------------------------------- media tab

    @staticmethod
    def _scrape_existing_media_ids(soup: BeautifulSoup) -> list[str]:
        """Return the existing screenshot/media item ids in current display order."""
        ids: list[str] = []
        for item in soup.select('.media-manager .media-item[data-type="existing"]'):
            order = item.find("input", {"name": lambda n: bool(n and n.startswith("media_order"))})
            if order and order.get("value"):
                ids.append(order["value"])
        return ids

    async def update_media(
        self,
        publisher: str,
        slug: str,
        *,
        thumbnail_path: str | Path | None = None,
        featured_thumbnail_path: str | Path | None = None,
        clear_featured: bool = False,
        video_url: str | None = None,
        add_screenshots: list[str | Path] | None = None,
        keep_existing_screenshots: bool = True,
    ) -> dict[str, Any]:
        """POST the /media/update/ form.

        - ``thumbnail_path`` / ``featured_thumbnail_path``: local file paths to
          upload. Leave ``None`` to keep the current value.
        - ``clear_featured``: explicitly remove the existing featured image.
        - ``video_url``: YouTube URL or ``""`` to clear; ``None`` to keep.
        - ``add_screenshots``: list of local files to append to the screenshot
          gallery. The existing screenshots are kept (in their current order)
          unless ``keep_existing_screenshots=False``.
        """
        soup = await self._fetch_manage(publisher, slug)
        csrf = self._csrf_token(soup)

        # Default values from existing form
        media_form = next(
            (f for f in soup.find_all("form") if f.get("hx-post", "").endswith("/media/update/")),
            None,
        )
        current_video = ""
        if media_form is not None:
            video_input = media_form.find("input", {"name": "video"})
            if video_input is not None:
                current_video = video_input.get("value", "") or ""

        existing_ids = self._scrape_existing_media_ids(soup) if keep_existing_screenshots else []

        data: dict[str, str] = {
            "csrf_token": csrf,
            "video": video_url if video_url is not None else current_video,
            "thumbnail_updated": "true" if thumbnail_path is not None else "false",
            "featured_thumbnail_updated": (
                "true" if (featured_thumbnail_path is not None or clear_featured) else "false"
            ),
        }

        files: dict[str, Any] = {}
        if thumbnail_path is not None:
            p = Path(thumbnail_path)
            files["thumbnail"] = (p.name, p.read_bytes(), _guess_mime(p))
        if featured_thumbnail_path is not None:
            p = Path(featured_thumbnail_path)
            files["featured_thumbnail"] = (p.name, p.read_bytes(), _guess_mime(p))

        # Reorder + add screenshots. The form indexes media_order from 0 and
        # references new uploads as "NEW::<upload-index>".
        order_index = 0
        for existing_id in existing_ids:
            data[f"media_order-{order_index}"] = existing_id
            order_index += 1
        for upload_index, path in enumerate(add_screenshots or []):
            p = Path(path)
            files_key = f"new_uploads-{upload_index}"
            files[files_key] = (p.name, p.read_bytes(), _guess_mime(p))
            data[f"media_order-{order_index}"] = f"NEW::{upload_index}"
            order_index += 1

        return await self._post_manage_form(
            f"asset/{publisher}/{slug}/media/update/",
            data,
            files=files,
            publisher=publisher,
            slug=slug,
        )

    # ---------------------------------------------------- version upload

    async def upload_version(
        self,
        publisher: str,
        slug: str,
        *,
        file_path: str | Path,
        version_name: str,
        changelog: str = "",
        stable: bool = True,
        min_godot_version: str = "Undefined",
        max_godot_version: str = "Undefined",
        version_notes: str = "",
    ) -> dict[str, Any]:
        """Upload a new version archive.

        Three steps, mirroring the upstream JS:

        1. POST /version/upload_url/ — returns ``{upload_url, queue_id}``.
        2. PUT the file body directly to that S3 pre-signed URL.
        3. POST /version/create/ to commit the upload.
        """
        soup = await self._fetch_manage(publisher, slug)
        csrf = self._csrf_token(soup)

        path = Path(file_path)
        body = path.read_bytes()
        md5 = hashlib.md5(body).digest()
        checksum_b64 = base64.b64encode(md5).decode()

        common: dict[str, str] = {
            "csrf_token": csrf,
            "name": version_name,
            "changelog": changelog,
            "min_godot_version": min_godot_version,
            "max_godot_version": max_godot_version,
            "version_notes": version_notes,
        }
        if stable:
            common["stable"] = "y"

        client = self._ensure_client()
        manage_url = urljoin(self.base_url + "/", f"asset/{publisher}/{slug}/manage/")

        # Step 1
        upload_url_endpoint = urljoin(
            self.base_url + "/", f"asset/{publisher}/{slug}/version/upload_url/"
        )
        step1 = await client.post(
            upload_url_endpoint,
            data={**common, "filename": path.name, "checksum": checksum_b64},
            files={},
            headers={
                "X-CSRFToken": csrf,
                "Referer": manage_url,
                "HX-Request": "true",
            },
            follow_redirects=False,
        )
        if step1.status_code >= 400:
            try:
                err = step1.json().get("error") or step1.text[:300]
            except ValueError:
                err = step1.text[:300]
            raise StoreError(step1.status_code, f"version/upload_url rejected: {err}")
        try:
            payload = step1.json()
        except ValueError as e:
            raise StoreError(500, f"version/upload_url returned non-JSON: {step1.text[:200]}") from e
        upload_url = payload.get("upload_url")
        queue_id = payload.get("queue_id")
        if not upload_url or not queue_id:
            raise StoreError(500, f"version/upload_url missing fields: {payload!r}")

        # Step 2 — direct PUT to S3 pre-signed URL. The pre-signed URL embeds
        # auth; we must NOT send the store's session cookie or our default
        # User-Agent could trip the signature.
        async with httpx.AsyncClient(timeout=600.0) as raw:
            put_resp = await raw.put(
                upload_url,
                content=body,
                headers={"Content-Type": "application/octet-stream"},
            )
        if put_resp.status_code >= 400:
            raise StoreError(put_resp.status_code, f"S3 upload failed: {put_resp.text[:300]}")

        # Step 3
        create_endpoint = urljoin(
            self.base_url + "/", f"asset/{publisher}/{slug}/version/create/"
        )
        step3 = await client.post(
            create_endpoint,
            data={**common, "queue_id": str(queue_id)},
            files={},
            headers={
                "X-CSRFToken": csrf,
                "Referer": manage_url,
                "HX-Request": "true",
            },
            follow_redirects=False,
        )
        if step3.status_code >= 400:
            try:
                err = step3.json().get("error") or step3.text[:300]
            except ValueError:
                err = step3.text[:300]
            raise StoreError(step3.status_code, f"version/create rejected: {err}")

        return {
            "ok": True,
            "queue_id": queue_id,
            "filename": path.name,
            "checksum_b64": checksum_b64,
            "size": len(body),
            "version_name": version_name,
        }

    # ---------------------------------------------------- pricing

    @staticmethod
    def _parse_pricing_form(soup: BeautifulSoup) -> dict[str, str]:
        pricing_form = next(
            (
                f
                for f in soup.find_all("form")
                if f.get("hx-post", "").endswith("/pricing/update/")
            ),
            None,
        )
        current: dict[str, str] = {}
        if pricing_form is None:
            return current
        for inp in pricing_form.find_all("input"):
            n = inp.get("name")
            if not n or n == "csrf_token":
                continue
            if inp.get("type") == "checkbox":
                current[n] = "y" if inp.has_attr("checked") else ""
            else:
                current[n] = inp.get("value", "") or ""
        return current

    async def get_pricing(self, publisher: str, slug: str) -> dict[str, Any]:
        soup = await self._fetch_manage(publisher, slug)
        current = self._parse_pricing_form(soup)
        raw_price = current.get("price_cent", "")
        try:
            price_cent = int(raw_price) if raw_price != "" else 0
        except ValueError:
            price_cent = None
        return {
            "publisher_slug": publisher,
            "asset_slug": slug,
            "price_cent": price_cent,
            "reviews_disabled": current.get("reviews_disabled") == "y",
            "donation_text": current.get("donation_text", ""),
            "donation_url": current.get("donation_url", ""),
        }

    async def set_pricing(
        self,
        publisher: str,
        slug: str,
        *,
        price_cent: int | None = None,
        reviews_disabled: bool | None = None,
        donation_text: str | None = None,
        donation_url: str | None = None,
    ) -> dict[str, Any]:
        soup = await self._fetch_manage(publisher, slug)
        csrf = self._csrf_token(soup)
        current = self._parse_pricing_form(soup)

        data: dict[str, str] = {
            "csrf_token": csrf,
            "price_cent": (
                "" if price_cent is None else str(price_cent)
            ) if price_cent is not None else current.get("price_cent", ""),
            "donation_text": (
                donation_text if donation_text is not None else current.get("donation_text", "")
            ),
            "donation_url": (
                donation_url if donation_url is not None else current.get("donation_url", "")
            ),
        }
        if reviews_disabled is None:
            if current.get("reviews_disabled") == "y":
                data["reviews_disabled"] = "y"
        elif reviews_disabled:
            data["reviews_disabled"] = "y"

        return await self._post_manage_form(
            f"asset/{publisher}/{slug}/pricing/update/",
            data,
            publisher=publisher,
            slug=slug,
        )

    # ---------------------------------------------------- submit for review

    async def submit_for_review(self, publisher: str, slug: str) -> dict[str, Any]:
        soup = await self._fetch_manage(publisher, slug)
        csrf = self._csrf_token(soup)
        return await self._post_manage_form(
            f"asset/{publisher}/{slug}/update_status/",
            {"csrf_token": csrf, "action": "mark_public"},
            publisher=publisher,
            slug=slug,
        )

    async def resolve_download_url(
        self, publisher: str, slug: str, download_id: str | None = None
    ) -> str:
        """Resolve a direct (CDN) download URL for the given asset version.

        If ``download_id`` is None, picks the currently-selected version on the
        asset detail page.
        """
        asset = await self.get_asset(publisher, slug)
        downloads = asset.get("downloads") or []
        if not downloads:
            raise StoreError(404, f"no downloads listed for {publisher}/{slug}")
        if download_id is None:
            chosen = next((d for d in downloads if d.get("selected")), downloads[0])
        else:
            chosen = next((d for d in downloads if str(d.get("id")) == str(download_id)), None)
            if chosen is None:
                ids = ", ".join(str(d.get("id")) for d in downloads)
                raise StoreError(404, f"download id {download_id} not found (available: {ids})")
        direct = chosen.get("direct_url")
        if direct:
            return direct
        # Fall back to the in-store download endpoint, which redirects to the CDN.
        return urlunparse(
            urlparse(urljoin(self.base_url + "/", f"asset/{publisher}/{slug}/download/{chosen['id']}/"))
        )


_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".zip": "application/zip",
}


def _guess_mime(path: Path) -> str:
    return _MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream")
