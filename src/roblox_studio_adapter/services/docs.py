"""Fetch Creator docs the way the docs tell an agent to.

``http_get`` only allows a few URL prefixes, and the URL must end in ``.md``
or be ``llms.txt``. The search API (``/docs/api/search``) is not on that
allowlist, so search goes out over ordinary HTTPS from this process. Page
reads go through Studio when a session is connected, because that is the
tool the server provides and it can trim to a keyword.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from roblox_studio_adapter.session import Session

_DOCS = "https://create.roblox.com/docs"
_ENGINE = "https://create.roblox.com/docs/reference/engine"


class DocsService:
    def __init__(self, session: Session | None = None) -> None:
        self.session = session

    def search(self, question: str, *, limit: int = 8) -> dict:
        """Semantic search. Returns the JSON payload from the Creator docs index."""
        query = urllib.parse.urlencode({"q": question})
        url = f"{_DOCS}/api/search?{query}"
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            payload["results"] = payload["results"][:limit]
        return payload

    def read(self, url: str, *, query: str | None = None, context_lines: int | None = None) -> str:
        """Read one docs page. ``url`` must already be an allowed http_get URL."""
        if not url.endswith(".md") and not url.endswith("llms.txt"):
            if url.startswith(_DOCS):
                url = url + ".md"
            else:
                raise ValueError("Docs URLs fetched through Studio must end in .md or be llms.txt.")
        if self.session is None:
            with urllib.request.urlopen(url, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        result = self.session.call(
            "http_get",
            {"url": url, "query": query, "context_lines": context_lines},
        )
        return result.text

    def engine_class(self, class_name: str, *, query: str | None = None) -> str:
        return self.read(f"{_ENGINE}/classes/{class_name}.md", query=query)

    def latest_features(self) -> dict:
        """The index the docs tell agents to read before trusting older API memory.

        This file is JSON, so it is fetched directly. Studio's http_get would
        reject it because it does not end in .md.
        """
        url = f"{_DOCS}/latest-features.json"
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
