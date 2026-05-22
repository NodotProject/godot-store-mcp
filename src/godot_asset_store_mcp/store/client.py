"""Client for the new Godot Asset Store (store.godotengine.org).

The new store does not (yet) publish a JSON API, so this module talks to the
HTMX-driven HTML pages and scrapes structured data out of them. Endpoints and
selectors may change without notice while the store is in beta.

Authenticated state is carried by a single ``session`` cookie issued by the
Flask app once OIDC has completed. Use ``store/login.py`` to obtain one.
"""

from __future__ import annotations

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
