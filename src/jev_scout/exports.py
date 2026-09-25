"""Readable, escaped exports from saved records; never generate bibliographic facts."""

from __future__ import annotations

import json
import re


def bibtex_escape(value: str) -> str:
    substitutions = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "&": r"\&",
        "%": r"\%",
        "_": r"\_",
        "#": r"\#",
        "$": r"\$",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(substitutions.get(char, char) for char in value).replace("\r", " ").replace("\n", " ")


def markdown_escape(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>#!|()+.\-])", r"\\\1", value).replace("\r", "")


def source_url(paper: dict) -> str:
    from .arxiv import normalize_arxiv_id

    identifier = normalize_arxiv_id(paper["arxiv_id"])
    if re.search(r"v\d+$", identifier) or type(paper["version"]) is not int or paper["version"] < 1:
        raise ValueError("Export requires an unversioned arXiv ID and a positive version.")
    return f"https://arxiv.org/abs/{identifier}v{paper['version']}"


def export_entries(entries: list[dict], profile: dict, format: str) -> tuple[str, str, str]:
    if format == "bibtex":
        records = []
        for paper in entries:
            key = "arxiv" + re.sub(r"[^a-zA-Z0-9]", "", paper["arxiv_id"])
            authors = " and ".join(bibtex_escape(author) for author in paper["authors"])
            fields = {
                "title": bibtex_escape(paper["title"]),
                "author": authors,
                "year": bibtex_escape(paper["published"][:4]),
                "eprint": bibtex_escape(paper["arxiv_id"]),
                "archivePrefix": "arXiv",
                "primaryClass": bibtex_escape((paper.get("categories") or [""])[0]),
                "url": bibtex_escape(source_url(paper)),
                "note": f"arXiv version {paper['version']}",
            }
            records.append(
                "@misc{"
                + key
                + ",\n"
                + ",\n".join(f"  {name} = {{{value}}}" for name, value in fields.items())
                + "\n}"
            )
        return "\n\n".join(records) + "\n", "application/x-bibtex; charset=utf-8", "reading-list.bib"
    if format == "markdown":
        lines = [f"# {markdown_escape(profile['name'])}", "", markdown_escape(profile["question"]), ""]
        for paper in entries:
            lines += [
                f"## {markdown_escape(paper['title'])}",
                "",
                f"{markdown_escape(', '.join(paper['authors']))} · {paper['published'][:10]} · v{paper['version']}",
                "",
                f"[arXiv source]({source_url(paper)})",
                "",
            ]
            decision = paper.get("decision")
            if decision:
                lines += [
                    f"Triage: {decision['route']} · Method: {decision['mode']} · Model: {markdown_escape(decision['model'])}"
                    + (" · Stale: reevaluation required" if decision["stale"] else ""),
                    "",
                    markdown_escape(decision.get("reason", "")),
                    "",
                ]
                for sentence in decision.get("sentences", []):
                    if sentence["id"] in decision.get("evidence_ids", []):
                        lines += ["> " + markdown_escape(sentence["text"]).replace("\n", "\n> "), ""]
            if paper["reading"]["note"]:
                lines += ["Notes:", "", markdown_escape(paper["reading"]["note"]), ""]
        lines += [
            "---",
            "Triage is a recommendation based on the available abstract, not a review of the full paper.",
            "",
        ]
        return "\n".join(lines), "text/markdown; charset=utf-8", "reading-list.md"
    if format == "json":
        clean = [{key: value for key, value in paper.items() if not key.startswith("_")} for paper in entries]
        return (
            json.dumps({"profile": profile, "papers": clean}, ensure_ascii=False, indent=2),
            "application/json",
            "reading-list.json",
        )
    raise ValueError("Unsupported export format.")
