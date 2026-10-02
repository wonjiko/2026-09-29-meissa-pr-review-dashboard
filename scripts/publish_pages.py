"""Optional stage - publish outputs/dashboard/index.html to the gh-pages branch.

The dashboard is a single self-contained HTML file, so a Pages site is just that file
committed to a branch. Nothing is built on GitHub's side: the pipeline runs locally
(it needs `gh` credentials and org read access that no public runner should hold) and
only the finished page is published.

The commit is written with git plumbing - hash-object / mktree / commit-tree - so the
working tree and the checked-out branch are never touched, and each publish is an
ordinary child of the previous gh-pages commit. That keeps the push a fast-forward, so
no force-push is needed.

    python3 scripts/publish_pages.py --dry-run    show what would be published
    python3 scripts/publish_pages.py              commit + push gh-pages
    python3 scripts/publish_pages.py --enable     also turn the Pages site on

The page is published to config.json's `publish_repo` when set, otherwise to origin.
A separate page-only repository is needed here for two reasons: GitHub Pages is not
available for a private repository on a Free plan, and a page-only repository serves the
dashboard without also publishing the scripts, the config and the turn log.

WARNING: a Pages site is PUBLIC. --enable is the step that exposes the page, which is
why it is a separate flag.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import ghclient as gh  # noqa: E402

BRANCH = "gh-pages"


def git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(gh.ROOT), *args],
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "GIT_TERMINAL_PROMPT": "0",
            # macOS keychain helper intermittently fails with -25320 and git then blocks
            # waiting for a username; hand it the gh token instead of hanging.
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "!gh auth git-credential",
        },
    )
    if check and proc.returncode != 0:
        gh.log(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        sys.exit(1)
    return proc.stdout.strip()


def remote_slug() -> tuple[str, str]:
    url = git("remote", "get-url", "origin")
    slug = url.removesuffix(".git").split("github.com")[-1].lstrip(":/")
    owner, _, repo = slug.partition("/")
    if not owner or not repo:
        gh.log(f"could not read owner/repo from origin url: {url}")
        sys.exit(1)
    return owner, repo


def blob(path_on_disk) -> str:
    return git("hash-object", "-w", "--", str(path_on_disk))


def resolve_target(flag: str | None) -> tuple[str, str, bool]:
    """Returns (owner, repo, is_origin) for the repository that serves the page.

    config.json's `publish_repo` lets the page live in a repository of its own, separate
    from the pipeline repository. That matters because GitHub Pages is unavailable for a
    private repository on a Free plan, and because a page-only repository publishes the
    dashboard without also publishing the scripts and the turn log.
    """
    origin_owner, origin_repo = remote_slug()
    slug = flag or gh.load_config().get("publish_repo")
    if not slug:
        return origin_owner, origin_repo, True
    owner, _, repo = slug.partition("/")
    if not owner or not repo:
        gh.log(f"publish_repo must be owner/repo, got: {slug!r}")
        sys.exit(1)
    return owner, repo, (owner, repo) == (origin_owner, origin_repo)


def ensure_repo(owner: str, repo: str) -> None:
    seen = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}"], capture_output=True, text=True
    )
    if seen.returncode == 0:
        visibility = "private" if json.loads(seen.stdout).get("private") else "public"
        gh.log(f"target repo exists: {owner}/{repo} ({visibility})")
        return
    made = subprocess.run(
        ["gh", "repo", "create", f"{owner}/{repo}", "--public", "--description",
         "CARTA-IS PR review dashboard - rendered page only"],
        capture_output=True, text=True,
    )
    if made.returncode != 0:
        gh.log(f"creating {owner}/{repo} failed: {made.stderr.strip()}")
        sys.exit(1)
    gh.log(f"created public repo {owner}/{repo}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--enable", action="store_true", help="also enable the Pages site (makes it public)")
    ap.add_argument("--target", help="owner/repo to publish to, overriding config publish_repo")
    args = ap.parse_args()

    page = gh.DASHBOARD / "index.html"
    if not page.exists():
        gh.log(f"{page.relative_to(gh.ROOT)} missing - run ./run.sh dashboard first")
        sys.exit(1)

    owner, repo, is_origin = resolve_target(args.target)
    size_kb = page.stat().st_size // 1024
    parent = git("rev-parse", "--verify", f"refs/heads/{BRANCH}", check=False)
    gh.log(f"publishing {page.relative_to(gh.ROOT)} ({size_kb} KB) to {owner}/{repo}@{BRANCH}")
    gh.log(f"parent commit: {parent or '(new branch)'}")

    if args.dry_run:
        live = site_state(owner, repo)
        gh.log(f"Pages site: {live.get('html_url') if live else 'not enabled'}")
        gh.log("dry run - nothing written")
        return

    # An empty .nojekyll stops GitHub running the page through Jekyll.
    nojekyll = gh.BUILD / ".nojekyll"
    nojekyll.write_text("")
    tree_spec = "\n".join([
        f"100644 blob {blob(page)}\tindex.html",
        f"100644 blob {blob(nojekyll)}\t.nojekyll",
    ])
    tree = subprocess.run(
        ["git", "-C", str(gh.ROOT), "mktree"], input=tree_spec + "\n",
        capture_output=True, text=True,
    )
    if tree.returncode != 0:
        gh.log(f"mktree failed: {tree.stderr.strip()}")
        sys.exit(1)
    tree_sha = tree.stdout.strip()

    unchanged = False
    if parent:
        existing = git("rev-parse", f"{parent}^{{tree}}", check=False)
        unchanged = existing == tree_sha

    if unchanged:
        gh.log("local page is already the gh-pages tip - no new commit")
        head = parent
    else:
        msg = f"dashboard {gh.utcnow()}"
        head = git("commit-tree", tree_sha, *(["-p", parent] if parent else []), "-m", msg)
        git("update-ref", f"refs/heads/{BRANCH}", head)
        gh.log(f"commit {head[:9]} on {BRANCH}")

    if not is_origin:
        ensure_repo(owner, repo)
    dest = "origin" if is_origin else f"https://github.com/{owner}/{repo}.git"

    # An unchanged local branch does not mean the target already serves it - a freshly
    # created page repo has no gh-pages at all - so compare against the target's tip.
    remote_tip = git("ls-remote", dest, f"refs/heads/{BRANCH}", check=False).split("\t")[0]
    if remote_tip == head:
        gh.log(f"{owner}/{repo}@{BRANCH} already at {head[:9]} - nothing to push")
    else:
        git("push", dest, f"refs/heads/{BRANCH}:refs/heads/{BRANCH}")
        gh.log(f"pushed {BRANCH} to {owner}/{repo}")

    # Enabling the site is independent of whether the content changed: an unchanged page
    # must still be able to turn a site on that is not yet serving.
    if not args.enable:
        # Report what the site is actually doing. Saying "NOT enabled" here is wrong once
        # the site exists -- the push has already replaced what it serves.
        live = site_state(owner, repo)
        if live is None:
            gh.log("branch published; Pages site NOT enabled (pass --enable to turn it on)")
        else:
            gh.log(f"branch published; site already serving: {live.get('html_url')} "
                   f"(status {live.get('status')})")
        return
    enable_site(owner, repo)


def site_state(owner: str, repo: str) -> dict | None:
    """The Pages site's current record, or None when no site exists for the repo."""
    got = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/pages"], capture_output=True, text=True
    )
    return json.loads(got.stdout) if got.returncode == 0 else None


def enable_site(owner: str, repo: str) -> None:
    live = site_state(owner, repo)
    if live is not None:
        gh.log(f"Pages already enabled: {live.get('html_url')}")
        return
    made = subprocess.run(
        ["gh", "api", "-X", "POST", f"repos/{owner}/{repo}/pages",
         "-f", "source[branch]=" + BRANCH, "-f", "source[path]=/"],
        capture_output=True, text=True,
    )
    if made.returncode != 0:
        # Pushing gh-pages to a public repo can auto-enable the site, so POST then races
        # with GitHub and returns 409. That is the wanted end state, not a failure.
        if "already enabled" in made.stdout:
            again = site_state(owner, repo)
            gh.log(f"Pages already enabled: {(again or {}).get('html_url', '?')}")
            return
        gh.log(f"enabling Pages failed: {made.stdout.strip() or made.stderr.strip()}")
        sys.exit(1)
    gh.log(f"Pages enabled: {json.loads(made.stdout).get('html_url')}")


if __name__ == "__main__":
    main()
