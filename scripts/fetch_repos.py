"""Stage 1 - enumerate org repositories and their in-window PR counts.

Writes outputs/raw/meta/repos.json. The per-repo `expected_created_in_window` count comes
from the search API and is the reference the verify stage checks the database against.
"""

from __future__ import annotations

import json

import ghclient as gh

REPO_QUERY = """
query($login:String!, $cursor:String) {
  rateLimit { cost remaining resetAt }
  organization(login:$login) {
    repositories(first: 50, after: $cursor, orderBy: {field: NAME, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        isArchived
        isPrivate
        isFork
        createdAt
        pushedAt
        primaryLanguage { name }
      }
    }
  }
}
"""

COUNT_QUERY = """
query($q:String!) {
  rateLimit { cost remaining resetAt }
  search(query:$q, type: ISSUE, first: 1) { issueCount }
}
"""


def fetch_repositories(org: str) -> list[dict]:
    repos: list[dict] = []
    cursor = None
    page = 0
    while True:
        payload = gh.graphql(REPO_QUERY, {"login": org, "cursor": cursor})
        gh.save_raw(f"meta/repos-page-{page:03d}.json", payload, {"query": "repositories", "org": org, "cursor": cursor})
        conn = payload["data"]["organization"]["repositories"]
        repos.extend(conn["nodes"])
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
        page += 1
    return repos


def count_prs(org: str, repo: str, start: str, end: str) -> dict:
    created_q = f"repo:{org}/{repo} is:pr created:{start}..{end}"
    updated_q = f"repo:{org}/{repo} is:pr updated:{start}..{end} created:<{start}"
    created = gh.graphql(COUNT_QUERY, {"q": created_q})
    updated = gh.graphql(COUNT_QUERY, {"q": updated_q})
    gh.save_raw(
        f"meta/counts/{gh.safe_name(repo)}.json",
        {"created": created, "updated_backfill": updated},
        {"query": "search issueCount", "created_q": created_q, "updated_q": updated_q},
    )
    return {
        "expected_created_in_window": created["data"]["search"]["issueCount"],
        "expected_updated_backfill": updated["data"]["search"]["issueCount"],
        "search_created_query": created_q,
        "search_updated_query": updated_q,
    }


def main() -> None:
    cfg = gh.load_config()
    org, start, end = cfg["org"], cfg["window_start"], cfg["window_end"]

    gh.log(f"listing repositories in {org}")
    repos = fetch_repositories(org)
    gh.log(f"{len(repos)} repositories")

    selected = []
    for idx, repo in enumerate(repos, 1):
        if repo["isArchived"] and not cfg["include_archived"]:
            continue
        counts = count_prs(org, repo["name"], start, end)
        record = {**repo, **counts}
        record["in_scope"] = (
            counts["expected_created_in_window"] > 0 or counts["expected_updated_backfill"] > 0
        )
        selected.append(record)
        if record["in_scope"]:
            gh.log(
                f"  {idx}/{len(repos)} {repo['name']}: "
                f"{counts['expected_created_in_window']} created, "
                f"{counts['expected_updated_backfill']} backfill"
            )
        gh.BUDGET.guard()

    manifest = {
        "_meta": {
            "generated_at": gh.utcnow(),
            "org": org,
            "window_start": start,
            "window_end": end,
            "include_archived": cfg["include_archived"],
            "rate": gh.BUDGET.summary(),
        },
        "repos": selected,
    }
    out = gh.RAW / "meta" / "repos.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))

    in_scope = [r for r in selected if r["in_scope"]]
    total = sum(r["expected_created_in_window"] for r in in_scope)
    backfill = sum(r["expected_updated_backfill"] for r in in_scope)
    gh.log(f"in scope: {len(in_scope)} repos, {total} created + {backfill} backfill PRs")
    gh.log(f"rate: {gh.BUDGET.summary()}")


if __name__ == "__main__":
    main()
