"""arXiv metadata ingestion with bounded parsing and a shared request limiter."""

from __future__ import annotations

import asyncio
import re
import time
import weakref
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

API_URL = "https://export.arxiv.org/api/query"
MAX_BYTES = 2_000_000
MIN_REQUEST_INTERVAL = 3.1
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_MODERN = re.compile(r"(?P<year>\d{2})(?P<month>\d{2})\.(?P<number>\d{4,5})(?P<version>v[1-9]\d{0,4})?\Z")
_OLD = re.compile(
    r"(?P<archive>[a-zA-Z][a-zA-Z0-9.-]{0,30})/(?P<year>\d{2})(?P<month>\d{2})(?P<number>\d{3})(?P<version>v[1-9]\d{0,4})?\Z"
)
_LIMITERS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


class ArxivError(Exception):
    """Safe source error without remote response bodies."""


class _RateLimiter:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.last_request: float | None = None

    async def wait(self) -> None:
        async with self.lock:
            if self.last_request is not None:
                # Some event loops may wake timers slightly early. Check the clock
                # again instead of assuming a sleep guarantees the minimum delay.
                deadline = self.last_request + MIN_REQUEST_INTERVAL
                while (remaining := deadline - time.monotonic()) > 0:
                    await asyncio.sleep(remaining)
            self.last_request = time.monotonic()


def _limiter() -> _RateLimiter:
    # A fresh event loop (CLI/test) needs its own asyncio primitive.
    loop = asyncio.get_running_loop()
    if loop not in _LIMITERS:
        _LIMITERS[loop] = _RateLimiter()
    return _LIMITERS[loop]


def normalize_arxiv_id(value: str) -> str:
    """Accept an identifier or official /abs or /pdf URL, retaining vN if present."""
    if not isinstance(value, str) or len(value) > 250:
        raise ArxivError("Enter a valid arXiv identifier or official arXiv abstract URL.")
    identifier = value.strip()
    if identifier.lower().startswith("arxiv:"):
        identifier = identifier[6:].strip()
    if "://" in identifier:
        try:
            parsed = urlsplit(identifier)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}
                or parsed.port is not None
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError
        except ValueError:
            raise ArxivError("Only official arXiv abstract or PDF URLs are accepted.") from None
        if parsed.path.startswith("/abs/"):
            identifier = parsed.path[5:]
        elif parsed.path.startswith("/pdf/"):
            identifier = parsed.path[5:]
            if identifier.endswith(".pdf"):
                identifier = identifier[:-4]
        else:
            raise ArxivError("The arXiv URL must point to /abs/ or /pdf/.")
    match = _MODERN.fullmatch(identifier) or _OLD.fullmatch(identifier)
    if not match or not 1 <= int(match["month"]) <= 12:
        raise ArxivError("Invalid arXiv identifier. Examples: 2303.08774 or hep-th/9901001v2.")
    if "." in identifier and "/" not in identifier:
        year, month = int(match["year"]), int(match["month"])
        if year < 7 or (year == 7 and month < 4):
            raise ArxivError("Modern arXiv identifiers begin in April 2007.")
    return identifier


def _parts(identifier: str) -> tuple[str, int]:
    match = re.search(r"v([1-9]\d*)$", identifier)
    return (identifier[: match.start()], int(match[1])) if match else (identifier, 1)


def _date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00").replace("/", "-"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError):
        raise ArxivError("arXiv returned an invalid publication date.") from None


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_atom(content: bytes, maximum: int) -> list[dict]:
    if len(content) > MAX_BYTES:
        raise ArxivError("arXiv returned an oversized metadata feed.")
    try:
        root = SafeET.fromstring(content, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (SafeET.ParseError, DefusedXmlException, ValueError, RecursionError):
        raise ArxivError("arXiv returned an invalid or unsafe metadata feed.") from None
    if root.tag != f"{_ATOM}feed":
        raise ArxivError("arXiv did not return an Atom metadata feed.")
    entries = root.findall(f"{_ATOM}entry")
    if len(entries) > maximum:
        raise ArxivError("arXiv returned more papers than requested.")
    papers, seen = [], set()
    for entry in entries:
        identifier_text = entry.findtext(f"{_ATOM}id", "")
        if "/api/errors" in identifier_text:
            raise ArxivError("arXiv rejected the search or one of the paper identifiers.")
        identifier = normalize_arxiv_id(identifier_text)
        base, version = _parts(identifier)
        if (base, version) in seen:
            continue
        seen.add((base, version))
        title = _clean(entry.findtext(f"{_ATOM}title", ""))
        abstract = entry.findtext(f"{_ATOM}summary", "").strip()
        authors = [_clean(author.findtext(f"{_ATOM}name", "")) for author in entry.findall(f"{_ATOM}author")]
        categories = list(
            dict.fromkeys(category.get("term", "") for category in entry.findall(f"{_ATOM}category"))
        )
        if (
            not title
            or not abstract
            or not authors
            or any(not name for name in authors)
            or len(title) > 2000
            or len(abstract) > 32000
        ):
            raise ArxivError("arXiv returned incomplete or oversized paper metadata.")
        papers.append(
            {
                "arxiv_id": base,
                "version": version,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "categories": categories,
                "published": _date(entry.findtext(f"{_ATOM}published", "")),
                "updated": _date(entry.findtext(f"{_ATOM}updated", "")),
                "source_url": f"https://arxiv.org/abs/{base}v{version}",
                "pdf_url": f"https://arxiv.org/pdf/{base}v{version}",
                "source": "arxiv",
                "metadata_source": "arxiv_atom_api",
            }
        )
    return papers


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.in_abstract = False
        self.abstract: list[str] = []
        self.in_title = False
        self.page_title: list[str] = []
        self.all_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "meta" and attr.get("name") and attr.get("content"):
            self.meta.setdefault(attr["name"], []).append(attr["content"])
        if tag == "blockquote" and "abstract" in attr.get("class", "").split():
            self.in_abstract = True
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "blockquote":
            self.in_abstract = False
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        self.all_text.append(data)
        if self.in_abstract:
            self.abstract.append(data)
        if self.in_title:
            self.page_title.append(data)


def _parse_abstract_page(content: bytes, requested: str) -> dict:
    parser = _MetadataParser()
    try:
        parser.feed(content.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError, RecursionError):
        raise ArxivError("arXiv returned an invalid abstract page.") from None
    meta = parser.meta

    def first(name: str) -> str:
        return next(iter(meta.get(name, [])), "")

    requested_base, requested_version = _parts(requested)
    citation_id = first("citation_arxiv_id")
    if not citation_id:
        title_match = re.match(r"\[([^\]]+)\]", "".join(parser.page_title).strip())
        citation_id = title_match[1] if title_match else ""
    if not citation_id or _parts(normalize_arxiv_id(citation_id))[0] != requested_base:
        raise ArxivError("The official arXiv page does not match the requested paper.")
    page_text = " ".join(parser.all_text)
    versions = [int(value) for value in re.findall(r"\[v(\d+)\]", page_text)]
    version = (
        requested_version
        if re.search(r"v\d+$", requested)
        else (max(versions) if versions else _parts(citation_id)[1])
    )
    title = _clean(first("citation_title"))
    abstract = "".join(parser.abstract).strip()
    abstract = re.sub(r"^\s*Abstract:\s*", "", abstract).strip()
    if not abstract:
        # citation_abstract is publisher-supplied full abstract metadata when present.
        abstract = first("citation_abstract").strip()
    authors = [_clean(author) for author in meta.get("citation_author", [])]
    if not title or not abstract or not authors or len(title) > 2000 or len(abstract) > 32000:
        raise ArxivError("The official arXiv page is missing complete paper metadata.")
    published = first("citation_date") or first("citation_publication_date")
    updated = first("citation_online_date") or published
    categories = list(dict.fromkeys(re.findall(r"\(([a-z-]+(?:\.[A-Z]{2})?)\)", page_text)))
    return {
        "arxiv_id": requested_base,
        "version": version,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "categories": categories,
        "published": _date(published),
        "updated": _date(updated),
        "source_url": f"https://arxiv.org/abs/{requested_base}v{version}",
        "pdf_url": f"https://arxiv.org/pdf/{requested_base}v{version}",
        "source": "arxiv",
        "metadata_source": "arxiv_abstract_page",
        "source_note": "Official abstract-page metadata fallback; dates have day precision when supplied by citation metadata.",
    }


async def _request(client: httpx.AsyncClient, url: str, *, params: dict | None = None) -> tuple[int, bytes]:
    await _limiter().wait()
    try:
        async with client.stream(
            "GET",
            url,
            params=params,
            headers={
                "User-Agent": "JevScout/0.1 (local research reading inbox)",
                "Accept": "application/atom+xml, text/html;q=0.9",
            },
            timeout=30,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                return response.status_code, b""
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise ArxivError("arXiv returned an oversized metadata response.")
            return 200, bytes(content)
    except httpx.TimeoutException:
        raise ArxivError("arXiv timed out. Retry the import later.") from None
    except httpx.HTTPError:
        raise ArxivError("Could not reach arXiv. Check your network and retry.") from None


async def _fetch(
    client: httpx.AsyncClient, query: str | None, identifiers: list[str] | None, maximum: int
) -> list[dict]:
    params: dict = {"start": 0, "max_results": maximum}
    if identifiers:
        identifiers = identifiers[:maximum]
        params["id_list"] = ",".join(identifiers)
    else:
        params.update(search_query=query, sortBy="submittedDate", sortOrder="descending")
    status, content = await _request(client, API_URL, params=params)
    if status == 200:
        papers = _parse_atom(content, maximum)
        if identifiers:
            expected = [
                (_parts(identifier)[0], _parts(identifier)[1] if re.search(r"v\d+$", identifier) else None)
                for identifier in identifiers
            ]

            def matches(paper: dict, requested: tuple[str, int | None]) -> bool:
                return paper["arxiv_id"] == requested[0] and (
                    requested[1] is None or paper["version"] == requested[1]
                )

            if any(not any(matches(paper, requested) for requested in expected) for paper in papers):
                raise ArxivError(
                    "arXiv returned an unexpected paper ID or a different paper version than requested."
                )
            if any(not any(matches(paper, requested) for paper in papers) for requested in expected):
                raise ArxivError(
                    "arXiv returned missing paper IDs or versions. Check the identifiers and retry."
                )
        return papers
    # arXiv sometimes blocks its API while official paper pages remain available.
    # Preserve provenance; never use a mirror or substitute a demonstration paper.
    if identifiers and status in {403, 406, 500, 502, 503, 504}:
        papers = []
        for identifier in identifiers[:maximum]:
            page_status, page = await _request(client, f"https://arxiv.org/abs/{identifier}")
            if page_status != 200:
                raise ArxivError(f"The official arXiv abstract page was unavailable (HTTP {page_status}).")
            papers.append(_parse_abstract_page(page, identifier))
        return papers
    if status == 429:
        raise ArxivError("arXiv is rate-limiting requests. Wait before retrying this import.")
    if query:
        raise ArxivError(
            f"The arXiv search API is unavailable (HTTP {status}). Try importing official arXiv paper IDs instead."
        )
    raise ArxivError(f"arXiv could not complete the request (HTTP {status}).")


async def fetch_papers(
    *,
    query: str | None = None,
    ids: list[str] | None = None,
    max_results: int = 30,
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Fetch a bounded set, with one request start per >=3.1 seconds per event loop."""
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 100:
        raise ArxivError("max_results must be between 1 and 100.")
    if (query is None) == (ids is None):
        raise ArxivError("Provide either an arXiv search query or a list of paper IDs.")
    identifiers = None
    if ids is not None:
        if not isinstance(ids, list) or not ids or len(ids) > 50:
            raise ArxivError("Provide between 1 and 50 arXiv paper IDs.")
        identifiers = list(dict.fromkeys(normalize_arxiv_id(value) for value in ids))
    else:
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > 1000
            or any(ord(char) < 32 for char in query)
        ):
            raise ArxivError(
                "Provide a nonempty arXiv query of at most 1000 characters without control characters."
            )
        query = query.strip()
    if client is None:
        async with httpx.AsyncClient() as owned_client:
            return await _fetch(owned_client, query, identifiers, max_results)
    return await _fetch(client, query, identifiers, max_results)
