"""GitHub GraphQL/REST access through the `gh` CLI, plus raw-response persistence.

Every remote response is written to raw/ verbatim together with a `_meta` block so
that every later stage can be rebuilt from disk without touching the network.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
BUILD = ROOT / "build"
DASHBOARD = ROOT / "dashboard"
CONFIG_PATH = ROOT / "config.json"


def load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text())
    if not cfg.get("window_end"):
        cfg["window_end"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    return cfg


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


class RateBudget:
    """Tracks the rateLimit block GitHub returns on every GraphQL response."""

    def __init__(self) -> None:
        self.cost = 0
        self.requests = 0
        self.remaining: int | None = None
        self.reset_at: str | None = None

    def observe(self, payload: dict) -> None:
        self.requests += 1
        rl = (payload.get("data") or {}).get("rateLimit") or {}
        if rl:
            self.cost += rl.get("cost") or 0
            self.remaining = rl.get("remaining")
            self.reset_at = rl.get("resetAt")

    def guard(self, floor: int = 200) -> None:
        if self.remaining is not None and self.remaining < floor:
            log(f"rate limit low ({self.remaining}); sleeping 60s")
            time.sleep(60)

    def summary(self) -> dict:
        return {
            "requests": self.requests,
            "points_spent": self.cost,
            "points_remaining": self.remaining,
            "reset_at": self.reset_at,
        }


BUDGET = RateBudget()


class GraphQLError(RuntimeError):
    pass


def graphql(query: str, variables: dict[str, Any] | None = None, *, attempts: int = 4) -> dict:
    """Run one GraphQL query. Variables are passed as argv values, never as files."""
    argv = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in (variables or {}).items():
        if value is None:
            continue
        argv += ["-f", f"{key}={value}"]

    last_err = ""
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(argv, capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            payload = json.loads(proc.stdout)
            errors = payload.get("errors") or []
            fatal = [e for e in errors if e.get("type") not in {"NOT_FOUND"}]
            if fatal and not payload.get("data"):
                last_err = json.dumps(errors)[:500]
            else:
                BUDGET.observe(payload)
                if errors:
                    log(f"partial errors: {json.dumps(errors)[:300]}")
                return payload
        else:
            last_err = (proc.stderr or proc.stdout)[:500]
        if attempt < attempts:
            backoff = 3 * attempt
            log(f"graphql attempt {attempt} failed, retrying in {backoff}s: {last_err[:200]}")
            time.sleep(backoff)
    raise GraphQLError(last_err)


def rest(path: str, *, paginate: bool = False, jq: str | None = None) -> Any:
    argv = ["gh", "api", path]
    if paginate:
        argv.append("--paginate")
    if jq:
        argv += ["--jq", jq]
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        raise GraphQLError((proc.stderr or proc.stdout)[:500])
    out = proc.stdout.strip()
    if jq:
        return [line for line in out.splitlines() if line]
    return json.loads(out)


def save_raw(relpath: str, payload: dict, meta: dict) -> Path:
    target = RAW / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "_meta": {"fetched_at": utcnow(), **meta},
        "response": payload,
    }
    target.write_text(json.dumps(body, ensure_ascii=False, indent=1))
    return target


def load_raw(relpath: str) -> dict:
    return json.loads((RAW / relpath).read_text())


def iter_raw(pattern: str):
    for path in sorted(RAW.glob(pattern)):
        yield path, json.loads(path.read_text())


def safe_name(name: str) -> str:
    return name.replace("/", "__")
