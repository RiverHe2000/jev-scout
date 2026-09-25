import asyncio
import time

import httpx
import pytest

from jev_scout import arxiv
from jev_scout.arxiv import ArxivError, fetch_papers, normalize_arxiv_id

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2303.08774v2</id><title> A real\n paper title </title>
<summary>  Abstract first sentence.\nSecond sentence.  </summary>
<author><name>First Author</name></author><author><name>Second Author</name></author>
<category term="cs.AI"/><published>2023-03-15T12:00:00Z</published><updated>2023-04-01T01:30:00Z</updated>
<link rel="alternate" href="https://evil.example/track"/><link title="pdf" href="file:///etc/passwd"/>
</entry></feed>"""

PAGE = b"""<html><head><title>[2303.08774] Paper title</title>
<meta name="citation_arxiv_id" content="2303.08774"/>
<meta name="citation_title" content="Paper &amp; title"/>
<meta name="citation_author" content="One Author"/>
<meta name="citation_date" content="2023/03/15"/>
<meta name="citation_online_date" content="2023/04/01"/>
</head><body><blockquote class="abstract mathjax"><span class="descriptor">Abstract:</span> Original abstract. It has evidence.</blockquote>
<div>Artificial Intelligence (cs.AI) [v1] [v2]</div></body></html>"""


@pytest.fixture(autouse=True)
def reset_limiter(monkeypatch):
    monkeypatch.setattr(arxiv, "MIN_REQUEST_INTERVAL", 0)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2303.08774", "2303.08774"),
        ("arXiv:2303.08774v2", "2303.08774v2"),
        (" https://arxiv.org/abs/2303.08774v2 ", "2303.08774v2"),
        ("http://arxiv.org/pdf/2303.08774.pdf", "2303.08774"),
        ("https://export.arxiv.org/abs/hep-th/9901001v3", "hep-th/9901001v3"),
        ("0704.0001", "0704.0001"),
    ],
)
def test_normalize_valid_ids(value, expected):
    assert normalize_arxiv_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/abs/2303.08774",
        "https://arxiv.org.evil.example/abs/2303.08774",
        "https://arxiv.org@evil.example/abs/2303.08774",
        "file:///2303.08774",
        "https://arxiv.org:443/abs/2303.08774",
        "https://arxiv.org/abs/2303.08774?url=http://localhost",
        "https://arxiv.org/abs/2303.08774#fragment",
        "https://arxiv.org/abs/../2303.08774",
        "https://arxiv.org/abs/%32%33%30%33.08774",
        "2313.08774",
        "2300.08774",
        "2303.08774v0",
        "2303.08774\nmalicious",
        "https://arxiv.org/search/2303.08774",
        "0601.00123",
        "",
        None,
    ],
)
def test_normalize_rejects_invalid_or_nonofficial(value):
    with pytest.raises(ArxivError):
        normalize_arxiv_id(value)


@pytest.mark.asyncio
async def test_atom_import_has_official_provenance_and_safe_links():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=FEED)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        papers = await fetch_papers(ids=["https://arxiv.org/abs/2303.08774v2"], client=client)
    paper = papers[0]
    assert paper["arxiv_id"] == "2303.08774" and paper["version"] == 2
    assert paper["title"] == "A real paper title"
    assert paper["abstract"] == "Abstract first sentence.\nSecond sentence."
    assert paper["source"] == "arxiv" and paper["metadata_source"] == "arxiv_atom_api"
    assert paper["pdf_url"] == "https://arxiv.org/pdf/2303.08774v2"
    assert paper["source_url"] == "https://arxiv.org/abs/2303.08774v2"
    assert str(requests[0].url).startswith(arxiv.API_URL)
    assert requests[0].url.params["id_list"] == "2303.08774v2"


@pytest.mark.asyncio
async def test_query_uses_fixed_endpoint_and_sort():
    async def handler(request):
        assert request.url.host == "export.arxiv.org"
        assert request.url.params["search_query"] == 'cat:cs.AI AND all:"memory"'
        assert request.url.params["sortBy"] == "submittedDate"
        return httpx.Response(200, content=FEED)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert len(await fetch_papers(query='cat:cs.AI AND all:"memory"', max_results=2, client=client)) == 1


@pytest.mark.asyncio
async def test_ids_fall_back_to_official_abstract_pages_with_provenance():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return (
            httpx.Response(406)
            if request.url.host == "export.arxiv.org"
            else httpx.Response(200, content=PAGE)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = (await fetch_papers(ids=["2303.08774"], client=client))[0]
    assert urls[1] == "https://arxiv.org/abs/2303.08774"
    assert result["metadata_source"] == "arxiv_abstract_page"
    assert result["abstract"] == "Original abstract. It has evidence."
    assert result["title"] == "Paper & title" and result["version"] == 2
    assert result["categories"] == ["cs.AI"]


@pytest.mark.asyncio
async def test_abstract_fallback_rejects_wrong_paper():
    def handler(request):
        return (
            httpx.Response(406)
            if request.url.host == "export.arxiv.org"
            else httpx.Response(200, content=PAGE.replace(b"2303.08774", b"2303.09999"))
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArxivError, match="does not match"):
            await fetch_papers(ids=["2303.08774"], client=client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        b"<html>not atom</html>",
        b"not xml",
        b"<feed>",
        b'<!DOCTYPE feed [<!ENTITY payload "expanded">]><feed xmlns="http://www.w3.org/2005/Atom">&payload;</feed>',
        FEED.replace(b"2023-03-15T12:00:00Z", b"not-a-date"),
        FEED.replace(b"<title> A real\n paper title </title>", b"<title></title>"),
        FEED.replace(
            b"http://arxiv.org/abs/2303.08774v2", b"http://arxiv.org/api/errors#incorrect_id_format"
        ),
        b"x" * 2_000_001,
    ],
    ids=["html", "plain", "truncated", "entity", "date", "missing-title", "api-error", "oversized"],
)
async def test_malformed_unsafe_or_oversized_feeds_fail(content):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    ) as client:
        with pytest.raises(ArxivError):
            await fetch_papers(query="all:memory", client=client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"query": ""},
        {"query": "a", "ids": ["2303.08774"]},
        {"ids": []},
        {"ids": ["2303.08774"], "max_results": 0},
        {"query": "abc\n"},
        {"query": "x", "max_results": True},
    ],
)
async def test_invalid_arguments_never_hit_network(kwargs):
    with pytest.raises(ArxivError):
        await fetch_papers(**kwargs)


@pytest.mark.asyncio
async def test_rate_limit_is_shared_between_concurrent_calls(monkeypatch):
    monkeypatch.setattr(arxiv, "MIN_REQUEST_INTERVAL", 0.03)
    times = []

    def handler(request):
        times.append(time.monotonic())
        return httpx.Response(200, content=FEED)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await asyncio.gather(*(fetch_papers(query="all:memory", client=client) for _ in range(3)))
    assert len(times) == 3
    assert all(right - left >= 0.025 for left, right in zip(times, times[1:], strict=False))


@pytest.mark.asyncio
async def test_query_failure_is_actionable_and_not_a_demo_substitution():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(406, text="private body"))
    ) as client:
        with pytest.raises(ArxivError, match="paper IDs") as error:
            await fetch_papers(query="all:memory", client=client)
    assert "private body" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["2303.08774v1", "2303.09999"])
async def test_api_papers_must_match_requested_ids_and_versions(identifier):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=FEED))
    ) as client:
        with pytest.raises(ArxivError, match="unexpected"):
            await fetch_papers(ids=[identifier], client=client)


@pytest.mark.asyncio
async def test_missing_requested_paper_is_reported():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=FEED))
    ) as client:
        with pytest.raises(ArxivError, match="missing"):
            await fetch_papers(ids=["2303.08774", "2303.09999"], client=client)


@pytest.mark.asyncio
async def test_id_limit_is_applied_before_the_request():
    def handler(request):
        assert request.url.params["id_list"] == "2303.08774"
        return httpx.Response(200, content=FEED)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_papers(ids=["2303.08774", "2303.09999"], max_results=1, client=client)
    assert len(result) == 1
