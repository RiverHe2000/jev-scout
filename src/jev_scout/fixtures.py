"""Attributed public-paper demo fixtures; never an evaluation gold dataset."""

from __future__ import annotations

import json
import re
import sysconfig
from pathlib import Path


def data_directory() -> Path:
    """Resolve fixture files independently of the caller's working directory."""
    # Source checkout / editable install. A packaged build can ship data beneath
    # jev_scout/data; both locations are explicit, never relative to cwd.
    candidates = [
        Path(__file__).resolve().parent / "data",
        Path(__file__).resolve().parents[2] / "data",
        Path(sysconfig.get_path("data")) / "share" / "jev-scout" / "data",
    ]
    for candidate in candidates:
        if (candidate / "profiles.json").is_file() and (candidate / "papers.json").is_file():
            return candidate
    raise FileNotFoundError(
        "Bundled Jev Scout data is missing. Install with the included data files or run from the source checkout."
    )


def load_papers() -> list[dict]:
    """Load fresh dictionaries with recorded arXiv attribution and provenance."""
    papers = json.loads((data_directory() / "papers.json").read_text(encoding="utf-8"))
    seen = set()
    for paper in papers:
        key = (paper["arxiv_id"], paper["version"])
        if key in seen:
            raise ValueError(f"Duplicate fixture paper: {key}")
        seen.add(key)
        if not paper["abstract"] or not paper["authors"] or paper["source"] != "bundled":
            raise ValueError("Invalid attributed public-paper fixture")
        if not re.fullmatch(
            r"https://arxiv\.org/abs/(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})v\d+", paper["source_url"]
        ):
            raise ValueError("Invalid arXiv source attribution")
    return papers


def load_profiles() -> list[dict]:
    """Return three editable starter profiles with stable idempotency keys."""
    profiles = json.loads((data_directory() / "profiles.json").read_text(encoding="utf-8"))
    keys = [profile["fixture_key"] for profile in profiles]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate fixture profile keys")
    return profiles
