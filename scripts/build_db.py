"""Stage 3 - rebuild outputs/build/facts.db from outputs/raw/ only. No network access.

The database holds facts as GitHub reported them; every derived metric is computed
later in aggregate.py from SQL. Re-running this is safe and fully replaces the file.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import ghclient as gh

SCHEMA = """
PRAGMA journal_mode = WAL;

DROP TABLE IF EXISTS meta;
DROP TABLE IF EXISTS repos;
DROP TABLE IF EXISTS pull_requests;
DROP TABLE IF EXISTS pending_review_requests;
DROP TABLE IF EXISTS review_request_events;
DROP TABLE IF EXISTS draft_events;
DROP TABLE IF EXISTS reviews;

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE repos (
  name TEXT PRIMARY KEY,
  is_archived INTEGER,
  is_private INTEGER,
  is_fork INTEGER,
  created_at TEXT,
  pushed_at TEXT,
  language TEXT,
  expected_created_in_window INTEGER,
  expected_updated_backfill INTEGER
);

CREATE TABLE pull_requests (
  repo TEXT,
  number INTEGER,
  title TEXT,
  url TEXT,
  state TEXT,
  is_draft INTEGER,
  created_at TEXT,
  updated_at TEXT,
  closed_at TEXT,
  merged_at TEXT,
  additions INTEGER,
  deletions INTEGER,
  changed_files INTEGER,
  author TEXT,
  author_type TEXT,
  merged_by TEXT,
  base_ref TEXT,
  window_source TEXT,
  PRIMARY KEY (repo, number)
);

CREATE TABLE pending_review_requests (
  repo TEXT,
  number INTEGER,
  reviewer TEXT,
  reviewer_type TEXT,
  PRIMARY KEY (repo, number, reviewer)
);

CREATE TABLE review_request_events (
  repo TEXT,
  number INTEGER,
  event_type TEXT,
  at TEXT,
  actor TEXT,
  reviewer TEXT,
  reviewer_type TEXT,
  UNIQUE (repo, number, event_type, at, reviewer)
);

CREATE TABLE draft_events (
  repo TEXT,
  number INTEGER,
  event_type TEXT,
  at TEXT,
  actor TEXT,
  UNIQUE (repo, number, event_type, at)
);

CREATE TABLE reviews (
  review_id TEXT PRIMARY KEY,
  repo TEXT,
  number INTEGER,
  author TEXT,
  author_type TEXT,
  state TEXT,
  submitted_at TEXT,
  body_len INTEGER,
  inline_comments INTEGER
);

CREATE INDEX idx_pr_created ON pull_requests(created_at);
CREATE INDEX idx_pr_author ON pull_requests(author);
CREATE INDEX idx_rre_reviewer ON review_request_events(reviewer, event_type);
CREATE INDEX idx_rev_author ON reviews(author);
CREATE INDEX idx_rev_pr ON reviews(repo, number);
"""


def reviewer_fields(node: dict | None) -> tuple[str | None, str | None]:
    if not node:
        return None, None
    kind = node.get("__typename")
    if kind == "Team":
        return node.get("slug"), "Team"
    return node.get("login"), kind or "User"


def insert_pr(conn: sqlite3.Connection, repo: str, node: dict, cutoff: str) -> None:
    author = node.get("author") or {}
    conn.execute(
        """INSERT OR REPLACE INTO pull_requests
           (repo, number, title, url, state, is_draft, created_at, updated_at, closed_at,
            merged_at, additions, deletions, changed_files, author, author_type, merged_by,
            base_ref, window_source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            repo,
            node["number"],
            node.get("title"),
            node.get("url"),
            node.get("state"),
            1 if node.get("isDraft") else 0,
            node.get("createdAt"),
            node.get("updatedAt"),
            node.get("closedAt"),
            node.get("mergedAt"),
            node.get("additions"),
            node.get("deletions"),
            node.get("changedFiles"),
            author.get("login"),
            author.get("__typename"),
            (node.get("mergedBy") or {}).get("login"),
            node.get("baseRefName"),
            "created" if (node.get("createdAt") or "") >= cutoff else "updated",
        ),
    )

    for req in ((node.get("reviewRequests") or {}).get("nodes") or []):
        login, kind = reviewer_fields(req.get("requestedReviewer"))
        if login:
            conn.execute(
                "INSERT OR REPLACE INTO pending_review_requests VALUES (?,?,?,?)",
                (repo, node["number"], login, kind),
            )

    insert_reviews(conn, repo, node["number"], (node.get("reviews") or {}).get("nodes") or [])
    insert_timeline(conn, repo, node["number"], (node.get("timelineItems") or {}).get("nodes") or [])


def insert_reviews(conn: sqlite3.Connection, repo: str, number: int, nodes: list[dict]) -> None:
    for rev in nodes:
        if not rev or not rev.get("id"):
            continue
        author = rev.get("author") or {}
        conn.execute(
            """INSERT OR REPLACE INTO reviews
               (review_id, repo, number, author, author_type, state, submitted_at, body_len, inline_comments)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                rev["id"],
                repo,
                number,
                author.get("login"),
                author.get("__typename"),
                rev.get("state"),
                rev.get("submittedAt"),
                len(rev.get("bodyText") or ""),
                (rev.get("comments") or {}).get("totalCount") or 0,
            ),
        )


def insert_timeline(conn: sqlite3.Connection, repo: str, number: int, nodes: list[dict]) -> None:
    for ev in nodes:
        if not ev:
            continue
        kind = ev.get("__typename")
        if kind in ("ReviewRequestedEvent", "ReviewRequestRemovedEvent"):
            login, rtype = reviewer_fields(ev.get("requestedReviewer"))
            conn.execute(
                "INSERT OR IGNORE INTO review_request_events VALUES (?,?,?,?,?,?,?)",
                (
                    repo,
                    number,
                    "requested" if kind == "ReviewRequestedEvent" else "removed",
                    ev.get("createdAt"),
                    (ev.get("actor") or {}).get("login"),
                    login,
                    rtype,
                ),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO draft_events VALUES (?,?,?,?,?)",
                (
                    repo,
                    number,
                    "ready_for_review" if kind == "ReadyForReviewEvent" else "convert_to_draft",
                    ev.get("createdAt"),
                    (ev.get("actor") or {}).get("login"),
                ),
            )


def main() -> None:
    cfg = gh.load_config()
    manifest = json.loads((gh.RAW / "meta" / "repos.json").read_text())
    cutoff = cfg["window_start"] + "T00:00:00Z"

    gh.BUILD.mkdir(parents=True, exist_ok=True)
    db_path = gh.BUILD / "facts.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    for repo in manifest["repos"]:
        conn.execute(
            "INSERT OR REPLACE INTO repos VALUES (?,?,?,?,?,?,?,?,?)",
            (
                repo["name"],
                1 if repo["isArchived"] else 0,
                1 if repo["isPrivate"] else 0,
                1 if repo["isFork"] else 0,
                repo["createdAt"],
                repo["pushedAt"],
                (repo.get("primaryLanguage") or {}).get("name"),
                repo["expected_created_in_window"],
                repo["expected_updated_backfill"],
            ),
        )

    pr_files = sorted(gh.RAW.glob("prs/*/created-*.json")) + sorted(gh.RAW.glob("prs/*/backfill-[0-9]*.json"))
    gh.log(f"loading {len(pr_files)} pull-request pages")
    for path in pr_files:
        body = json.loads(path.read_text())
        repo = body["_meta"]["repo"]
        repo_node = ((body.get("response") or {}).get("data") or {}).get("repository") or {}
        if "pullRequests" in repo_node:
            nodes = repo_node["pullRequests"]["nodes"]
            nodes = [n for n in nodes if n and (n.get("createdAt") or "") >= cutoff]
        else:
            nodes = [v for k, v in repo_node.items() if k.startswith("p") and isinstance(v, dict)]
        for node in nodes:
            insert_pr(conn, repo, node, cutoff)

    overflow = sorted(gh.RAW.glob("prs/*/pr-*-reviews-*.json")) + sorted(
        gh.RAW.glob("prs/*/pr-*-timelineItems-*.json")
    )
    gh.log(f"loading {len(overflow)} overflow pages")
    for path in overflow:
        body = json.loads(path.read_text())
        meta = body["_meta"]
        pr_node = (((body.get("response") or {}).get("data") or {}).get("repository") or {}).get("pullRequest") or {}
        conn_field = meta["field"]
        nodes = (pr_node.get(conn_field) or {}).get("nodes") or []
        if conn_field == "reviews":
            insert_reviews(conn, meta["repo"], meta["number"], nodes)
        else:
            insert_timeline(conn, meta["repo"], meta["number"], nodes)

    fetch_stats = gh.RAW / "meta" / "fetch_stats.json"
    conn.executemany(
        "INSERT OR REPLACE INTO meta VALUES (?,?)",
        [
            ("built_at", gh.utcnow()),
            ("org", cfg["org"]),
            ("window_start", cfg["window_start"]),
            ("window_end", cfg["window_end"]),
            ("default_reviewer", cfg["default_reviewer"]),
            ("include_archived", str(cfg["include_archived"])),
            ("raw_pr_pages", str(len(pr_files))),
            ("raw_overflow_pages", str(len(overflow))),
            ("fetch_stats", fetch_stats.read_text() if fetch_stats.exists() else ""),
        ],
    )
    conn.commit()

    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "repos",
            "pull_requests",
            "pending_review_requests",
            "review_request_events",
            "draft_events",
            "reviews",
        )
    }
    conn.close()
    gh.log(f"facts.db written: {counts}")


if __name__ == "__main__":
    main()
