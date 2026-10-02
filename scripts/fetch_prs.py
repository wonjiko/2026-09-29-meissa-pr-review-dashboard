"""Stage 2 - fetch every in-scope pull request with its reviews and review-request events.

Three passes, all writing verbatim responses under outputs/raw/prs/<repo>/:

  created   cursor paging over pullRequests(orderBy: CREATED_AT desc), stopped once
            createdAt falls before the window. CREATED_AT never changes, so the
            ordering is stable and nothing can slip between pages.
  backfill  PRs created before the window but touched inside it, enumerated by the
            search API and then fetched by number in aliased batches.
  overflow  per-PR cursor paging for reviews / timelineItems that exceeded one page.

timelineItems.totalCount is not trusted anywhere: it ignores the itemTypes filter.
Only pageInfo cursors drive paging.
"""

from __future__ import annotations

import json
import sys

import ghclient as gh

PR_FRAGMENT = """
fragment PRCore on PullRequest {
  number
  title
  url
  state
  isDraft
  createdAt
  updatedAt
  closedAt
  mergedAt
  additions
  deletions
  changedFiles
  author { login __typename }
  mergedBy { login }
  baseRefName
  reviewRequests(first: 50) {
    nodes {
      requestedReviewer {
        __typename
        ... on User { login }
        ... on Team { slug }
      }
    }
  }
  reviews(first: REVIEW_PAGE) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      author { login __typename }
      state
      submittedAt
      bodyText
      comments { totalCount }
    }
  }
  timelineItems(first: TIMELINE_PAGE, itemTypes: [REVIEW_REQUESTED_EVENT, REVIEW_REQUEST_REMOVED_EVENT, READY_FOR_REVIEW_EVENT, CONVERT_TO_DRAFT_EVENT]) {
    pageInfo { hasNextPage endCursor }
    nodes {
      __typename
      ... on ReviewRequestedEvent {
        createdAt
        actor { login }
        requestedReviewer { __typename ... on User { login } ... on Team { slug } }
      }
      ... on ReviewRequestRemovedEvent {
        createdAt
        actor { login }
        requestedReviewer { __typename ... on User { login } ... on Team { slug } }
      }
      ... on ReadyForReviewEvent { createdAt actor { login } }
      ... on ConvertToDraftEvent { createdAt actor { login } }
    }
  }
}
"""

CREATED_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  rateLimit { cost remaining resetAt }
  repository(owner:$owner, name:$name) {
    pullRequests(first: PR_PAGE, orderBy: {field: CREATED_AT, direction: DESC}, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes { ...PRCore }
    }
  }
}
"""

SEARCH_QUERY = """
query($q:String!, $cursor:String) {
  rateLimit { cost remaining resetAt }
  search(query:$q, type: ISSUE, first: 100, after: $cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { number } }
  }
}
"""

REVIEW_PAGE_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  rateLimit { cost remaining resetAt }
  repository(owner:$owner, name:$name) {
    pullRequest(number: NUMBER) {
      number
      reviews(first: REVIEW_PAGE, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          author { login __typename }
          state
          submittedAt
          bodyText
          comments { totalCount }
        }
      }
    }
  }
}
"""

TIMELINE_PAGE_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  rateLimit { cost remaining resetAt }
  repository(owner:$owner, name:$name) {
    pullRequest(number: NUMBER) {
      number
      timelineItems(first: TIMELINE_PAGE, after: $cursor, itemTypes: [REVIEW_REQUESTED_EVENT, REVIEW_REQUEST_REMOVED_EVENT, READY_FOR_REVIEW_EVENT, CONVERT_TO_DRAFT_EVENT]) {
        pageInfo { hasNextPage endCursor }
        nodes {
          __typename
          ... on ReviewRequestedEvent {
            createdAt
            actor { login }
            requestedReviewer { __typename ... on User { login } ... on Team { slug } }
          }
          ... on ReviewRequestRemovedEvent {
            createdAt
            actor { login }
            requestedReviewer { __typename ... on User { login } ... on Team { slug } }
          }
          ... on ReadyForReviewEvent { createdAt actor { login } }
          ... on ConvertToDraftEvent { createdAt actor { login } }
        }
      }
    }
  }
}
"""


def sized(template: str, cfg: dict, number: int | None = None) -> str:
    out = (
        template.replace("PR_PAGE", str(cfg["pr_page_size"]))
        .replace("REVIEW_PAGE", str(cfg["review_page_size"]))
        .replace("TIMELINE_PAGE", str(cfg["timeline_page_size"]))
    )
    if number is not None:
        out = out.replace("NUMBER", str(number))
    return out


def load_manifest() -> dict:
    path = gh.RAW / "meta" / "repos.json"
    if not path.exists():
        gh.log("outputs/raw/meta/repos.json missing - run fetch_repos.py first")
        sys.exit(1)
    return json.loads(path.read_text())


def fetch_created(cfg: dict, repo: str) -> tuple[int, list[tuple[int, str, str]]]:
    """Page newest-first until the window boundary. Returns (count, overflow queue)."""
    query = sized(CREATED_QUERY + PR_FRAGMENT, cfg)
    cutoff = cfg["window_start"] + "T00:00:00Z"
    owner, cursor, page, kept = cfg["org"], None, 0, 0
    overflow: list[tuple[int, str, str]] = []

    while True:
        payload = gh.graphql(query, {"owner": owner, "name": repo, "cursor": cursor})
        conn = payload["data"]["repository"]["pullRequests"]
        nodes = conn["nodes"]
        in_window = [n for n in nodes if n["createdAt"] >= cutoff]

        gh.save_raw(
            f"prs/{gh.safe_name(repo)}/created-{page:04d}.json",
            payload,
            {"pass": "created", "repo": repo, "cursor": cursor, "page": page},
        )
        kept += len(in_window)
        overflow += collect_overflow(repo, in_window)

        if len(in_window) < len(nodes) or not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
        page += 1
        gh.BUDGET.guard()
    return kept, overflow


def search_numbers(cfg: dict, repo: str) -> list[int]:
    q = f"repo:{cfg['org']}/{repo} is:pr updated:{cfg['window_start']}..{cfg['window_end']} created:<{cfg['window_start']}"
    numbers: list[int] = []
    cursor, page = None, 0
    while True:
        payload = gh.graphql(SEARCH_QUERY, {"q": q, "cursor": cursor})
        gh.save_raw(
            f"prs/{gh.safe_name(repo)}/backfill-search-{page:04d}.json",
            payload,
            {"pass": "backfill-search", "repo": repo, "query": q, "cursor": cursor},
        )
        conn = payload["data"]["search"]
        numbers += [n["number"] for n in conn["nodes"] if n]
        if not conn["pageInfo"]["hasNextPage"]:
            if conn["issueCount"] > 1000:
                gh.log(f"  WARNING {repo}: backfill search hit the 1000-result cap ({conn['issueCount']})")
            break
        cursor = conn["pageInfo"]["endCursor"]
        page += 1
    return numbers


def fetch_by_numbers(cfg: dict, repo: str, numbers: list[int]) -> list[tuple[int, str, str]]:
    overflow: list[tuple[int, str, str]] = []
    batch_size = cfg["alias_batch_size"]
    for bi in range(0, len(numbers), batch_size):
        chunk = numbers[bi : bi + batch_size]
        aliases = "\n    ".join(f"p{n}: pullRequest(number: {n}) {{ ...PRCore }}" for n in chunk)
        query = sized(
            "query($owner:String!, $name:String!) {\n"
            "  rateLimit { cost remaining resetAt }\n"
            "  repository(owner:$owner, name:$name) {\n"
            f"    {aliases}\n"
            "  }\n}\n" + PR_FRAGMENT,
            cfg,
        )
        payload = gh.graphql(query, {"owner": cfg["org"], "name": repo})
        gh.save_raw(
            f"prs/{gh.safe_name(repo)}/backfill-{bi // batch_size:04d}.json",
            payload,
            {"pass": "backfill", "repo": repo, "numbers": chunk},
        )
        repo_node = payload["data"]["repository"] or {}
        nodes = [v for k, v in repo_node.items() if k.startswith("p") and isinstance(v, dict)]
        overflow += collect_overflow(repo, nodes)
        gh.BUDGET.guard()
    return overflow


def collect_overflow(repo: str, nodes: list[dict]) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for node in nodes:
        if not node:
            continue
        for field in ("reviews", "timelineItems"):
            info = (node.get(field) or {}).get("pageInfo") or {}
            if info.get("hasNextPage"):
                out.append((node["number"], field, info["endCursor"]))
    return out


def fetch_overflow(cfg: dict, repo: str, queue: list[tuple[int, str, str]]) -> None:
    for number, field, cursor in queue:
        template = REVIEW_PAGE_QUERY if field == "reviews" else TIMELINE_PAGE_QUERY
        query = sized(template, cfg, number=number)
        page = 0
        while cursor:
            payload = gh.graphql(query, {"owner": cfg["org"], "name": repo, "cursor": cursor})
            gh.save_raw(
                f"prs/{gh.safe_name(repo)}/pr-{number}-{field}-{page:03d}.json",
                payload,
                {"pass": "overflow", "repo": repo, "number": number, "field": field, "cursor": cursor},
            )
            conn = (payload["data"]["repository"]["pullRequest"] or {}).get(field) or {}
            info = conn.get("pageInfo") or {}
            cursor = info["endCursor"] if info.get("hasNextPage") else None
            page += 1
            gh.BUDGET.guard()


def main() -> None:
    cfg = gh.load_config()
    manifest = load_manifest()
    only = set(sys.argv[1:])
    repos = [r for r in manifest["repos"] if r["in_scope"] and (not only or r["name"] in only)]
    gh.log(f"fetching {len(repos)} repositories")

    stats = []
    for idx, repo in enumerate(repos, 1):
        name = repo["name"]
        gh.log(f"{idx}/{len(repos)} {name}")
        created, overflow = fetch_created(cfg, name)

        numbers = search_numbers(cfg, name) if repo["expected_updated_backfill"] else []
        if numbers:
            overflow += fetch_by_numbers(cfg, name, numbers)

        if overflow:
            gh.log(f"  {len(overflow)} overflow page chains")
            fetch_overflow(cfg, name, overflow)

        stats.append(
            {
                "repo": name,
                "created_in_window": created,
                "expected_created_in_window": repo["expected_created_in_window"],
                "backfill_fetched": len(numbers),
                "expected_updated_backfill": repo["expected_updated_backfill"],
                "overflow_chains": len(overflow),
            }
        )
        gh.log(f"  {created} created (expected {repo['expected_created_in_window']}), {len(numbers)} backfill")

    out = gh.RAW / "meta" / "fetch_stats.json"
    out.write_text(
        json.dumps(
            {"_meta": {"generated_at": gh.utcnow(), "rate": gh.BUDGET.summary()}, "repos": stats},
            ensure_ascii=False,
            indent=1,
        )
    )
    gh.log(f"done. rate: {gh.BUDGET.summary()}")


if __name__ == "__main__":
    main()
