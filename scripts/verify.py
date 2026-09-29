"""Stage 5 - prove the database matches what GitHub reports, and that nothing was invented.

Checks, each written to build/verification.json with pass/fail:
  A  per-repo PR count vs the search API's issueCount
  B  backfill PR count vs its own search issueCount
  C  every page that reported hasNextPage has the follow-up page on disk
  D  no PR is filed under the wrong window basis
  E  no review or request event points at a PR that is not in the table
  F  the target reviewer's review total against a search query built independently
  G  timelineItems.totalCount vs the filtered node count (documents the known trap)
  H  additions/deletions/changedFiles in the database recomputed from the raw responses
  I  missing change size stays NULL rather than 0 (documents how churn handles gaps)

Exit status is non-zero when any hard check fails.
"""

from __future__ import annotations

import json
import sqlite3
import sys

import ghclient as gh

SEARCH_COUNT = """
query($q:String!) {
  rateLimit { cost remaining resetAt }
  search(query:$q, type: ISSUE, first: 1) { issueCount }
}
"""


def search_count(q: str) -> int:
    payload = gh.graphql(SEARCH_COUNT, {"q": q})
    return payload["data"]["search"]["issueCount"]


def main() -> None:
    cfg = gh.load_config()
    conn = sqlite3.connect(gh.BUILD / "facts.db")
    cutoff = cfg["window_start"] + "T00:00:00Z"
    results: list[dict] = []
    hard_fail = False

    def record(check: str, ok: bool, detail, hard: bool = True) -> None:
        nonlocal hard_fail
        results.append({"check": check, "ok": ok, "hard": hard, "detail": detail})
        if hard and not ok:
            hard_fail = True

    # A / B - counts against the search API reference
    mismatches_created, mismatches_backfill = [], []
    for name, expected_created, expected_backfill in conn.execute(
        "SELECT name, expected_created_in_window, expected_updated_backfill FROM repos"
    ):
        got_created = conn.execute(
            "SELECT COUNT(*) FROM pull_requests WHERE repo=? AND window_source='created'", (name,)
        ).fetchone()[0]
        got_backfill = conn.execute(
            "SELECT COUNT(*) FROM pull_requests WHERE repo=? AND window_source='updated'", (name,)
        ).fetchone()[0]
        if got_created != expected_created:
            mismatches_created.append(
                {"repo": name, "expected": expected_created, "in_db": got_created, "delta": got_created - expected_created}
            )
        if got_backfill != expected_backfill:
            mismatches_backfill.append(
                {"repo": name, "expected": expected_backfill, "in_db": got_backfill, "delta": got_backfill - expected_backfill}
            )
    record("A: per-repo created PR count == search issueCount", not mismatches_created, mismatches_created)
    record("B: per-repo backfill PR count == search issueCount", not mismatches_backfill, mismatches_backfill)

    # C - unresolved pagination
    unresolved = []
    on_disk = {p.name for p in (gh.RAW).glob("prs/*/pr-*-*.json")}
    for path, body in gh.iter_raw("prs/*/created-*.json"):
        repo_node = ((body.get("response") or {}).get("data") or {}).get("repository") or {}
        for node in (repo_node.get("pullRequests") or {}).get("nodes") or []:
            if not node or (node.get("createdAt") or "") < cutoff:
                continue
            for field in ("reviews", "timelineItems"):
                if ((node.get(field) or {}).get("pageInfo") or {}).get("hasNextPage"):
                    expect = f"pr-{node['number']}-{field}-000.json"
                    if expect not in on_disk:
                        unresolved.append({"repo": body["_meta"]["repo"], "number": node["number"], "field": field})
    for path, body in gh.iter_raw("prs/*/backfill-[0-9]*.json"):
        repo_node = ((body.get("response") or {}).get("data") or {}).get("repository") or {}
        for key, node in repo_node.items():
            if not key.startswith("p") or not isinstance(node, dict):
                continue
            for field in ("reviews", "timelineItems"):
                if ((node.get(field) or {}).get("pageInfo") or {}).get("hasNextPage"):
                    expect = f"pr-{node['number']}-{field}-000.json"
                    if expect not in on_disk:
                        unresolved.append({"repo": body["_meta"]["repo"], "number": node["number"], "field": field})
    record("C: every hasNextPage chain has its follow-up page on disk", not unresolved, unresolved)

    # D - window basis integrity
    wrong = conn.execute(
        "SELECT COUNT(*) FROM pull_requests WHERE (window_source='created' AND created_at < ?)"
        " OR (window_source='updated' AND created_at >= ?)",
        (cutoff, cutoff),
    ).fetchone()[0]
    record("D: window_source matches created_at", wrong == 0, {"misfiled_rows": wrong})

    # E - referential integrity
    orphan_reviews = conn.execute(
        "SELECT COUNT(*) FROM reviews r LEFT JOIN pull_requests p"
        " ON r.repo=p.repo AND r.number=p.number WHERE p.number IS NULL"
    ).fetchone()[0]
    orphan_events = conn.execute(
        "SELECT COUNT(*) FROM review_request_events e LEFT JOIN pull_requests p"
        " ON e.repo=p.repo AND e.number=p.number WHERE p.number IS NULL"
    ).fetchone()[0]
    record(
        "E: no orphan reviews or request events",
        orphan_reviews == 0 and orphan_events == 0,
        {"orphan_reviews": orphan_reviews, "orphan_request_events": orphan_events},
    )

    # F - independent cross-check of the default reviewer
    target = cfg["default_reviewer"]
    q = f"org:{cfg['org']} is:pr reviewed-by:{target} created:{cfg['window_start']}..{cfg['window_end']}"
    remote = search_count(q)
    local = conn.execute(
        "SELECT COUNT(DISTINCT r.repo || '#' || r.number) FROM reviews r"
        " JOIN pull_requests p ON r.repo=p.repo AND r.number=p.number"
        " WHERE r.author=? AND p.window_source='created'",
        (target,),
    ).fetchone()[0]
    drift = abs(local - remote)
    record(
        "F: default reviewer reviewed-PR count within 2% of search",
        remote == 0 or drift / max(remote, 1) <= 0.02,
        {"search_query": q, "search_issue_count": remote, "in_db": local, "delta": local - remote},
        hard=False,
    )

    # G - documents that totalCount ignores itemTypes
    totalcount_drift = []
    for path, body in gh.iter_raw("prs/*/created-0000.json"):
        repo_node = ((body.get("response") or {}).get("data") or {}).get("repository") or {}
        for node in ((repo_node.get("pullRequests") or {}).get("nodes") or [])[:5]:
            tl = node.get("timelineItems") or {}
            if "totalCount" in tl and tl["totalCount"] != len(tl.get("nodes") or []):
                totalcount_drift.append(
                    {"repo": body["_meta"]["repo"], "number": node["number"], "totalCount": tl["totalCount"], "nodes": len(tl["nodes"])}
                )
    record(
        "G: timelineItems.totalCount is not used for paging (informational)",
        True,
        {"observed_drift_samples": totalcount_drift[:10], "note": "totalCount is never read by build_db.py"},
        hard=False,
    )

    # H - change size in the database recomputed from the raw responses
    raw_size: dict[tuple, tuple[int, int, int]] = {}
    for path, body in gh.iter_raw("prs/*/created-*.json"):
        repo = body["_meta"]["repo"]
        repo_node = ((body.get("response") or {}).get("data") or {}).get("repository") or {}
        for node in (repo_node.get("pullRequests") or {}).get("nodes") or []:
            if not node or (node.get("createdAt") or "") < cutoff:
                continue
            if node.get("additions") is None or node.get("deletions") is None:
                continue
            raw_size[(repo, node["number"])] = (
                node["additions"],
                node["deletions"],
                node.get("changedFiles") or 0,
            )
    db_size = {
        (r[0], r[1]): (r[2], r[3], r[4] or 0)
        for r in conn.execute(
            "SELECT repo, number, additions, deletions, changed_files FROM pull_requests"
            " WHERE window_source='created' AND additions IS NOT NULL AND deletions IS NOT NULL"
        )
    }
    size_mismatch = [
        {"repo": k[0], "number": k[1], "raw": raw_size[k], "in_db": db_size.get(k)}
        for k in raw_size
        if db_size.get(k) != raw_size[k]
    ]
    raw_churn = sum(a + d for a, d, _ in raw_size.values())
    db_churn = sum(a + d for a, d, _ in db_size.values())
    record(
        "H: additions/deletions/changedFiles in db == raw responses",
        not size_mismatch and raw_churn == db_churn,
        {
            "prs_compared": len(raw_size),
            "raw_churn": raw_churn,
            "db_churn": db_churn,
            "missing_from_db": [f"{k[0]}#{k[1]}" for k in raw_size if k not in db_size][:10],
            "mismatches": size_mismatch[:10],
        },
    )

    # I - no PR silently carries a zero change size where GitHub reported none at all
    null_size = conn.execute(
        "SELECT COUNT(*) FROM pull_requests WHERE window_source='created'"
        " AND (additions IS NULL OR deletions IS NULL OR changed_files IS NULL)"
    ).fetchone()[0]
    zero_churn = conn.execute(
        "SELECT COUNT(*) FROM pull_requests WHERE window_source='created' AND additions=0 AND deletions=0"
    ).fetchone()[0]
    record(
        "I: missing change size stays NULL, never 0 (informational)",
        True,
        {
            "prs_with_null_size": null_size,
            "prs_with_genuine_zero_churn": zero_churn,
            "note": "aggregate.py excludes NULL sizes from every churn figure instead of treating them as 0",
        },
        hard=False,
    )

    summary = {
        "verified_at": gh.utcnow(),
        "org": cfg["org"],
        "window": [cfg["window_start"], cfg["window_end"]],
        "hard_failures": sum(1 for r in results if r["hard"] and not r["ok"]),
        "checks": results,
    }
    (gh.BUILD / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))

    for r in results:
        mark = "PASS" if r["ok"] else ("FAIL" if r["hard"] else "WARN")
        gh.log(f"{mark}  {r['check']}")
        if not r["ok"]:
            gh.log(f"      {json.dumps(r['detail'], ensure_ascii=False)[:600]}")
    conn.close()
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
