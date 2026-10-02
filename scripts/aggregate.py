"""Stage 4 - derive every dashboard number from outputs/build/facts.db into outputs/dashboard/data.json.

No figure is written by hand anywhere in this file; each one is the result of a SQL
read over facts.db. Missing data stays null so that "none" and "not collected" are
distinguishable in the dashboard.

The window basis is `created` - pull requests opened inside the window. The
`activity` basis (requests or reviews that happened inside the window whatever the
PR's creation date) is also computed and shipped for the reviewer comparison table.

Per-reviewer detail is produced for every reviewer in the roster, so the dashboard can
switch between them; config.json's `default_reviewer` decides which one opens first.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections import defaultdict

import ghclient as gh

TERMINAL_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING"}

# Change size is measured as churn = additions + deletions, as GitHub reports it on the
# pull request. Bucket edges are the upper bound of each band in churned lines; the last
# band is open-ended. Edges were placed on the observed distribution so that no band holds
# either a negligible or a dominant share of pull requests.
SIZE_BUCKETS: list[tuple[str, int | None]] = [
    ("XS ≤10", 10),
    ("S 11-50", 50),
    ("M 51-200", 200),
    ("L 201-500", 500),
    ("XL 501-1000", 1000),
    ("XXL >1000", None),
]
SIZE_LABELS = [label for label, _ in SIZE_BUCKETS]
# First-response latency bands, upper bound in hours; the last band is open-ended.
LATENCY_BUCKETS: list[tuple[str, int | None]] = [
    ("<=1h", 1),
    ("<=4h", 4),
    ("<=12h", 12),
    ("<=24h", 24),
    ("<=72h", 72),
    ("<=168h", 168),
    (">168h", None),
]
# Boundary between "small" and "large" for the paired latency comparison.
SMALL_MAX_CHURN = 200
LARGE_MIN_CHURN = 501


def size_bucket(churn: int | None) -> str | None:
    if churn is None:
        return None
    for label, edge in SIZE_BUCKETS:
        if edge is None or churn <= edge:
            return label
    return SIZE_LABELS[-1]


def churn_of(pr: dict) -> int | None:
    add, dele = pr.get("additions"), pr.get("deletions")
    if add is None or dele is None:
        return None
    return add + dele


def share(part: float | None, whole: float | None) -> float | None:
    if part is None or not whole:
        return None
    return round(part / whole, 6)


def stats_of(values: list[int]) -> dict:
    """Spread of a churn (or file-count) sample. Empty sample stays null, never zero."""
    if not values:
        return {"n": 0, "sum": None, "mean": None, "p50": None, "p90": None, "max": None}
    floats = [float(v) for v in values]
    return {
        "n": len(values),
        "sum": sum(values),
        "mean": round(sum(values) / len(values), 1),
        "p50": percentile(floats, 0.50),
        "p90": percentile(floats, 0.90),
        "max": max(values),
    }


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def one(conn: sqlite3.Connection, sql: str, params: tuple = ()):
    return conn.execute(sql, params).fetchone()[0]


def parse(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def hours_between(a: dt.datetime, b: dt.datetime) -> float:
    return round((b - a).total_seconds() / 3600.0, 3)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return round(ordered[idx], 2)


def week_key(moment: dt.datetime) -> str:
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def week_ends(start: dt.datetime, end: dt.datetime) -> list[tuple[str, dt.datetime]]:
    """Sunday 23:59:59Z boundaries covering the window, labelled by ISO week."""
    out: list[tuple[str, dt.datetime]] = []
    cursor = start
    while cursor <= end:
        boundary = cursor + dt.timedelta(days=(6 - cursor.weekday()) % 7)
        boundary = boundary.replace(hour=23, minute=59, second=59)
        if boundary > end:
            boundary = end
        out.append((week_key(cursor), boundary))
        cursor = (boundary + dt.timedelta(seconds=1)).replace(hour=0, minute=0, second=0)
        if out and len(out) > 300:
            break
    return out


class Model:
    """Facts loaded once into memory, keyed for the aggregations below."""

    def __init__(self, conn: sqlite3.Connection, cfg: dict) -> None:
        self.cfg = cfg
        self.bots = set(cfg["bot_logins"])
        self.window_start = parse(cfg["window_start"] + "T00:00:00Z")
        self.window_end = parse(cfg["window_end"] + "T23:59:59Z")

        self.prs = {(p["repo"], p["number"]): p for p in rows(conn, "SELECT * FROM pull_requests")}
        self.reviews = rows(
            conn,
            "SELECT * FROM reviews WHERE submitted_at IS NOT NULL ORDER BY submitted_at",
        )
        self.request_events = rows(conn, "SELECT * FROM review_request_events ORDER BY at")
        self.pending = rows(conn, "SELECT * FROM pending_review_requests")
        self.repos = {r["name"]: r for r in rows(conn, "SELECT * FROM repos")}
        self.meta = dict(rows_to_pairs(conn))

        self.reviews_by_pr: dict[tuple, list[dict]] = defaultdict(list)
        for rev in self.reviews:
            self.reviews_by_pr[(rev["repo"], rev["number"])].append(rev)

        self.pairs = self._build_pairs()

        # One denominator for every "share of the whole" figure: the churn of all pull
        # requests opened inside the window. Reviewer shares are measured against it and
        # therefore overlap, since a PR is normally requested from several reviewers.
        self.created_prs = [p for p in self.prs.values() if p["window_source"] == "created"]
        self.total_churn = sum(
            c for p in self.created_prs if (c := churn_of(p)) is not None
        )
        self.total_changed_files = sum(p["changed_files"] or 0 for p in self.created_prs)

    def _build_pairs(self) -> list[dict]:
        """One row per (PR, human reviewer) that was ever asked to review it."""
        agg: dict[tuple, dict] = {}
        for ev in self.request_events:
            if ev["reviewer_type"] in ("Team", "Bot") or not ev["reviewer"]:
                continue
            key = (ev["repo"], ev["number"], ev["reviewer"])
            slot = agg.setdefault(
                key,
                {
                    "repo": ev["repo"],
                    "number": ev["number"],
                    "reviewer": ev["reviewer"],
                    "requested_at": None,
                    "last_requested_at": None,
                    "removed_at": None,
                    "request_count": 0,
                },
            )
            if ev["event_type"] == "requested":
                slot["request_count"] += 1
                if slot["requested_at"] is None or ev["at"] < slot["requested_at"]:
                    slot["requested_at"] = ev["at"]
                if slot["last_requested_at"] is None or ev["at"] > slot["last_requested_at"]:
                    slot["last_requested_at"] = ev["at"]
            else:
                if slot["removed_at"] is None or ev["at"] > slot["removed_at"]:
                    slot["removed_at"] = ev["at"]

        # A reviewer can sit in the pending snapshot with no surviving timeline event.
        for pend in self.pending:
            if pend["reviewer_type"] in ("Team", "Bot") or not pend["reviewer"]:
                continue
            key = (pend["repo"], pend["number"], pend["reviewer"])
            if key not in agg:
                pr = self.prs.get((pend["repo"], pend["number"]))
                agg[key] = {
                    "repo": pend["repo"],
                    "number": pend["number"],
                    "reviewer": pend["reviewer"],
                    "requested_at": pr["created_at"] if pr else None,
                    "last_requested_at": pr["created_at"] if pr else None,
                    "removed_at": None,
                    "request_count": 0,
                    "source": "pending_snapshot_only",
                }

        pending_keys = {(p["repo"], p["number"], p["reviewer"]) for p in self.pending}
        out = []
        for key, slot in agg.items():
            pr = self.prs.get((slot["repo"], slot["number"]))
            if pr is None or slot["requested_at"] is None:
                continue
            if slot["reviewer"] in self.bots:
                continue
            if pr["author"] == slot["reviewer"]:
                continue

            own = [
                r
                for r in self.reviews_by_pr.get((slot["repo"], slot["number"]), [])
                if r["author"] == slot["reviewer"]
            ]
            first_any = min((r["submitted_at"] for r in own), default=None)
            after = [r["submitted_at"] for r in own if r["submitted_at"] >= slot["requested_at"]]
            first_after = min(after, default=None)

            slot.update(
                {
                    "pr_state": pr["state"],
                    "pr_created_at": pr["created_at"],
                    "pr_merged_at": pr["merged_at"],
                    "pr_closed_at": pr["closed_at"],
                    "pr_author": pr["author"],
                    "pr_title": pr["title"],
                    "pr_url": pr["url"],
                    "pr_churn": churn_of(pr),
                    "pr_changed_files": pr["changed_files"],
                    "pr_size_bucket": size_bucket(churn_of(pr)),
                    "reviewed": bool(own),
                    "review_count": len(own),
                    "first_review_at": first_any,
                    "first_review_after_request_at": first_after,
                    "latency_hours": (
                        hours_between(parse(slot["requested_at"]), parse(first_after))
                        if first_after
                        else None
                    ),
                    "still_pending_snapshot": key in pending_keys,
                }
            )
            out.append(slot)
        return out

    # window filters -------------------------------------------------------
    def in_created_window(self, pr: dict) -> bool:
        return pr["window_source"] == "created"

    def pair_in_basis(self, pair: dict, basis: str) -> bool:
        if basis == "created":
            return (pair["pr_created_at"] or "") >= self.cfg["window_start"]
        start, end = self.cfg["window_start"], self.cfg["window_end"] + "T23:59:59Z"
        if start <= (pair["requested_at"] or "") <= end:
            return True
        return bool(pair["first_review_at"] and start <= pair["first_review_at"] <= end)

    def review_in_basis(self, rev: dict, basis: str) -> bool:
        pr = self.prs.get((rev["repo"], rev["number"]))
        if pr is None:
            return False
        if basis == "created":
            return pr["window_source"] == "created"
        return self.cfg["window_start"] <= (rev["submitted_at"] or "") <= self.cfg["window_end"] + "T23:59:59Z"

    def is_human(self, login: str | None) -> bool:
        return bool(login) and login not in self.bots

    def is_human_review(self, rev: dict) -> bool:
        return self.is_human(rev["author"]) and rev.get("author_type") != "Bot"


def rows_to_pairs(conn: sqlite3.Connection):
    return [(r["key"], r["value"]) for r in rows(conn, "SELECT key, value FROM meta")]


def reviewer_table(model: Model, basis: str) -> list[dict]:
    pairs = [p for p in model.pairs if model.pair_in_basis(p, basis)]
    reviews = [
        r
        for r in model.reviews
        if model.is_human_review(r)
        and model.review_in_basis(r, basis)
        and (model.prs.get((r["repo"], r["number"])) or {}).get("author") != r["author"]
    ]

    by_reviewer: dict[str, dict] = {}

    def slot(login: str) -> dict:
        return by_reviewer.setdefault(
            login,
            {
                "reviewer": login,
                "requested_prs": 0,
                "fulfilled_prs": 0,
                "outstanding_open": 0,
                "merged_without_review": 0,
                "latencies": [],
                "reviews_given": 0,
                "reviewed_prs": set(),
                "inline_comments": 0,
                "body_chars": 0,
                "approved": 0,
                "changes_requested": 0,
                "commented": 0,
                "dismissed": 0,
                "substantive_reviews": 0,
                "unsolicited_prs": set(),
                "requested_churn": 0,
                "requested_churn_values": [],
                "fulfilled_churn": 0,
                "reviewed_pr_churn": {},
                "lat_small": [],
                "lat_large": [],
            },
        )

    requested_keys = set()
    for pair in pairs:
        s = slot(pair["reviewer"])
        s["requested_prs"] += 1
        requested_keys.add((pair["repo"], pair["number"], pair["reviewer"]))
        churn = pair["pr_churn"]
        if churn is not None:
            s["requested_churn"] += churn
            s["requested_churn_values"].append(churn)
        if pair["reviewed"]:
            s["fulfilled_prs"] += 1
            if churn is not None:
                s["fulfilled_churn"] += churn
        else:
            if pair["pr_state"] == "OPEN":
                s["outstanding_open"] += 1
            if pair["pr_merged_at"]:
                s["merged_without_review"] += 1
        if pair["latency_hours"] is not None:
            s["latencies"].append(pair["latency_hours"])
            if churn is not None and churn <= SMALL_MAX_CHURN:
                s["lat_small"].append(pair["latency_hours"])
            elif churn is not None and churn >= LARGE_MIN_CHURN:
                s["lat_large"].append(pair["latency_hours"])

    for rev in reviews:
        s = slot(rev["author"])
        s["reviews_given"] += 1
        s["reviewed_prs"].add((rev["repo"], rev["number"]))
        pr = model.prs.get((rev["repo"], rev["number"]))
        if pr is not None:
            s["reviewed_pr_churn"][(rev["repo"], rev["number"])] = churn_of(pr)
        s["inline_comments"] += rev["inline_comments"] or 0
        s["body_chars"] += rev["body_len"] or 0
        state = (rev["state"] or "").upper()
        if state == "APPROVED":
            s["approved"] += 1
        elif state == "CHANGES_REQUESTED":
            s["changes_requested"] += 1
        elif state == "COMMENTED":
            s["commented"] += 1
        elif state == "DISMISSED":
            s["dismissed"] += 1
        if (rev["inline_comments"] or 0) > 0 or (rev["body_len"] or 0) > 0:
            s["substantive_reviews"] += 1
        if (rev["repo"], rev["number"], rev["author"]) not in requested_keys:
            s["unsolicited_prs"].add((rev["repo"], rev["number"]))

    table = []
    total_churn = model.total_churn
    for login, s in by_reviewer.items():
        lat = s["latencies"]
        reviewed_churn_values = [v for v in s["reviewed_pr_churn"].values() if v is not None]
        verdicts = s["approved"] + s["changes_requested"]
        lat_small_p50 = percentile(s["lat_small"], 0.50)
        lat_large_p50 = percentile(s["lat_large"], 0.50)
        table.append(
            {
                "reviewer": login,
                "requested_prs": s["requested_prs"],
                "fulfilled_prs": s["fulfilled_prs"],
                "response_rate": round(s["fulfilled_prs"] / s["requested_prs"], 4) if s["requested_prs"] else None,
                "outstanding_open": s["outstanding_open"],
                "merged_without_review": s["merged_without_review"],
                "merged_without_review_rate": (
                    round(s["merged_without_review"] / s["requested_prs"], 4) if s["requested_prs"] else None
                ),
                "reviews_given": s["reviews_given"],
                "reviewed_prs": len(s["reviewed_prs"]),
                "latency_p50_h": percentile(lat, 0.50),
                "latency_p90_h": percentile(lat, 0.90),
                "latency_mean_h": round(sum(lat) / len(lat), 2) if lat else None,
                "latency_samples": len(lat),
                "inline_comments": s["inline_comments"],
                "comments_per_review": (
                    round(s["inline_comments"] / s["reviews_given"], 2) if s["reviews_given"] else None
                ),
                "substantive_review_rate": (
                    round(s["substantive_reviews"] / s["reviews_given"], 4) if s["reviews_given"] else None
                ),
                "approved": s["approved"],
                "changes_requested": s["changes_requested"],
                "commented": s["commented"],
                "dismissed": s["dismissed"],
                "verdicts": verdicts,
                "approve_rate": round(s["approved"] / verdicts, 4) if verdicts else None,
                "changes_rate": round(s["changes_requested"] / verdicts, 4) if verdicts else None,
                "changes_per_100_reviews": (
                    round(s["changes_requested"] * 100 / s["reviews_given"], 1) if s["reviews_given"] else None
                ),
                "unsolicited_prs": len(s["unsolicited_prs"]),
                # change-size view: churn of the PRs this reviewer was asked to look at,
                # and of the ones they actually reviewed. Shares are measured against the
                # window's whole churn and OVERLAP between reviewers, because one PR is
                # normally requested from several people.
                "requested_churn": s["requested_churn"],
                "requested_churn_share": share(s["requested_churn"], total_churn),
                "fulfilled_churn": s["fulfilled_churn"],
                "churn_response_rate": (
                    round(s["fulfilled_churn"] / s["requested_churn"], 4) if s["requested_churn"] else None
                ),
                "reviewed_churn": sum(reviewed_churn_values) if reviewed_churn_values else None,
                "reviewed_churn_share": share(sum(reviewed_churn_values), total_churn) if reviewed_churn_values else None,
                "reviewed_churn_p50": percentile([float(v) for v in reviewed_churn_values], 0.50),
                "reviewed_churn_mean": (
                    round(sum(reviewed_churn_values) / len(reviewed_churn_values), 1) if reviewed_churn_values else None
                ),
                "latency_small_p50_h": lat_small_p50,
                "latency_large_p50_h": lat_large_p50,
                "latency_size_gap_h": (
                    round(lat_large_p50 - lat_small_p50, 2)
                    if lat_small_p50 is not None and lat_large_p50 is not None
                    else None
                ),
                "latency_small_samples": len(s["lat_small"]),
                "latency_large_samples": len(s["lat_large"]),
            }
        )
    table.sort(key=lambda r: (-r["reviews_given"], -r["requested_prs"]))
    return table


def backlog_series(model: Model, reviewer: str, basis: str) -> list[dict]:
    pairs = [
        p for p in model.pairs if p["reviewer"] == reviewer and model.pair_in_basis(p, basis)
    ]
    series = []
    for label, boundary in week_ends(model.window_start, model.window_end):
        edge = boundary.strftime("%Y-%m-%dT%H:%M:%SZ")
        outstanding = 0
        for p in pairs:
            if (p["requested_at"] or "") > edge:
                continue
            if p["first_review_at"] and p["first_review_at"] <= edge:
                continue
            if p["removed_at"] and p["removed_at"] <= edge:
                continue
            if p["pr_closed_at"] and p["pr_closed_at"] <= edge:
                continue
            outstanding += 1
        requested = sum(1 for p in pairs if week_key(parse(p["requested_at"])) == label)
        reviewed = sum(
            1
            for p in pairs
            if p["first_review_at"] and week_key(parse(p["first_review_at"])) == label
        )
        series.append(
            {
                "week": label,
                "week_end": edge,
                "outstanding": outstanding,
                "requested": requested,
                "first_reviews": reviewed,
            }
        )
    return series


def weekly_volume(model: Model) -> list[dict]:
    created: dict[str, int] = defaultdict(int)
    merged: dict[str, int] = defaultdict(int)
    reviews: dict[str, int] = defaultdict(int)
    for pr in model.prs.values():
        if pr["window_source"] == "created":
            created[week_key(parse(pr["created_at"]))] += 1
        if pr["merged_at"] and pr["merged_at"] >= model.cfg["window_start"]:
            merged[week_key(parse(pr["merged_at"]))] += 1
    for rev in model.reviews:
        if model.is_human_review(rev) and rev["submitted_at"] >= model.cfg["window_start"]:
            reviews[week_key(parse(rev["submitted_at"]))] += 1
    labels = [label for label, _ in week_ends(model.window_start, model.window_end)]
    return [
        {"week": w, "prs_created": created.get(w, 0), "prs_merged": merged.get(w, 0), "reviews": reviews.get(w, 0)}
        for w in labels
    ]


def reviewer_detail(model: Model, reviewer: str, basis: str) -> dict:
    pairs = [
        p for p in model.pairs if p["reviewer"] == reviewer and model.pair_in_basis(p, basis)
    ]
    own_reviews = [
        r
        for r in model.reviews
        if r["author"] == reviewer
        and model.is_human_review(r)
        and model.review_in_basis(r, basis)
        and (model.prs.get((r["repo"], r["number"])) or {}).get("author") != reviewer
    ]

    by_repo: dict[str, dict] = {}
    for p in pairs:
        s = by_repo.setdefault(
            p["repo"],
            {
                "repo": p["repo"],
                "requested": 0,
                "reviewed": 0,
                "outstanding_open": 0,
                "merged_without_review": 0,
                "requested_churn": 0,
                "reviewed_churn": 0,
                "_lat": [],
            },
        )
        s["requested"] += 1
        if p["pr_churn"] is not None:
            s["requested_churn"] += p["pr_churn"]
        if p["reviewed"]:
            s["reviewed"] += 1
            if p["pr_churn"] is not None:
                s["reviewed_churn"] += p["pr_churn"]
        else:
            if p["pr_state"] == "OPEN":
                s["outstanding_open"] += 1
            if p["pr_merged_at"]:
                s["merged_without_review"] += 1
        if p["latency_hours"] is not None:
            s["_lat"].append(p["latency_hours"])
    reviewer_requested_churn = sum(s["requested_churn"] for s in by_repo.values())
    for s in by_repo.values():
        s["response_rate"] = round(s["reviewed"] / s["requested"], 4) if s["requested"] else None
        s["churn_response_rate"] = (
            round(s["reviewed_churn"] / s["requested_churn"], 4) if s["requested_churn"] else None
        )
        s["requested_churn_share"] = share(s["requested_churn"], reviewer_requested_churn)
        s["churn_per_pr"] = round(s["requested_churn"] / s["requested"], 1) if s["requested"] else None
        s["latency_p50_h"] = percentile(s.pop("_lat"), 0.50)
        s["repo_prs_total"] = sum(
            1 for pr in model.prs.values() if pr["repo"] == s["repo"] and pr["window_source"] == "created"
        )

    by_author: dict[str, dict] = {}
    for p in pairs:
        s = by_author.setdefault(
            p["pr_author"] or "(unknown)",
            {"author": p["pr_author"] or "(unknown)", "requested": 0, "reviewed": 0, "requested_churn": 0, "_lat": []},
        )
        s["requested"] += 1
        if p["pr_churn"] is not None:
            s["requested_churn"] += p["pr_churn"]
        if p["reviewed"]:
            s["reviewed"] += 1
        if p["latency_hours"] is not None:
            s["_lat"].append(p["latency_hours"])
    for s in by_author.values():
        s["response_rate"] = round(s["reviewed"] / s["requested"], 4) if s["requested"] else None
        s["requested_churn_share"] = share(s["requested_churn"], reviewer_requested_churn)
        s["churn_per_pr"] = round(s["requested_churn"] / s["requested"], 1) if s["requested"] else None
        s["latency_p50_h"] = percentile(s.pop("_lat"), 0.50)

    # change-size bands for this reviewer: volume, churn weight, wait and verdict per band
    own_by_pr: dict[tuple, list[dict]] = defaultdict(list)
    for r in own_reviews:
        own_by_pr[(r["repo"], r["number"])].append(r)
    by_size = []
    for label in SIZE_LABELS:
        band = [p for p in pairs if p["pr_size_bucket"] == label]
        band_reviews = [r for p in band for r in own_by_pr.get((p["repo"], p["number"]), [])]
        lats = [p["latency_hours"] for p in band if p["latency_hours"] is not None]
        churn = sum(p["pr_churn"] for p in band if p["pr_churn"] is not None)
        reviewed = sum(1 for p in band if p["reviewed"])
        approved = sum(1 for r in band_reviews if (r["state"] or "").upper() == "APPROVED")
        changes = sum(1 for r in band_reviews if (r["state"] or "").upper() == "CHANGES_REQUESTED")
        by_size.append(
            {
                "bucket": label,
                "requested": len(band),
                "requested_share": share(len(band), len(pairs)),
                "reviewed": reviewed,
                "response_rate": share(reviewed, len(band)),
                "churn": churn,
                "churn_share": share(churn, reviewer_requested_churn),
                "latency_p50_h": percentile(lats, 0.50),
                "latency_p90_h": percentile(lats, 0.90),
                "latency_samples": len(lats),
                "reviews": len(band_reviews),
                "inline_comments": sum(r["inline_comments"] or 0 for r in band_reviews),
                "comments_per_review": (
                    round(sum(r["inline_comments"] or 0 for r in band_reviews) / len(band_reviews), 2)
                    if band_reviews
                    else None
                ),
                "approved": approved,
                "changes_requested": changes,
                "verdicts": approved + changes,
                "changes_rate": share(changes, approved + changes),
                "outstanding_open": sum(1 for p in band if not p["reviewed"] and p["pr_state"] == "OPEN"),
                "merged_without_review": sum(1 for p in band if not p["reviewed"] and p["pr_merged_at"]),
            }
        )

    heaviest = [
        {
            "repo": p["repo"],
            "number": p["number"],
            "title": p["pr_title"],
            "url": p["pr_url"],
            "author": p["pr_author"],
            "churn": p["pr_churn"],
            "changed_files": p["pr_changed_files"],
            "bucket": p["pr_size_bucket"],
            "reviewed": p["reviewed"],
            "latency_hours": p["latency_hours"],
            "reviews": len(own_by_pr.get((p["repo"], p["number"]), [])),
            "inline_comments": sum(r["inline_comments"] or 0 for r in own_by_pr.get((p["repo"], p["number"]), [])),
            "verdict": next(
                (
                    r["state"]
                    for r in sorted(own_by_pr.get((p["repo"], p["number"]), []), key=lambda x: x["submitted_at"] or "")
                    if (r["state"] or "").upper() in ("APPROVED", "CHANGES_REQUESTED")
                ),
                None,
            ),
        }
        for p in pairs
        if p["pr_churn"] is not None
    ]
    heaviest.sort(key=lambda r: -(r["churn"] or 0))
    heaviest = heaviest[:30]

    buckets = LATENCY_BUCKETS
    hist = {label: 0 for label, _ in buckets}
    for p in pairs:
        if p["latency_hours"] is None:
            continue
        for label, edge in buckets:
            if edge is None or p["latency_hours"] <= edge:
                hist[label] += 1
                break

    outstanding = [
        {
            "repo": p["repo"],
            "number": p["number"],
            "title": p["pr_title"],
            "url": p["pr_url"],
            "author": p["pr_author"],
            "requested_at": p["requested_at"],
            "waiting_hours": hours_between(parse(p["requested_at"]), model.window_end),
            "still_pending_snapshot": p["still_pending_snapshot"],
            "churn": p["pr_churn"],
            "changed_files": p["pr_changed_files"],
            "bucket": p["pr_size_bucket"],
        }
        for p in pairs
        if not p["reviewed"] and p["pr_state"] == "OPEN"
    ]
    outstanding.sort(key=lambda r: -r["waiting_hours"])

    merged_unreviewed = [
        {
            "repo": p["repo"],
            "number": p["number"],
            "title": p["pr_title"],
            "url": p["pr_url"],
            "author": p["pr_author"],
            "requested_at": p["requested_at"],
            "merged_at": p["pr_merged_at"],
            "churn": p["pr_churn"],
            "changed_files": p["pr_changed_files"],
            "bucket": p["pr_size_bucket"],
        }
        for p in pairs
        if not p["reviewed"] and p["pr_merged_at"]
    ]
    merged_unreviewed.sort(key=lambda r: r["merged_at"] or "", reverse=True)

    return {
        "reviewer": reviewer,
        "requested_churn": reviewer_requested_churn,
        "requested_churn_share": share(reviewer_requested_churn, model.total_churn),
        "by_repo": sorted(by_repo.values(), key=lambda r: -r["requested"]),
        "by_pr_author": sorted(by_author.values(), key=lambda r: -r["requested"]),
        "by_size": by_size,
        "heaviest_prs": heaviest,
        "latency_histogram": [{"bucket": label, "count": hist[label]} for label, _ in buckets],
        "backlog_weekly": backlog_series(model, reviewer, basis),
        "outstanding_open": outstanding,
        "merged_without_review": merged_unreviewed,
        "review_state_mix": {
            "approved": sum(1 for r in own_reviews if r["state"] == "APPROVED"),
            "changes_requested": sum(1 for r in own_reviews if r["state"] == "CHANGES_REQUESTED"),
            "commented": sum(1 for r in own_reviews if r["state"] == "COMMENTED"),
            "dismissed": sum(1 for r in own_reviews if r["state"] == "DISMISSED"),
        },
    }


def human_reviews_created(model: Model) -> list[dict]:
    """Human, non-self reviews on pull requests opened inside the window."""
    return [
        r
        for r in model.reviews
        if model.is_human_review(r)
        and model.review_in_basis(r, "created")
        and (model.prs.get((r["repo"], r["number"])) or {}).get("author") != r["author"]
    ]


def size_overview(model: Model) -> dict:
    """Change-size profile of the window: how PR count and churn split across size bands,
    and whether a bigger change waits longer or draws a different verdict."""
    prs = model.created_prs
    churns = [c for p in prs if (c := churn_of(p)) is not None]
    files = [p["changed_files"] for p in prs if p["changed_files"] is not None]

    reviews = human_reviews_created(model)
    reviews_by_pr: dict[tuple, list[dict]] = defaultdict(list)
    for r in reviews:
        reviews_by_pr[(r["repo"], r["number"])].append(r)

    pairs = [p for p in model.pairs if model.pair_in_basis(p, "created")]
    pairs_by_bucket: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        if p["pr_size_bucket"]:
            pairs_by_bucket[p["pr_size_bucket"]].append(p)

    rows = []
    for label in SIZE_LABELS:
        band = [p for p in prs if size_bucket(churn_of(p)) == label]
        band_churn = sum(c for p in band if (c := churn_of(p)) is not None)
        band_files = sum(p["changed_files"] or 0 for p in band)
        band_reviews = [r for p in band for r in reviews_by_pr.get((p["repo"], p["number"]), [])]
        reviewed_prs = sum(1 for p in band if reviews_by_pr.get((p["repo"], p["number"])))
        merged = sum(1 for p in band if p["merged_at"])
        merged_unreviewed = sum(
            1 for p in band if p["merged_at"] and not reviews_by_pr.get((p["repo"], p["number"]))
        )
        lats = [p["latency_hours"] for p in pairs_by_bucket.get(label, []) if p["latency_hours"] is not None]
        approved = sum(1 for r in band_reviews if (r["state"] or "").upper() == "APPROVED")
        changes = sum(1 for r in band_reviews if (r["state"] or "").upper() == "CHANGES_REQUESTED")
        verdicts = approved + changes
        rows.append(
            {
                "bucket": label,
                "prs": len(band),
                "prs_share": share(len(band), len(prs)),
                "churn": band_churn,
                "churn_share": share(band_churn, model.total_churn),
                "changed_files": band_files,
                "changed_files_share": share(band_files, model.total_changed_files),
                "churn_p50": percentile([float(c) for p in band if (c := churn_of(p)) is not None], 0.50),
                "files_p50": percentile([float(p["changed_files"]) for p in band if p["changed_files"] is not None], 0.50),
                "merged": merged,
                "reviewed_prs": reviewed_prs,
                "review_coverage": share(reviewed_prs, len(band)),
                "merged_without_review": merged_unreviewed,
                "merged_without_review_rate": share(merged_unreviewed, merged),
                "reviews": len(band_reviews),
                "reviews_per_pr": round(len(band_reviews) / len(band), 2) if band else None,
                "inline_comments": sum(r["inline_comments"] or 0 for r in band_reviews),
                "comments_per_pr": (
                    round(sum(r["inline_comments"] or 0 for r in band_reviews) / len(band), 2) if band else None
                ),
                "latency_p50_h": percentile(lats, 0.50),
                "latency_p90_h": percentile(lats, 0.90),
                "latency_samples": len(lats),
                "approved": approved,
                "changes_requested": changes,
                "verdicts": verdicts,
                "changes_rate": share(changes, verdicts),
                "approve_rate": share(approved, verdicts),
            }
        )

    ordered = sorted(churns, reverse=True)
    top10 = ordered[: max(1, len(ordered) // 10)] if ordered else []
    all_reviews = reviews
    approved_all = sum(1 for r in all_reviews if (r["state"] or "").upper() == "APPROVED")
    changes_all = sum(1 for r in all_reviews if (r["state"] or "").upper() == "CHANGES_REQUESTED")
    return {
        "buckets": rows,
        "bucket_labels": SIZE_LABELS,
        "small_max_churn": SMALL_MAX_CHURN,
        "large_min_churn": LARGE_MIN_CHURN,
        "totals": {
            "prs": len(prs),
            "churn": model.total_churn,
            "additions": sum(p["additions"] or 0 for p in prs),
            "deletions": sum(p["deletions"] or 0 for p in prs),
            "changed_files": model.total_changed_files,
            "churn_missing_prs": sum(1 for p in prs if churn_of(p) is None),
            "churn_stats": stats_of(churns),
            "files_stats": stats_of(files),
            "churn_p25": percentile([float(c) for c in churns], 0.25),
            "churn_p75": percentile([float(c) for c in churns], 0.75),
            "churn_p99": percentile([float(c) for c in churns], 0.99),
            "top_decile_churn_share": share(sum(top10), model.total_churn),
            "approved": approved_all,
            "changes_requested": changes_all,
            "verdicts": approved_all + changes_all,
            "changes_rate": share(changes_all, approved_all + changes_all),
        },
    }


def bulk_request_evidence(model: Model) -> dict:
    """How many reviewers a PR asks at once, and how fast after opening."""
    per_pr: dict[tuple, list[dict]] = defaultdict(list)
    for p in model.pairs:
        per_pr[(p["repo"], p["number"])].append(p)
    sizes, delays = [], []
    for key, plist in per_pr.items():
        pr = model.prs.get(key)
        if not pr or pr["window_source"] != "created":
            continue
        sizes.append(len(plist))
        first = min(p["requested_at"] for p in plist)
        delays.append(hours_between(parse(pr["created_at"]), parse(first)))
    dist: dict[int, int] = defaultdict(int)
    for s in sizes:
        dist[s] += 1
    return {
        "prs_with_requests": len(sizes),
        "reviewers_per_pr_mean": round(sum(sizes) / len(sizes), 2) if sizes else None,
        "reviewers_per_pr_p50": percentile([float(s) for s in sizes], 0.5),
        "reviewers_per_pr_distribution": [{"reviewers": k, "prs": dist[k]} for k in sorted(dist)],
        "first_request_delay_p50_h": percentile(delays, 0.5),
        "first_request_delay_p90_h": percentile(delays, 0.9),
    }


def epoch(ts: str | None) -> int | None:
    moment = parse(ts)
    return int(moment.timestamp()) if moment else None


def export_facts(model: Model) -> dict:
    """Ship the facts themselves, not just one window's summary, so the dashboard can
    re-aggregate for any date range the user picks.

    Columnar with interned repo/login tables and epoch-second timestamps: the same rows
    as verbose JSON objects are several times larger. Pull request urls are omitted
    because they are `https://github.com/<org>/<repo>/pull/<number>` without exception
    (verify.py's own query confirms it), so the page rebuilds them.
    """
    repos: list[str] = []
    repo_idx: dict[str, int] = {}
    logins: list[str] = []
    login_idx: dict[str | None, int] = {}

    def ri(name: str) -> int:
        if name not in repo_idx:
            repo_idx[name] = len(repos)
            repos.append(name)
        return repo_idx[name]

    def li(login: str | None) -> int:
        key = login or "(unknown)"
        if key not in login_idx:
            login_idx[key] = len(logins)
            logins.append(key)
        return login_idx[key]

    prs = sorted(model.created_prs, key=lambda p: p["created_at"] or "")
    pr_cols = {
        "repo": [ri(p["repo"]) for p in prs],
        "number": [p["number"] for p in prs],
        "author": [li(p["author"]) for p in prs],
        "created": [epoch(p["created_at"]) for p in prs],
        "merged": [epoch(p["merged_at"]) for p in prs],
        "closed": [epoch(p["closed_at"]) for p in prs],
        "state": [p["state"] for p in prs],
        "additions": [p["additions"] for p in prs],
        "deletions": [p["deletions"] for p in prs],
        "changed_files": [p["changed_files"] for p in prs],
        "draft": [1 if p["is_draft"] else 0 for p in prs],
        "title": [p["title"] or "" for p in prs],
    }

    in_scope = {(p["repo"], p["number"]) for p in prs}
    pairs = [p for p in model.pairs if (p["repo"], p["number"]) in in_scope]
    pair_cols = {
        "repo": [ri(p["repo"]) for p in pairs],
        "number": [p["number"] for p in pairs],
        "reviewer": [li(p["reviewer"]) for p in pairs],
        "requested": [epoch(p["requested_at"]) for p in pairs],
        "last_requested": [epoch(p["last_requested_at"]) for p in pairs],
        "removed": [epoch(p["removed_at"]) for p in pairs],
        "first_review": [epoch(p["first_review_at"]) for p in pairs],
        "first_after": [epoch(p["first_review_after_request_at"]) for p in pairs],
        "pending_snapshot": [1 if p["still_pending_snapshot"] else 0 for p in pairs],
    }

    reviews = [
        r
        for r in human_reviews_created(model)
        if (r["repo"], r["number"]) in in_scope
    ]
    review_cols = {
        "repo": [ri(r["repo"]) for r in reviews],
        "number": [r["number"] for r in reviews],
        "author": [li(r["author"]) for r in reviews],
        "at": [epoch(r["submitted_at"]) for r in reviews],
        "state": [(r["state"] or "").upper() for r in reviews],
        "inline_comments": [r["inline_comments"] or 0 for r in reviews],
        "body_len": [r["body_len"] or 0 for r in reviews],
    }

    repo_meta = [
        {
            "repo": name,
            "is_archived": bool(model.repos[name]["is_archived"]),
            "language": model.repos[name]["language"],
            "expected_created_in_window": model.repos[name]["expected_created_in_window"],
        }
        for name in repos
    ]

    return {
        "repo_table": repos,
        "login_table": logins,
        "repo_meta": repo_meta,
        "prs": pr_cols,
        "pairs": pair_cols,
        "reviews": review_cols,
        "counts": {"prs": len(prs), "pairs": len(pairs), "reviews": len(reviews)},
        "size_buckets": [{"label": label, "max_churn": edge} for label, edge in SIZE_BUCKETS],
        "latency_buckets": [
            {"label": label, "max_hours": edge} for label, edge in LATENCY_BUCKETS
        ],
        "small_max_churn": SMALL_MAX_CHURN,
        "large_min_churn": LARGE_MIN_CHURN,
        "bot_reviews_excluded": sum(1 for r in model.reviews if not model.is_human_review(r)),
        "self_reviews_excluded": sum(
            1
            for r in model.reviews
            if (model.prs.get((r["repo"], r["number"])) or {}).get("author") == r["author"]
        ),
    }


def main() -> None:
    cfg = gh.load_config()
    conn = sqlite3.connect(gh.BUILD / "facts.db")
    model = Model(conn, cfg)
    default_reviewer = cfg["default_reviewer"]
    basis = "created"

    repo_rows = []
    reviews_created = human_reviews_created(model)
    reviews_by_pr_all: dict[tuple, list[dict]] = defaultdict(list)
    for r in reviews_created:
        reviews_by_pr_all[(r["repo"], r["number"])].append(r)
    pairs_created = [p for p in model.pairs if model.pair_in_basis(p, "created")]
    pairs_by_repo: dict[str, list[dict]] = defaultdict(list)
    for p in pairs_created:
        pairs_by_repo[p["repo"]].append(p)
    total_prs_created = len(model.created_prs)

    for name, repo in model.repos.items():
        created = [p for p in model.prs.values() if p["repo"] == name and p["window_source"] == "created"]
        if not created and not repo["expected_created_in_window"]:
            continue
        churns = [c for p in created if (c := churn_of(p)) is not None]
        repo_churn = sum(churns)
        repo_files = sum(p["changed_files"] or 0 for p in created)
        repo_reviews = [r for p in created for r in reviews_by_pr_all.get((p["repo"], p["number"]), [])]
        reviewed_prs = sum(1 for p in created if reviews_by_pr_all.get((p["repo"], p["number"])))
        lats = [p["latency_hours"] for p in pairs_by_repo.get(name, []) if p["latency_hours"] is not None]
        approved = sum(1 for r in repo_reviews if (r["state"] or "").upper() == "APPROVED")
        changes = sum(1 for r in repo_reviews if (r["state"] or "").upper() == "CHANGES_REQUESTED")
        prs_share = share(len(created), total_prs_created)
        churn_share = share(repo_churn, model.total_churn)
        size_mix = {label: 0 for label in SIZE_LABELS}
        for p in created:
            bucket = size_bucket(churn_of(p))
            if bucket:
                size_mix[bucket] += 1
        repo_rows.append(
            {
                "repo": name,
                "is_archived": bool(repo["is_archived"]),
                "language": repo["language"],
                "prs_created": len(created),
                "prs_share": prs_share,
                "prs_merged": sum(1 for p in created if p["merged_at"]),
                "prs_open": sum(1 for p in created if p["state"] == "OPEN"),
                "prs_closed_unmerged": sum(1 for p in created if p["state"] == "CLOSED"),
                "distinct_authors": len({p["author"] for p in created}),
                "expected_created_in_window": repo["expected_created_in_window"],
                # change size
                "churn": repo_churn,
                "churn_share": churn_share,
                "additions": sum(p["additions"] or 0 for p in created),
                "deletions": sum(p["deletions"] or 0 for p in created),
                "changed_files": repo_files,
                "changed_files_share": share(repo_files, model.total_changed_files),
                "churn_p50": percentile([float(c) for c in churns], 0.50),
                "churn_p90": percentile([float(c) for c in churns], 0.90),
                "churn_mean": round(repo_churn / len(churns), 1) if churns else None,
                "churn_max": max(churns) if churns else None,
                # >1 means this repo eats a bigger slice of the org's churn than of its PR count
                "weight_index": (
                    round(churn_share / prs_share, 2) if churn_share and prs_share else None
                ),
                "large_prs": sum(1 for c in churns if c >= LARGE_MIN_CHURN),
                "large_pr_rate": share(sum(1 for c in churns if c >= LARGE_MIN_CHURN), len(churns)),
                "size_mix": [{"bucket": k, "prs": v} for k, v in size_mix.items()],
                # review response
                "reviewed_prs": reviewed_prs,
                "review_coverage": share(reviewed_prs, len(created)),
                "reviews": len(repo_reviews),
                "latency_p50_h": percentile(lats, 0.50),
                "latency_p90_h": percentile(lats, 0.90),
                "latency_samples": len(lats),
                "approved": approved,
                "changes_requested": changes,
                "verdicts": approved + changes,
                "changes_rate": share(changes, approved + changes),
                "inline_comments": sum(r["inline_comments"] or 0 for r in repo_reviews),
                "comments_per_pr": round(sum(r["inline_comments"] or 0 for r in repo_reviews) / len(created), 2) if created else None,
            }
        )
    repo_rows.sort(key=lambda r: -r["prs_created"])

    created_prs = model.created_prs
    author_counts: dict[str, int] = defaultdict(int)
    author_churn: dict[str, int] = defaultdict(int)
    author_churn_values: dict[str, list[int]] = defaultdict(list)
    author_files: dict[str, int] = defaultdict(int)
    for p in created_prs:
        who = p["author"] or "(unknown)"
        author_counts[who] += 1
        author_files[who] += p["changed_files"] or 0
        c = churn_of(p)
        if c is not None:
            author_churn[who] += c
            author_churn_values[who].append(c)

    reviewers_created = reviewer_table(model, "created")
    reviewers_activity = reviewer_table(model, "activity")
    roster = [r["reviewer"] for r in reviewers_created]
    if default_reviewer not in roster:
        roster.insert(0, default_reviewer)

    # The reference exists to be checked against the page's own engine, so it carries the
    # comparable figures only - the long PR listings and the weekly series the page no
    # longer draws are left out rather than shipped unused.
    reference_detail = reviewer_detail(model, default_reviewer, basis)
    for heavy in ("backlog_weekly", "outstanding_open", "merged_without_review", "heaviest_prs"):
        reference_detail.pop(heavy, None)

    data = {
        "meta": {
            "generated_at": gh.utcnow(),
            "org": cfg["org"],
            # The COLLECTION window - everything that was fetched. The dashboard's own view
            # window is chosen in the page and can never reach outside this range.
            "window_start": cfg["window_start"],
            "window_end": cfg["window_end"],
            "collection_start": cfg["window_start"],
            "collection_end": cfg["window_end"],
            "view_default_days": cfg.get("view_default_days") or 90,
            "basis": basis,
            "default_reviewer": default_reviewer,
            "reviewer_roster": roster,
            "include_archived": cfg["include_archived"],
            "built_at": model.meta.get("built_at"),
            "raw_pr_pages": model.meta.get("raw_pr_pages"),
            "raw_overflow_pages": model.meta.get("raw_overflow_pages"),
        },
        "facts": export_facts(model),
        # Everything below is computed here, in SQL-derived Python, for the FULL collection
        # window. The page never displays it: it re-aggregates the facts itself for whatever
        # window the user picks. check_render.mjs points the page at the full window and
        # asserts its numbers equal these, which is what keeps the in-page engine honest.
        "reference": {
            "window": [cfg["window_start"], cfg["window_end"] or gh.utcnow()[:10]],
            "totals": {
                "repos_in_scope": len(repo_rows),
                "repos_archived_in_scope": sum(1 for r in repo_rows if r["is_archived"]),
                "prs_created_in_window": len(created_prs),
                "prs_merged": sum(1 for p in created_prs if p["merged_at"]),
                "prs_open": sum(1 for p in created_prs if p["state"] == "OPEN"),
                "prs_closed_unmerged": sum(1 for p in created_prs if p["state"] == "CLOSED"),
                "prs_draft_now": sum(1 for p in created_prs if p["is_draft"]),
                # Window-scoped, and defined exactly as the dashboard defines them: human,
                # non-self reviews on in-window pull requests, and the request pairs on those
                # same pull requests. The collection-wide counts live under *_all_db below,
                # so the two are never confused for one another.
                "human_reviews": len(human_reviews_created(model)),
                "review_request_pairs": len(pairs_created),
                "distinct_reviewers": len({p["reviewer"] for p in pairs_created}),
                "distinct_pr_authors": len(author_counts),
                "churn_total": model.total_churn,
                "changed_files_total": model.total_changed_files,
                "churn_per_pr_mean": round(model.total_churn / len(created_prs), 1) if created_prs else None,
                "prs_backfilled": sum(1 for p in model.prs.values() if p["window_source"] == "updated"),
                "human_reviews_all_db": sum(1 for r in model.reviews if model.is_human_review(r)),
                "bot_reviews": sum(1 for r in model.reviews if not model.is_human_review(r)),
                "self_reviews": sum(
                    1
                    for r in model.reviews
                    if (model.prs.get((r["repo"], r["number"])) or {}).get("author") == r["author"]
                ),
                "review_request_pairs_all_db": len(model.pairs),
            },
            "bulk_request_evidence": bulk_request_evidence(model),
            "size_overview": size_overview(model),
            "repos": repo_rows,
            "pr_authors": sorted(
                (
                    {
                        "author": a,
                        "prs_created": c,
                        "prs_share": share(c, len(created_prs)),
                        "churn": author_churn.get(a) or None,
                        "churn_share": share(author_churn.get(a), model.total_churn),
                        "churn_p50": percentile([float(v) for v in author_churn_values.get(a, [])], 0.50),
                        "churn_mean": (
                            round(author_churn[a] / len(author_churn_values[a]), 1)
                            if author_churn_values.get(a)
                            else None
                        ),
                        "changed_files": author_files.get(a) or None,
                        "weight_index": (
                            round(share(author_churn.get(a), model.total_churn) / share(c, len(created_prs)), 2)
                            if author_churn.get(a) and c
                            else None
                        ),
                    }
                    for a, c in author_counts.items()
                ),
                key=lambda r: -r["prs_created"],
            ),
            "weekly_volume": weekly_volume(model),
            "reviewers": {"created": reviewers_created, "activity": reviewers_activity},
            "reviewer_detail": {default_reviewer: reference_detail},
        },
    }

    gh.DASHBOARD.mkdir(parents=True, exist_ok=True)
    out = gh.DASHBOARD / "data.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    conn.close()
    gh.log(f"data.json written ({out.stat().st_size // 1024} KB), {len(roster)} reviewers")
    facts = data["facts"]["counts"]
    gh.log(
        f"facts shipped for in-page re-aggregation: {facts['prs']} PRs / {facts['pairs']} request pairs"
        f" / {facts['reviews']} reviews; default view window {data['meta']['view_default_days']} days"
    )
    gh.log(
        f"reference (full collection window) for {default_reviewer}: "
        + json.dumps(
            next((r for r in reviewers_created if r["reviewer"] == default_reviewer), {}),
            ensure_ascii=False,
        )[:400]
    )


if __name__ == "__main__":
    main()
