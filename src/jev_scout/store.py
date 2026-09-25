"""SQLite persistence with immutable inputs, optimistic edits and resumable jobs."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any
from uuid import uuid4


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


class ConflictError(Exception):
    """An optimistic write no longer matches the current version."""


class MissingError(Exception):
    """A requested persisted entity does not exist."""


class JobCancelledError(Exception):
    """A terminal job is no longer allowed to publish in-flight work."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT OR IGNORE INTO metadata VALUES ('schema_version','1');
CREATE TABLE IF NOT EXISTS profiles (
 id TEXT PRIMARY KEY, fixture_key TEXT UNIQUE, payload TEXT NOT NULL,
 version INTEGER NOT NULL, archived INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_versions (
 profile_id TEXT NOT NULL REFERENCES profiles(id), version INTEGER NOT NULL,
 payload TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(profile_id,version)
);
CREATE TABLE IF NOT EXISTS papers (
 id TEXT PRIMARY KEY,arxiv_id TEXT UNIQUE NOT NULL,current_version_id TEXT,created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_versions (
 id TEXT PRIMARY KEY,paper_id TEXT NOT NULL REFERENCES papers(id),version INTEGER NOT NULL,
 content_hash TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(paper_id,version,content_hash)
);
CREATE TABLE IF NOT EXISTS decisions (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,
 paper_id TEXT NOT NULL REFERENCES papers(id),paper_version_id TEXT NOT NULL REFERENCES paper_versions(id),
 profile_id TEXT NOT NULL REFERENCES profiles(id),profile_version INTEGER NOT NULL,
 mode TEXT NOT NULL,cache_key TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,stale INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS decision_lookup ON decisions(profile_id,paper_id,seq DESC);
CREATE INDEX IF NOT EXISTS decision_cache ON decisions(cache_key,seq DESC);
CREATE TABLE IF NOT EXISTS selected_decisions (
 profile_id TEXT NOT NULL REFERENCES profiles(id),paper_id TEXT NOT NULL REFERENCES papers(id),
 decision_id TEXT NOT NULL REFERENCES decisions(id),PRIMARY KEY(profile_id,paper_id)
);
CREATE TABLE IF NOT EXISTS reading (
 paper_id TEXT NOT NULL REFERENCES papers(id),profile_id TEXT NOT NULL REFERENCES profiles(id),
 saved INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'unread',note TEXT NOT NULL DEFAULT '',
 feedback TEXT,updated_at TEXT NOT NULL,PRIMARY KEY(paper_id,profile_id)
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY,kind TEXT NOT NULL,profile_id TEXT NOT NULL REFERENCES profiles(id),mode TEXT NOT NULL,
 status TEXT NOT NULL,payload TEXT NOT NULL,total INTEGER NOT NULL DEFAULT 0,
 completed INTEGER NOT NULL DEFAULT 0,failed INTEGER NOT NULL DEFAULT 0,message TEXT NOT NULL DEFAULT '',error TEXT,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,finished_at TEXT
);
CREATE INDEX IF NOT EXISTS job_queue ON jobs(status,created_at);
CREATE TABLE IF NOT EXISTS job_decisions (
 job_id TEXT NOT NULL REFERENCES jobs(id),decision_id TEXT NOT NULL REFERENCES decisions(id),
 PRIMARY KEY(job_id,decision_id)
);
CREATE TABLE IF NOT EXISTS activity (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,profile_id TEXT,
 paper_id TEXT,type TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS annotations (
 profile_id TEXT NOT NULL REFERENCES profiles(id),paper_id TEXT NOT NULL REFERENCES papers(id),
 relevance INTEGER NOT NULL,split TEXT NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL,
 profile_version INTEGER,paper_version_id TEXT,content_hash TEXT,
 PRIMARY KEY(profile_id,paper_id)
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)
            annotation_columns = {row["name"] for row in con.execute("PRAGMA table_info(annotations)")}
            for column, kind in {
                "profile_version": "INTEGER",
                "paper_version_id": "TEXT",
                "content_hash": "TEXT",
            }.items():
                if column not in annotation_columns:
                    con.execute(f"ALTER TABLE annotations ADD COLUMN {column} {kind}")
            con.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=20)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=20000")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _activity(con, kind: str, detail: str, profile_id: str | None = None, paper_id: str | None = None):
        con.execute(
            "INSERT INTO activity(id,profile_id,paper_id,type,detail,created_at) VALUES (?,?,?,?,?,?)",
            (str(uuid4()), profile_id, paper_id, kind, detail[:2000], now()),
        )

    @staticmethod
    def _profile(row) -> dict:
        if row is None:
            raise MissingError("Research profile not found.")
        return {
            **json.loads(row["payload"]),
            "id": row["id"],
            "version": row["version"],
            "archived": bool(row["archived"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def profiles(self, include_archived: bool = False) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM profiles "
                + ("" if include_archived else "WHERE archived=0 ")
                + "ORDER BY created_at"
            ).fetchall()
            return [self._profile(row) for row in rows]

    def profile(self, profile_id: str) -> dict:
        with self.connect() as con:
            return self._profile(con.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone())

    def create_profile(self, payload: dict, fixture_key: str | None = None) -> dict:
        with self.connect() as con:
            if fixture_key:
                existing = con.execute(
                    "SELECT * FROM profiles WHERE fixture_key=?", (fixture_key,)
                ).fetchone()
                if existing:
                    return self._profile(existing)
            profile_id, stamp = str(uuid4()), now()
            con.execute(
                "INSERT INTO profiles VALUES (?,?,?,1,0,?,?)",
                (profile_id, fixture_key, encode(payload), stamp, stamp),
            )
            con.execute("INSERT INTO profile_versions VALUES (?,1,?,?)", (profile_id, encode(payload), stamp))
            self._activity(con, "profile_created", f"Created research card: {payload['name']}", profile_id)
        return self.profile(profile_id)

    def update_profile(self, profile_id: str, payload: dict, expected_version: int) -> dict:
        stamp = now()
        with self.connect() as con:
            cur = con.execute(
                "UPDATE profiles SET payload=?,version=version+1,updated_at=? WHERE id=? AND version=?",
                (encode(payload), stamp, profile_id, expected_version),
            )
            if cur.rowcount != 1:
                if not con.execute("SELECT 1 FROM profiles WHERE id=?", (profile_id,)).fetchone():
                    raise MissingError("Research profile not found.")
                raise ConflictError("This research card changed in another window. Reload it before saving.")
            con.execute(
                "INSERT INTO profile_versions VALUES (?,?,?,?)",
                (profile_id, expected_version + 1, encode(payload), stamp),
            )
            self._activity(
                con,
                "profile_updated",
                f"Research card updated to version {expected_version + 1}; previous decisions require reevaluation.",
                profile_id,
            )
        return self.profile(profile_id)

    def archive_profile(self, profile_id: str, archived: bool):
        with self.connect() as con:
            if (
                con.execute(
                    "UPDATE profiles SET archived=?,updated_at=? WHERE id=?",
                    (int(archived), now(), profile_id),
                ).rowcount
                != 1
            ):
                raise MissingError("Research profile not found.")
            self._activity(
                con,
                "profile_archived" if archived else "profile_restored",
                "Research card archived." if archived else "Research card restored.",
                profile_id,
            )

    @staticmethod
    def _paper(row) -> dict:
        if row is None:
            raise MissingError("Paper not found.")
        payload = json.loads(row["payload"])
        return {
            **payload,
            "id": row["paper_id"],
            "version": row["version"],
            "content_hash": row["content_hash"],
            "created_at": row["created_at"],
            "_version_id": row["id"],
        }

    def ingest_paper(self, payload: dict) -> dict:
        from .arxiv import normalize_arxiv_id

        payload = {
            key: value
            for key, value in payload.items()
            if key not in {"id", "content_hash", "created_at", "_version_id"}
        }
        for key in ("arxiv_id", "title", "abstract", "authors", "version", "published", "updated"):
            if key not in payload:
                raise ValueError(f"Paper metadata is missing {key}.")
        identifier = normalize_arxiv_id(payload["arxiv_id"])
        if identifier != payload["arxiv_id"] or re.search(r"v\d+$", identifier):
            raise ValueError("Paper metadata requires a canonical arXiv ID without a version suffix.")
        if type(payload["version"]) is not int or not 1 <= payload["version"] <= 99999:
            raise ValueError("Paper version must be a positive integer.")
        if not isinstance(payload["abstract"], str) or not 1 <= len(payload["abstract"]) <= 32000:
            raise ValueError("Paper abstract must be nonempty and bounded.")
        if not isinstance(payload["title"], str) or not 1 <= len(payload["title"]) <= 2000:
            raise ValueError("Paper title must be nonempty and bounded.")
        if (
            not isinstance(payload["authors"], list)
            or not payload["authors"]
            or len(payload["authors"]) > 5000
            or any(
                not isinstance(author, str) or not author.strip() or len(author) > 300
                for author in payload["authors"]
            )
        ):
            raise ValueError("Paper authors must be a bounded list of nonempty names.")
        categories = payload.get("categories", [])
        if (
            not isinstance(categories, list)
            or len(categories) > 100
            or any(not isinstance(category, str) or len(category) > 100 for category in categories)
        ):
            raise ValueError("Paper categories must be a bounded list of text values.")
        for field in ("published", "updated"):
            try:
                stamp = datetime.fromisoformat(payload[field].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=UTC)
                payload[field] = stamp.astimezone(UTC).isoformat()
            except (ValueError, AttributeError, TypeError):
                raise ValueError("Paper dates must be valid ISO timestamps.") from None
        payload["source_url"] = f"https://arxiv.org/abs/{identifier}v{payload['version']}"
        payload["pdf_url"] = f"https://arxiv.org/pdf/{identifier}v{payload['version']}"
        fingerprint = digest(
            {
                key: payload.get(key)
                for key in (
                    "arxiv_id",
                    "version",
                    "title",
                    "abstract",
                    "authors",
                    "categories",
                    "published",
                    "updated",
                )
            }
        )
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            paper_row = con.execute(
                "SELECT * FROM papers WHERE arxiv_id=?", (payload["arxiv_id"],)
            ).fetchone()
            stamp = now()
            if not paper_row:
                paper_id = str(uuid4())
                con.execute("INSERT INTO papers VALUES (?,?,NULL,?)", (paper_id, payload["arxiv_id"], stamp))
                current = None
            else:
                paper_id = paper_row["id"]
                current = con.execute(
                    "SELECT * FROM paper_versions WHERE id=?", (paper_row["current_version_id"],)
                ).fetchone()
            existing = con.execute(
                "SELECT * FROM paper_versions WHERE paper_id=? AND version=? AND content_hash=?",
                (paper_id, payload["version"], fingerprint),
            ).fetchone()
            if existing:
                # Prefer newly verified live provenance without changing immutable semantic content.
                if (
                    payload.get("source") == "arxiv"
                    and json.loads(existing["payload"]).get("source") == "bundled"
                ):
                    con.execute(
                        "UPDATE paper_versions SET payload=? WHERE id=?", (encode(payload), existing["id"])
                    )
                version_id = existing["id"]
            else:
                version_id = str(uuid4())
                con.execute(
                    "INSERT INTO paper_versions VALUES (?,?,?,?,?,?)",
                    (version_id, paper_id, payload["version"], fingerprint, encode(payload), stamp),
                )
            current_data = json.loads(current["payload"]) if current else {}
            if (
                current is None
                or payload["version"] > current["version"]
                or (
                    payload["version"] == current["version"]
                    and payload["updated"] >= current_data.get("updated", "")
                    and (existing is None or version_id == current["id"])
                    and not (current_data.get("source") == "arxiv" and payload.get("source") == "bundled")
                )
            ):
                con.execute("UPDATE papers SET current_version_id=? WHERE id=?", (version_id, paper_id))
        return self.paper(paper_id)

    def paper(self, paper_id: str) -> dict:
        with self.connect() as con:
            row = con.execute(
                "SELECT v.* FROM papers p JOIN paper_versions v ON p.current_version_id=v.id WHERE p.id=?",
                (paper_id,),
            ).fetchone()
            return self._paper(row)

    def papers(self, paper_ids: list[str] | None = None) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT v.* FROM papers p JOIN paper_versions v ON p.current_version_id=v.id ORDER BY p.created_at"
            ).fetchall()
            requested = set(paper_ids) if paper_ids is not None else None
            return [self._paper(row) for row in rows if requested is None or row["paper_id"] in requested]

    def paper_versions(self, paper_id: str) -> list[dict]:
        with self.connect() as con:
            return [
                self._paper(row)
                for row in con.execute(
                    "SELECT * FROM paper_versions WHERE paper_id=? ORDER BY version DESC,created_at DESC",
                    (paper_id,),
                ).fetchall()
            ]

    @staticmethod
    def _decision(
        row, current_profile_version: int | None = None, current_paper_version_id: str | None = None
    ) -> dict | None:
        if row is None:
            return None
        payload = json.loads(row["payload"])
        stale = (
            bool(row["stale"])
            or (current_profile_version is not None and row["profile_version"] != current_profile_version)
            or (current_paper_version_id is not None and row["paper_version_id"] != current_paper_version_id)
        )
        return {
            **payload,
            "id": row["id"],
            "paper_id": row["paper_id"],
            "profile_id": row["profile_id"],
            "profile_version": row["profile_version"],
            "mode": row["mode"],
            "created_at": row["created_at"],
            "cache_hit": False,
            "stale": stale,
        }

    def cached_decision(self, cache_key: str) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT d.* FROM decisions d JOIN profiles p ON p.id=d.profile_id JOIN papers a ON a.id=d.paper_id "
                "WHERE d.cache_key=? AND d.stale=0 AND p.version=d.profile_version AND a.current_version_id=d.paper_version_id "
                "ORDER BY d.seq DESC LIMIT 1",
                (cache_key,),
            ).fetchone()
            return self._decision(row)

    @staticmethod
    def _require_active_job(con, job_id: str | None):
        if job_id is not None:
            row = con.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["status"] != "running":
                raise JobCancelledError("The job stopped before this result could be published.")

    @staticmethod
    def _select_decision(con, profile_id: str, paper_id: str, decision_id: str):
        con.execute(
            "INSERT INTO selected_decisions VALUES (?,?,?) ON CONFLICT(profile_id,paper_id) DO UPDATE SET decision_id=excluded.decision_id",
            (profile_id, paper_id, decision_id),
        )

    def completed_job_decision(self, job_id: str, cache_key: str) -> dict | None:
        with self.connect() as con:
            job = self._job(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone(), True)
            retry_from = job["payload"].get("_retry_from", job_id)
            row = con.execute(
                "SELECT d.* FROM decisions d JOIN job_decisions j ON j.decision_id=d.id JOIN profiles p ON p.id=d.profile_id JOIN papers a ON a.id=d.paper_id WHERE j.job_id IN (?,?) AND d.cache_key=? AND d.stale=0 AND d.profile_version=p.version AND d.paper_version_id=a.current_version_id ORDER BY d.seq DESC LIMIT 1",
                (job_id, retry_from, cache_key),
            ).fetchone()
            return self._decision(row)

    def activate_cached_decision(self, decision_id: str, *, job_id: str | None = None) -> dict | None:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._require_active_job(con, job_id)
            row = con.execute(
                "SELECT d.* FROM decisions d JOIN profiles p ON p.id=d.profile_id JOIN papers a ON a.id=d.paper_id WHERE d.id=? AND d.stale=0 AND d.profile_version=p.version AND d.paper_version_id=a.current_version_id",
                (decision_id,),
            ).fetchone()
            if row is None:
                return None
            self._select_decision(con, row["profile_id"], row["paper_id"], decision_id)
            if job_id is not None:
                con.execute("INSERT OR IGNORE INTO job_decisions VALUES (?,?)", (job_id, decision_id))
            return {**self._decision(row), "cache_hit": True}

    def save_decision(
        self, paper: dict, profile: dict, payload: dict, cache_key: str, *, job_id: str | None = None
    ) -> dict:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._require_active_job(con, job_id)
            current_profile = con.execute(
                "SELECT version FROM profiles WHERE id=?", (profile["id"],)
            ).fetchone()
            current_paper = con.execute(
                "SELECT current_version_id FROM papers WHERE id=?", (paper["id"],)
            ).fetchone()
            stale = (
                current_profile["version"] != profile["version"]
                or current_paper["current_version_id"] != paper["_version_id"]
            )
            decision_id, stamp = str(uuid4()), now()
            payload = {**payload, "paper_version": paper["version"]}
            con.execute(
                "INSERT INTO decisions(id,paper_id,paper_version_id,profile_id,profile_version,mode,cache_key,payload,created_at,stale) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    decision_id,
                    paper["id"],
                    paper["_version_id"],
                    profile["id"],
                    profile["version"],
                    payload["mode"],
                    cache_key,
                    encode(payload),
                    stamp,
                    int(stale),
                ),
            )
            if not stale:
                self._select_decision(con, profile["id"], paper["id"], decision_id)
            if job_id is not None:
                con.execute("INSERT OR IGNORE INTO job_decisions VALUES (?,?)", (job_id, decision_id))
            self._activity(
                con,
                "decision_stale" if stale else "paper_evaluated",
                f"{payload['mode']}: {paper['title']} → {payload['route']}"
                + (" (superseded input)" if stale else ""),
                profile["id"],
                paper["id"],
            )
            row = con.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
            return self._decision(row)

    def decision_history(self, paper_id: str, profile_id: str) -> list[dict]:
        profile, paper = self.profile(profile_id), self.paper(paper_id)
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM decisions WHERE paper_id=? AND profile_id=? ORDER BY seq DESC LIMIT 30",
                (paper_id, profile_id),
            ).fetchall()
            return [self._decision(row, profile["version"], paper["_version_id"]) for row in rows]

    @staticmethod
    def _reading(row) -> dict:
        return (
            {
                "saved": bool(row["saved"]),
                "status": row["status"],
                "note": row["note"],
                "feedback": row["feedback"],
            }
            if row
            else {"saved": False, "status": "unread", "note": "", "feedback": None}
        )

    def update_reading(self, paper_id: str, profile_id: str, changes: dict) -> dict:
        self.paper(paper_id)
        self.profile(profile_id)
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            previous = self._reading(
                con.execute(
                    "SELECT * FROM reading WHERE paper_id=? AND profile_id=?", (paper_id, profile_id)
                ).fetchone()
            )
            merged = {**previous, **{key: value for key, value in changes.items() if key in previous}}
            if any(merged[key] is None for key in ("saved", "status", "note")):
                raise ValueError("Saved, status, and note cannot be null.")
            con.execute(
                "INSERT INTO reading VALUES (?,?,?,?,?,?,?) ON CONFLICT(paper_id,profile_id) DO UPDATE SET saved=excluded.saved,status=excluded.status,note=excluded.note,feedback=excluded.feedback,updated_at=excluded.updated_at",
                (
                    paper_id,
                    profile_id,
                    int(merged["saved"]),
                    merged["status"],
                    merged["note"],
                    merged["feedback"],
                    now(),
                ),
            )
            for key, value in changes.items():
                if key in previous and previous[key] != value:
                    detail = (
                        "Updated private reading note."
                        if key == "note"
                        else f"{key.replace('_', ' ').capitalize()}: {value if value is not None else 'cleared'}."
                    )
                    self._activity(
                        con,
                        "paper_saved" if key == "saved" and value else f"reading_{key}",
                        detail,
                        profile_id,
                        paper_id,
                    )
            return merged

    def entries(self, profile_id: str) -> list[dict]:
        profile = self.profile(profile_id)
        papers = self.papers()
        with self.connect() as con:
            results = []
            for paper in papers:
                row = con.execute(
                    "SELECT d.* FROM decisions d LEFT JOIN selected_decisions s ON s.profile_id=d.profile_id AND s.paper_id=d.paper_id WHERE d.profile_id=? AND d.paper_id=? ORDER BY (d.profile_version=? AND d.paper_version_id=? AND d.stale=0) DESC,(d.id=s.decision_id) DESC,d.seq DESC LIMIT 1",
                    (profile_id, paper["id"], profile["version"], paper["_version_id"]),
                ).fetchone()
                decision = self._decision(row, profile["version"], paper["_version_id"])
                reading = self._reading(
                    con.execute(
                        "SELECT * FROM reading WHERE profile_id=? AND paper_id=?", (profile_id, paper["id"])
                    ).fetchone()
                )
                results.append({**paper, "decision": decision, "reading": reading})
            return results

    @staticmethod
    def effective_route(entry: dict) -> str:
        decision = entry["decision"]
        return "review" if not decision or decision["stale"] else decision["route"]

    def list_papers(
        self,
        profile_id: str,
        *,
        route: str = "all",
        saved: bool = False,
        status: str = "all",
        q: str = "",
        sort: str = "priority",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        entries = self.entries(profile_id)
        counts = {key: 0 for key in ("all", "read", "skim", "review", "later", "saved", "unread")}
        for entry in entries:
            counts["all"] += 1
            counts[self.effective_route(entry)] += 1
            counts["saved"] += int(entry["reading"]["saved"])
            counts["unread"] += int(entry["reading"]["status"] == "unread")
        query = q.casefold().strip()
        filtered = [
            entry
            for entry in entries
            if (route == "all" or self.effective_route(entry) == route)
            and (not saved or entry["reading"]["saved"])
            and (status == "all" or entry["reading"]["status"] == status)
            and (
                not query
                or query
                in (entry["title"] + " " + entry["abstract"] + " " + " ".join(entry["authors"])).casefold()
            )
        ]
        if sort == "newest":
            filtered.sort(key=lambda item: (item["published"], item["id"]), reverse=True)
        else:
            filtered.sort(
                key=lambda item: (
                    float((item["decision"] or {}).get("rank_score", -1)),
                    item["published"],
                    item["id"],
                ),
                reverse=True,
            )
        return {
            "items": filtered[offset : offset + limit],
            "total": len(filtered),
            "counts": counts,
            "profile_version": self.profile(profile_id)["version"],
        }

    def create_job(self, kind: str, payload: dict) -> dict:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            profile = self._profile(
                con.execute("SELECT * FROM profiles WHERE id=?", (payload["profile_id"],)).fetchone()
            )
            if profile["archived"]:
                raise ConflictError("Restore this research card before processing papers.")
            payload = {**payload, "_profile_version": profile["version"]}
            if kind == "evaluate":
                paper_ids = payload.get("paper_ids")
                if paper_ids is not None:
                    payload["paper_ids"] = sorted(set(paper_ids))
                versions = con.execute("SELECT id,current_version_id FROM papers ORDER BY id").fetchall()
                payload["_paper_versions"] = [
                    [row["id"], row["current_version_id"]]
                    for row in versions
                    if paper_ids is None or row["id"] in paper_ids
                ]
            work_payload = {
                key: value
                for key, value in payload.items()
                if key not in {"_work_key", "_retry_from", "_imported_paper_ids"}
            }
            payload["_work_key"] = digest(work_payload)
            serialized = encode(payload)
            candidates = con.execute(
                "SELECT * FROM jobs WHERE kind=? AND status IN ('queued','running') ORDER BY created_at DESC",
                (kind,),
            ).fetchall()
            for candidate in candidates:
                if json.loads(candidate["payload"]).get("_work_key") == payload["_work_key"]:
                    return self._job(candidate)
            job_id, stamp = str(uuid4()), now()
            con.execute(
                "INSERT INTO jobs(id,kind,profile_id,mode,status,payload,created_at,updated_at,message) VALUES (?,?,?,?,'queued',?,?,?,'Waiting to start.')",
                (job_id, kind, payload["profile_id"], payload["mode"], serialized, stamp, stamp),
            )
            self._activity(
                con, "job_queued", f"Queued {kind} using {payload['mode']}.", payload["profile_id"]
            )
        return self.job(job_id)

    @staticmethod
    def _job(row, internal: bool = False) -> dict:
        if not row:
            raise MissingError("Job not found.")
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        if not internal:
            result.pop("payload")
        return result

    def job(self, job_id: str, internal: bool = False) -> dict:
        with self.connect() as con:
            return self._job(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone(), internal)

    def jobs(self) -> list[dict]:
        with self.connect() as con:
            return [
                self._job(row)
                for row in con.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 30").fetchall()
            ]

    def set_imported_papers(self, job_id: str, paper_ids: list[str]):
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._require_active_job(con, job_id)
            row = con.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            payload = {**json.loads(row["payload"]), "_imported_paper_ids": paper_ids}
            con.execute("UPDATE jobs SET payload=?,updated_at=? WHERE id=?", (encode(payload), now(), job_id))

    def recover_jobs(self):
        with self.connect() as con:
            con.execute(
                "UPDATE jobs SET status='queued',message='Resuming after server restart.',completed=0,failed=0,updated_at=? WHERE status='running'",
                (now(),),
            )

    def next_job(self) -> dict | None:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            con.execute(
                "UPDATE jobs SET status='running',message='Starting.',updated_at=? WHERE id=?",
                (now(), row["id"]),
            )
            result = self._job(row, True)
            result["status"] = "running"
            return result

    def job_update(self, job_id: str, **fields):
        allowed = {"status", "total", "completed", "failed", "message", "error", "finished_at"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("Unsupported job update.")
        fields["updated_at"] = now()
        with self.connect() as con:
            con.execute(
                "UPDATE jobs SET "
                + ",".join(f"{key}=?" for key in fields)
                + " WHERE id=? AND status IN ('queued','running')",
                (*fields.values(), job_id),
            )

    def cancel_job(self, job_id: str) -> dict:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise MissingError("Job not found.")
            if row["status"] in {"queued", "running"}:
                con.execute(
                    "UPDATE jobs SET status='cancelled',message='Cancelled. Completed results are retained.',updated_at=?,finished_at=? WHERE id=? AND status IN ('queued','running')",
                    (now(), now(), job_id),
                )
                self._activity(
                    con,
                    "job_cancelled",
                    "Stopped a processing job; existing results retained.",
                    row["profile_id"],
                )
        return self.job(job_id)

    def activity(
        self, profile_id: str | None = None, paper_id: str | None = None, limit: int = 100
    ) -> list[dict]:
        conditions, values = [], []
        if profile_id:
            conditions.append("profile_id=?")
            values.append(profile_id)
        if paper_id:
            conditions.append("paper_id=?")
            values.append(paper_id)
        with self.connect() as con:
            rows = con.execute(
                "SELECT id,type,detail,created_at FROM activity "
                + ("WHERE " + " AND ".join(conditions) if conditions else "")
                + " ORDER BY seq DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def stats(self, profile_id: str) -> dict:
        entries = self.entries(profile_id)
        with self.connect() as con:
            rows = con.execute(
                "SELECT d.*,p.version AS current_profile_version,a.current_version_id FROM decisions d JOIN profiles p ON p.id=d.profile_id JOIN papers a ON a.id=d.paper_id WHERE d.profile_id=? ORDER BY d.seq DESC",
                (profile_id,),
            ).fetchall()
            decisions = [
                self._decision(row, row["current_profile_version"], row["current_version_id"]) for row in rows
            ]
            saved_events = con.execute(
                "SELECT created_at FROM activity WHERE profile_id=? AND type='paper_saved'", (profile_id,)
            ).fetchall()
        timings = sorted(
            float(item["latency_ms"]) for item in decisions if item.get("latency_ms") is not None
        )
        costs_known = all(item.get("cost_usd") is not None for item in decisions)
        daily = {
            (datetime.now(UTC).date() - timedelta(days=day)).isoformat(): {"evaluated": 0, "saved": 0}
            for day in reversed(range(14))
        }
        for item in decisions:
            if item["created_at"][:10] in daily:
                daily[item["created_at"][:10]]["evaluated"] += 1
        for row in saved_events:
            if row["created_at"][:10] in daily:
                daily[row["created_at"][:10]]["saved"] += 1
        routes = {
            key: sum(self.effective_route(item) == key for item in entries)
            for key in ("read", "skim", "review", "later")
        }
        return {
            "papers": len(entries),
            "decisions": len(decisions),
            "saved": sum(item["reading"]["saved"] for item in entries),
            "review": routes["review"],
            "completed_reads": sum(item["reading"]["status"] == "done" for item in entries),
            "feedback_count": sum(item["reading"]["feedback"] is not None for item in entries),
            "live_decisions": sum(item["mode"] == "jev" for item in decisions),
            "baseline_decisions": sum(item["mode"] == "baseline" for item in decisions),
            "llm_decisions": sum(item["mode"] == "llm" for item in decisions),
            "input_tokens": sum(item.get("input_tokens") or 0 for item in decisions),
            "estimated_cost_usd": sum(item["cost_usd"] for item in decisions) if costs_known else None,
            "latency_p50_ms": median(timings) if timings else None,
            "latency_p95_ms": timings[min(len(timings) - 1, int((len(timings) - 1) * 0.95))]
            if timings
            else None,
            "daily_activity": [{"date": date, **counts} for date, counts in daily.items()],
            "route_counts": routes,
            "recent_runs": decisions[:10],
            "calibration_status": "not_calibrated",
        }

    def annotate(self, payload: dict):
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            profile = self._profile(
                con.execute("SELECT * FROM profiles WHERE id=?", (payload["profile_id"],)).fetchone()
            )
            paper = self._paper(
                con.execute(
                    "SELECT v.* FROM papers p JOIN paper_versions v ON v.id=p.current_version_id WHERE p.id=?",
                    (payload["paper_id"],),
                ).fetchone()
            )
            con.execute(
                "INSERT INTO annotations(profile_id,paper_id,relevance,split,note,created_at,profile_version,paper_version_id,content_hash) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(profile_id,paper_id) DO UPDATE SET relevance=excluded.relevance,split=excluded.split,note=excluded.note,created_at=excluded.created_at,profile_version=excluded.profile_version,paper_version_id=excluded.paper_version_id,content_hash=excluded.content_hash",
                (
                    payload["profile_id"],
                    payload["paper_id"],
                    payload["relevance"],
                    payload["split"],
                    payload["note"],
                    now(),
                    profile["version"],
                    paper["_version_id"],
                    paper["content_hash"],
                ),
            )

    def annotations(self) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT a.*,v.version AS paper_version, (a.profile_version IS NULL OR a.paper_version_id IS NULL OR a.profile_version!=p.version OR a.paper_version_id!=s.current_version_id) AS stale FROM annotations a JOIN profiles p ON p.id=a.profile_id JOIN papers s ON s.id=a.paper_id LEFT JOIN paper_versions v ON v.id=a.paper_version_id ORDER BY a.created_at"
            ).fetchall()
            return [{**dict(row), "stale": bool(row["stale"])} for row in rows]

    def backup(self, destination: Path):
        if destination.resolve() == self.path.resolve():
            raise ValueError("The backup destination must differ from the active database.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)
