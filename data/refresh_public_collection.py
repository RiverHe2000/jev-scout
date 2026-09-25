"""Refresh attributed arXiv abstract-page metadata; no PDFs or full text downloaded.

This maintenance script is deliberately separate from the production Atom client.
The arXiv API returned HTTP 406 during initial fixture creation. Requests are
serial and separated by at least 3.1 seconds. The snapshot retains source/license.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

IDS = [
    "2310.08560",
    "2304.03442",
    "2307.03172",
    "2310.11511",
    "2401.15884",
    "2005.11401",
    "2305.18290",
    "2106.09685",
    "2305.14314",
    "2205.14135",
    "2309.06180",
    "2302.04761",
    "2210.03629",
    "2308.03688",
    "2310.06770",
    "2410.10813",
    "2405.14831",
    "2309.12307",
    "2401.18059",
    "2304.11406",
]
ROOT = Path(__file__).resolve().parent


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, list[str]] = {}
        self.license = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name", "").startswith("citation_"):
            self.fields.setdefault(attrs["name"], []).append(attrs.get("content", ""))
        if tag == "a" and attrs.get("title") == "Rights to this article":
            self.license = attrs.get("href")


def parse_page(arxiv_id: str, html: str) -> dict:
    parser = Metadata()
    parser.feed(html)
    fields = parser.fields
    versions = re.findall(rf"{re.escape(arxiv_id)}v(\d+)", html)
    version = max(map(int, versions), default=1)
    subjects = re.search(r'<td class="tablecell subjects">(.*?)</td>', html, re.S)
    categories = re.findall(r"\(([a-z]+(?:\.[A-Za-z]+)?)\)", subjects.group(1)) if subjects else []
    required = ("citation_title", "citation_author", "citation_abstract", "citation_date")
    if any(not fields.get(key) for key in required):
        raise ValueError(f"Missing arXiv metadata for {arxiv_id}")
    abstract = fields["citation_abstract"][0].strip()
    published = fields["citation_date"][0].replace("/", "-")
    updated = fields.get("citation_online_date", [published])[0].replace("/", "-")
    return {
        "arxiv_id": arxiv_id,
        "version": version,
        "title": fields["citation_title"][0],
        "authors": fields["citation_author"],
        "abstract": abstract,
        "categories": categories,
        "published": published,
        "updated": updated,
        "source_url": f"https://arxiv.org/abs/{arxiv_id}v{version}",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}v{version}",
        "source": "bundled",
        "provenance": {
            "retrieved_at": datetime.now(UTC).isoformat(),
            "metadata_url": f"https://arxiv.org/abs/{arxiv_id}",
            "retrieval_method": "official_arxiv_abstract_page_citation_meta_tags",
            "license_url": parser.license,
            "metadata_license": "CC0-1.0",
            "metadata_terms_url": "https://info.arxiv.org/help/api/tou.html",
            "date_precision": "day",
            "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest(),
            "content_note": "Title, authors and abstract metadata only; no paper full text. License URL is the article license reported by arXiv.",
        },
    }


def main():
    destination = ROOT / "papers.json"
    existing = (
        {p["arxiv_id"]: p for p in json.loads(destination.read_text(encoding="utf-8"))}
        if destination.exists()
        else {}
    )
    previous_start = 0.0
    for arxiv_id in IDS:
        if arxiv_id in existing:
            continue
        time.sleep(max(0, 3.1 - (time.monotonic() - previous_start)))
        previous_start = time.monotonic()
        url = f"https://arxiv.org/abs/{arxiv_id}"
        request = urllib.request.Request(
            url, headers={"User-Agent": "JevScout/0.1 (research metadata snapshot)", "Accept": "text/html"}
        )
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                html = response.read(2_000_000).decode("utf-8")
            paper = parse_page(arxiv_id, html)
            existing[arxiv_id] = paper
            destination.write_text(
                json.dumps(list(existing.values()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(arxiv_id, paper["title"], flush=True)
        except Exception as error:
            print(arxiv_id, type(error).__name__, str(error), flush=True)
    print(f"Collected {len(existing)} attributed papers", flush=True)


if __name__ == "__main__":
    main()
