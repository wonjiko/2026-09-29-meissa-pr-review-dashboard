"""Append one turn entry to the progress log in CLAUDE.md.

    python3 scripts/log_turn.py "한 줄 요약" -d "세부 항목" -d "세부 항목" [--next "다음 할 일"]

Entries are inserted directly under the <!-- turn-log --> marker, newest last, so the
file stays append-only and nothing above the marker is touched.
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "CLAUDE.md"
MARKER = "<!-- turn-log -->"


def git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
        )
        return out.stdout.strip() or "(no commit)"
    except OSError:
        return "(no git)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("summary")
    ap.add_argument("-d", "--detail", action="append", default=[])
    ap.add_argument("--next", dest="next_step", default=None)
    args = ap.parse_args()

    text = DOC.read_text()
    if MARKER not in text:
        raise SystemExit(f"{MARKER} not found in {DOC}")

    head, _, tail = text.partition(MARKER)
    now_kst = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    existing = tail.count("\n### ")
    lines = [
        "",
        f"### #{existing + 1} · {now_kst.strftime('%Y-%m-%d %H:%M')} KST · `{git_head()}`",
        "",
        args.summary,
    ]
    if args.detail:
        lines.append("")
        lines += [f"- {d}" for d in args.detail]
    if args.next_step:
        lines += ["", f"다음: {args.next_step}"]

    DOC.write_text(head + MARKER + tail.rstrip("\n") + "\n" + "\n".join(lines) + "\n")
    print(f"logged turn #{existing + 1} to {DOC}")


if __name__ == "__main__":
    main()
