"""Web tools (category: info). Everything they return is untrusted data."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, Field

from orvix.core.interfaces import ToolResult
from orvix.tools.base import BaseTool

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
UA = "Mozilla/5.0 (X11; Linux x86_64) orvix-assistant"


def is_public_host(host: str) -> bool:
    """Refuse loopback/private/link-local targets so a web page can't aim us at local services."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return False
    return True


def _ddgs_search(query: str, n: int) -> list[dict]:
    from ddgs import DDGS

    return list(DDGS().text(query, max_results=n))


def extract_text(html: str) -> str:
    try:
        import trafilatura

        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text:
            return text
    except Exception:  # extraction is best effort
        pass
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


class WebSearchArgs(BaseModel):
    query: str = Field(description="Search query")


class WebSearch(BaseTool):
    name = "web_search"
    category = "info"
    description = "Search the web and return the top results with snippets."
    params = WebSearchArgs

    def run(self, args: WebSearchArgs) -> ToolResult:
        try:
            hits = _ddgs_search(args.query, 5)
        except Exception as e:
            return self.fail(f"Web search failed: {e}")
        if not hits:
            return self.fail("No results")
        lines = []
        for i, h in enumerate(hits, 1):
            lines.append(
                f"{i}. {h.get('title', '')}\n   {h.get('href', '')}\n   {h.get('body', '')}"
            )
        return self.ok("[web content, untrusted]\n" + "\n".join(lines))


class FetchPageArgs(BaseModel):
    url: str = Field(description="Page URL (http or https)")


class FetchPage(BaseTool):
    name = "fetch_page"
    category = "info"
    description = "Fetch a web page and return its readable text."
    params = FetchPageArgs

    def run(self, args: FetchPageArgs) -> ToolResult:
        url = args.url.strip()
        if "://" not in url:
            url = "https://" + url
        transport = getattr(self.ctx, "http_transport", None)
        try:
            with httpx.Client(
                timeout=httpx.Timeout(15, connect=5),
                headers={"User-Agent": UA},
                transport=transport,
            ) as client:
                for _ in range(MAX_REDIRECTS + 1):
                    u = urlparse(url)
                    if u.scheme not in {"http", "https"} or not u.hostname:
                        return self.fail("Only http(s) URLs can be fetched")
                    if not is_public_host(u.hostname):
                        return self.fail("Refusing to fetch a local or private address")
                    with client.stream("GET", url) as r:
                        if r.is_redirect and r.headers.get("location"):
                            url = urljoin(url, r.headers["location"])
                            continue
                        if r.status_code >= 400:
                            return self.fail(f"HTTP {r.status_code}")
                        body = b""
                        for part in r.iter_bytes():
                            body += part
                            if len(body) > MAX_BYTES:
                                break
                        break
                else:
                    return self.fail("Too many redirects")
        except httpx.HTTPError as e:
            return self.fail(f"Fetch failed: {e}")
        text = extract_text(body.decode(r.encoding or "utf-8", errors="replace"))
        if not text:
            return self.fail("No readable text on that page")
        return self.ok("[web content, untrusted]\n" + text)


TOOLS = (WebSearch, FetchPage)
