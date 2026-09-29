"""Stage 6 - render dashboard/index.html from dashboard/data.json.

The HTML is one self-contained file. data.json is embedded verbatim and carries the FACTS
(pull requests, review-request pairs, reviews) rather than one window's summary, so the page
re-aggregates for whatever date range the user selects. Nothing is precomputed into the
markup, so re-running aggregate.py + render.py is the only way the page changes.

The sticky control bar holds the reviewer picker and the date range, so both stay reachable
at any scroll position. The range defaults to the last `view_default_days` days ending today
and is clamped to the collection window; presets cover the last 7 / 30 / 90 days and the
whole collection.

data.json also carries a `reference` block: the same figures computed in Python from
facts.db for the full collection window. The page never displays it - check_render.mjs points
the page at that window and asserts the in-page engine reproduces it.
"""

from __future__ import annotations

import json

import ghclient as gh

TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #0f1115; --panel: #171a21; --panel2: #1e222b; --line: #2b3040;
    --fg: #e6e9ef; --dim: #9aa3b2; --accent: #5b9dff; --good: #3fb950;
    --warn: #d29922; --bad: #f85149; --pick: #a371f7;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg);
    font: 14px/1.5 -apple-system, "SF Pro Text", "Helvetica Neue", "Apple SD Gothic Neo", sans-serif; }
  header { padding: 22px 32px 14px; }
  h1 { margin: 0 0 6px; font-size: 20px; font-weight: 600; }
  .sub { color: var(--dim); font-size: 13px; }
  /* the picker and the date range must stay usable at any scroll position */
  .controls { position: sticky; top: 0; z-index: 30; background: var(--bg);
    border-bottom: 1px solid var(--line); padding: 10px 32px 12px;
    box-shadow: 0 6px 18px -12px #000; }
  .bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .bar label { color: var(--dim); font-size: 12px; }
  .bar .sep { color: var(--line); }
  select, input[type=date] { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
    border-radius: 8px; padding: 7px 10px; font: inherit; font-size: 13px; }
  select { min-width: 250px; }
  input[type=date] { width: 148px; }
  select:focus, input[type=date]:focus { outline: 2px solid var(--pick); outline-offset: 1px; }
  .chip { background: var(--panel2); border: 1px solid var(--line); border-radius: 999px;
    padding: 4px 11px; color: var(--dim); font-size: 12px; }
  .chip.warn { border-color: var(--warn); color: var(--warn); }
  main { padding: 22px 32px 64px; max-width: 1400px; }
  section { margin-bottom: 34px; }
  h2 { font-size: 15px; font-weight: 600; margin: 0 0 4px; }
  h2 .note { color: var(--dim); font-weight: 400; font-size: 12px; margin-left: 8px; }
  h3 { font-size: 13px; font-weight: 600; margin: 0 0 4px; color: var(--dim); }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(178px, 1fr)); gap: 12px; margin-top: 12px; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }
  .card .k { color: var(--dim); font-size: 12px; margin-bottom: 6px; }
  .card .v { font-size: 24px; font-weight: 600; letter-spacing: -0.5px; }
  .card .u { color: var(--dim); font-size: 12px; font-weight: 400; margin-left: 3px; }
  .card.hi { border-color: var(--pick); }
  table { width: 100%; border-collapse: collapse; background: var(--panel);
    border: 1px solid var(--line); border-radius: 10px; overflow: hidden; margin-top: 12px; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: right; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th { background: var(--panel2); color: var(--dim); font-weight: 500; font-size: 12px;
    position: sticky; top: 0; z-index: 5; cursor: pointer; user-select: none; }
  th:first-child, td:first-child { text-align: left; }
  td.txt, th.txt { text-align: left; white-space: normal; }
  tbody tr:hover { background: var(--panel2); }
  tr.picked { background: rgba(163,113,247,0.13); }
  tr.picked td:first-child { color: var(--pick); font-weight: 600; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  button.link { background: none; border: 0; color: var(--accent); font: inherit; cursor: pointer; padding: 0; }
  button.link:hover { text-decoration: underline; }
  .scroll { max-height: 460px; overflow: auto; border-radius: 10px; }
  .toggle { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
  .toggle button { background: var(--panel); color: var(--dim); border: 0; padding: 7px 12px;
    font: inherit; font-size: 12px; cursor: pointer; }
  .toggle button.on { background: var(--accent); color: #04070d; font-weight: 600; }
  .chart { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px; margin-top: 12px; }
  .legend { color: var(--dim); font-size: 12px; margin-top: 6px; display: flex; gap: 16px; flex-wrap: wrap; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 1000px) { .grid2 { grid-template-columns: 1fr; } }
  .null { color: var(--dim); }
  .empty { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    padding: 18px; color: var(--dim); margin-top: 12px; }
  footer { color: var(--dim); font-size: 12px; padding: 0 32px 40px; }
  code { background: var(--panel2); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
</style>
</head>
<body>
<header>
  <h1 id="title"></h1>
  <div class="sub" id="subtitle"></div>
</header>
<div class="controls">
  <div class="bar">
    <label for="pick">리뷰어</label>
    <select id="pick"></select>
    <label for="from">기간</label>
    <input type="date" id="from">
    <span class="sep">~</span>
    <input type="date" id="to">
    <div class="toggle" id="presets"></div>
    <span class="chip" id="rangeChip"></span>
    <span class="chip" id="basisChip"></span>
    <span class="chip" id="archChip"></span>
    <span class="chip" id="clampChip" style="display:none"></span>
  </div>
</div>
<main>
  <div id="reviewerSections"></div>
  <div id="orgSections"></div>
</main>
<footer id="footer"></footer>
<script type="application/json" id="payload">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('payload').textContent);
const F = D.facts;
const META = D.meta;

const el = (tag, attrs = {}, kids = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k === 'text') n.textContent = v;
    else if (k === 'on') Object.assign(n, v);
    else n.setAttribute(k, v);
  }
  for (const kid of [].concat(kids)) if (kid) n.appendChild(kid);
  return n;
};
const num = v => v === null || v === undefined ? '–' : (typeof v === 'number' ? v.toLocaleString() : v);
const pct = v => v === null || v === undefined ? '–' : (v * 100).toFixed(1) + '%';
const hrs = v => v === null || v === undefined ? '–' : (v >= 48 ? (v / 24).toFixed(1) + 'd' : v.toFixed(1) + 'h');

/* ================= aggregation engine =================
   Mirrors scripts/aggregate.py so any window can be summarised in the page. The Python
   figures for the full collection window ride along in D.reference purely so
   check_render.mjs can prove the two agree. */

const DAY = 86400;
const r2 = v => v === null || v === undefined ? null : Number(v.toFixed(2));
const r3 = v => v === null || v === undefined ? null : Number(v.toFixed(3));
const r4 = v => v === null || v === undefined ? null : Number(v.toFixed(4));
const r6 = v => v === null || v === undefined ? null : Number(v.toFixed(6));
// Python's round() breaks a tie to the even integer; Math.round() always goes up. The
// percentile index hits exact .5 often enough (any even-length sample at q=0.5) that the
// two disagree unless this is matched.
function pyRound(x) {
  const f = Math.floor(x), d = x - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}
function percentile(values, q) {
  if (!values.length) return null;
  const a = values.slice().sort((x, y) => x - y);
  const idx = Math.min(a.length - 1, Math.max(0, pyRound(q * (a.length - 1))));
  return r2(a[idx]);
}
const shareOf = (part, whole) => (part === null || part === undefined || !whole) ? null : r6(part / whole);
const mean = list => list.length ? r2(list.reduce((a, b) => a + b, 0) / list.length) : null;
const sumOf = list => list.reduce((a, b) => a + b, 0);
const iso = epoch => new Date(epoch * 1000).toISOString().replace('.000', '').slice(0, 19) + 'Z';
const dayKey = epoch => new Date(epoch * 1000).toISOString().slice(0, 10);
const dayStart = d => Math.floor(Date.parse(d + 'T00:00:00Z') / 1000);
const dayEnd = d => Math.floor(Date.parse(d + 'T23:59:59Z') / 1000);
const addDays = (d, n) => new Date(Date.parse(d + 'T00:00:00Z') + n * DAY * 1000).toISOString().slice(0, 10);

const SIZE_BUCKETS = F.size_buckets;
const SIZE_LABELS = SIZE_BUCKETS.map(b => b.label);
const LAT_BUCKETS = F.latency_buckets;
const SMALL_MAX = F.small_max_churn, LARGE_MIN = F.large_min_churn;

function sizeBucket(churn) {
  if (churn === null || churn === undefined) return null;
  for (const b of SIZE_BUCKETS) if (b.max_churn === null || churn <= b.max_churn) return b.label;
  return SIZE_LABELS[SIZE_LABELS.length - 1];
}

const REPO_NAME = F.repo_table, LOGIN = F.login_table;
const REPO_META = Object.fromEntries(F.repo_meta.map(m => [m.repo, m]));

const PR = [];
for (let i = 0; i < F.counts.prs; i++) {
  const add = F.prs.additions[i], del = F.prs.deletions[i];
  const churn = (add === null || del === null) ? null : add + del;
  PR.push({
    repo: REPO_NAME[F.prs.repo[i]], number: F.prs.number[i], author: LOGIN[F.prs.author[i]],
    created: F.prs.created[i], merged: F.prs.merged[i], closed: F.prs.closed[i],
    state: F.prs.state[i], additions: add, deletions: del,
    changed_files: F.prs.changed_files[i], draft: F.prs.draft[i], title: F.prs.title[i],
    churn, bucket: sizeBucket(churn),
    url: 'https://github.com/' + META.org + '/' + REPO_NAME[F.prs.repo[i]] + '/pull/' + F.prs.number[i],
  });
}
const keyOf = (repoIdx, number) => repoIdx * 10000000 + number;
const PR_BY_KEY = new Map();
for (let i = 0; i < F.counts.prs; i++) PR_BY_KEY.set(keyOf(F.prs.repo[i], F.prs.number[i]), PR[i]);

const PAIR = [];
for (let i = 0; i < F.counts.pairs; i++) {
  const pr = PR_BY_KEY.get(keyOf(F.pairs.repo[i], F.pairs.number[i]));
  const requested = F.pairs.requested[i], firstAfter = F.pairs.first_after[i];
  PAIR.push({
    pr, reviewer: LOGIN[F.pairs.reviewer[i]], requested,
    removed: F.pairs.removed[i], firstReview: F.pairs.first_review[i], firstAfter,
    pending: F.pairs.pending_snapshot[i] === 1,
    reviewed: F.pairs.first_review[i] !== null,
    latency: (requested !== null && firstAfter !== null) ? r3((firstAfter - requested) / 3600) : null,
  });
}

const REVIEW = [];
for (let i = 0; i < F.counts.reviews; i++) {
  REVIEW.push({
    pr: PR_BY_KEY.get(keyOf(F.reviews.repo[i], F.reviews.number[i])),
    author: LOGIN[F.reviews.author[i]], at: F.reviews.at[i], state: F.reviews.state[i],
    inline_comments: F.reviews.inline_comments[i], body_len: F.reviews.body_len[i],
  });
}

/* ---- one window's slice of the facts ---- */
function buildScope(fromDate, toDate) {
  const lo = dayStart(fromDate), hi = dayEnd(toDate);
  const prs = PR.filter(p => p.created !== null && p.created >= lo && p.created <= hi);
  const inScope = new Set(prs);
  const pairs = PAIR.filter(p => p.pr && inScope.has(p.pr));
  const reviews = REVIEW.filter(r => r.pr && inScope.has(r.pr));
  const reviewsByPr = new Map();
  for (const r of reviews) {
    if (!reviewsByPr.has(r.pr)) reviewsByPr.set(r.pr, []);
    reviewsByPr.get(r.pr).push(r);
  }
  const churns = prs.filter(p => p.churn !== null).map(p => p.churn);
  return {
    from: fromDate, to: toDate, lo, hi, prs, pairs, reviews, reviewsByPr,
    totalChurn: sumOf(churns),
    totalFiles: sumOf(prs.map(p => p.changed_files || 0)),
    churns,
  };
}

function reviewerTable(S) {
  const by = new Map();
  const slot = login => {
    if (!by.has(login)) by.set(login, {
      reviewer: login, requested_prs: 0, fulfilled_prs: 0, outstanding_open: 0,
      merged_without_review: 0, latencies: [], reviews_given: 0, reviewedPrs: new Set(),
      inline_comments: 0, approved: 0, changes_requested: 0, commented: 0, dismissed: 0,
      substantive: 0, unsolicited: new Set(), requested_churn: 0, fulfilled_churn: 0,
      reviewedChurn: new Map(), latSmall: [], latLarge: [],
    });
    return by.get(login);
  };
  const requestedKeys = new Set();
  for (const p of S.pairs) {
    const s = slot(p.reviewer);
    s.requested_prs += 1;
    requestedKeys.add(p.pr.repo + '#' + p.pr.number + '@' + p.reviewer);
    if (p.pr.churn !== null) s.requested_churn += p.pr.churn;
    if (p.reviewed) {
      s.fulfilled_prs += 1;
      if (p.pr.churn !== null) s.fulfilled_churn += p.pr.churn;
    } else {
      if (p.pr.state === 'OPEN') s.outstanding_open += 1;
      if (p.pr.merged !== null) s.merged_without_review += 1;
    }
    if (p.latency !== null) {
      s.latencies.push(p.latency);
      if (p.pr.churn !== null && p.pr.churn <= SMALL_MAX) s.latSmall.push(p.latency);
      else if (p.pr.churn !== null && p.pr.churn >= LARGE_MIN) s.latLarge.push(p.latency);
    }
  }
  for (const r of S.reviews) {
    const s = slot(r.author);
    s.reviews_given += 1;
    s.reviewedPrs.add(r.pr);
    s.reviewedChurn.set(r.pr, r.pr.churn);
    s.inline_comments += r.inline_comments;
    if (r.state === 'APPROVED') s.approved += 1;
    else if (r.state === 'CHANGES_REQUESTED') s.changes_requested += 1;
    else if (r.state === 'COMMENTED') s.commented += 1;
    else if (r.state === 'DISMISSED') s.dismissed += 1;
    if (r.inline_comments > 0 || r.body_len > 0) s.substantive += 1;
    if (!requestedKeys.has(r.pr.repo + '#' + r.pr.number + '@' + r.author)) s.unsolicited.add(r.pr);
  }
  const rows = [];
  for (const [login, s] of by) {
    const revChurn = [...s.reviewedChurn.values()].filter(v => v !== null);
    const verdicts = s.approved + s.changes_requested;
    const small = percentile(s.latSmall, 0.5), large = percentile(s.latLarge, 0.5);
    rows.push({
      reviewer: login,
      requested_prs: s.requested_prs,
      fulfilled_prs: s.fulfilled_prs,
      response_rate: s.requested_prs ? r4(s.fulfilled_prs / s.requested_prs) : null,
      outstanding_open: s.outstanding_open,
      merged_without_review: s.merged_without_review,
      merged_without_review_rate: s.requested_prs ? r4(s.merged_without_review / s.requested_prs) : null,
      reviews_given: s.reviews_given,
      reviewed_prs: s.reviewedPrs.size,
      latency_p50_h: percentile(s.latencies, 0.5),
      latency_p90_h: percentile(s.latencies, 0.9),
      latency_mean_h: mean(s.latencies),
      latency_samples: s.latencies.length,
      inline_comments: s.inline_comments,
      comments_per_review: s.reviews_given ? r2(s.inline_comments / s.reviews_given) : null,
      substantive_review_rate: s.reviews_given ? r4(s.substantive / s.reviews_given) : null,
      approved: s.approved,
      changes_requested: s.changes_requested,
      commented: s.commented,
      dismissed: s.dismissed,
      verdicts,
      approve_rate: verdicts ? r4(s.approved / verdicts) : null,
      changes_rate: verdicts ? r4(s.changes_requested / verdicts) : null,
      changes_per_100_reviews: s.reviews_given ? r2(s.changes_requested * 100 / s.reviews_given) : null,
      unsolicited_prs: s.unsolicited.size,
      requested_churn: s.requested_churn,
      requested_churn_share: shareOf(s.requested_churn, S.totalChurn),
      fulfilled_churn: s.fulfilled_churn,
      churn_response_rate: s.requested_churn ? r4(s.fulfilled_churn / s.requested_churn) : null,
      reviewed_churn: revChurn.length ? sumOf(revChurn) : null,
      reviewed_churn_share: revChurn.length ? shareOf(sumOf(revChurn), S.totalChurn) : null,
      reviewed_churn_p50: percentile(revChurn, 0.5),
      reviewed_churn_mean: revChurn.length ? r2(sumOf(revChurn) / revChurn.length) : null,
      latency_small_p50_h: small,
      latency_large_p50_h: large,
      latency_size_gap_h: (small !== null && large !== null) ? r2(large - small) : null,
      latency_small_samples: s.latSmall.length,
      latency_large_samples: s.latLarge.length,
    });
  }
  rows.sort((a, b) => (b.reviews_given - a.reviews_given) || (b.requested_prs - a.requested_prs));
  return rows;
}

function sizeOverview(S) {
  const pairsByBucket = new Map(SIZE_LABELS.map(l => [l, []]));
  for (const p of S.pairs) if (p.pr.bucket) pairsByBucket.get(p.pr.bucket).push(p);
  const buckets = SIZE_LABELS.map(label => {
    const band = S.prs.filter(p => p.bucket === label);
    const bandReviews = band.flatMap(p => S.reviewsByPr.get(p) || []);
    const reviewedPrs = band.filter(p => (S.reviewsByPr.get(p) || []).length).length;
    const merged = band.filter(p => p.merged !== null).length;
    const mergedUnreviewed = band.filter(p => p.merged !== null && !(S.reviewsByPr.get(p) || []).length).length;
    const lats = pairsByBucket.get(label).filter(p => p.latency !== null).map(p => p.latency);
    const approved = bandReviews.filter(r => r.state === 'APPROVED').length;
    const changes = bandReviews.filter(r => r.state === 'CHANGES_REQUESTED').length;
    const bandChurn = sumOf(band.filter(p => p.churn !== null).map(p => p.churn));
    const bandFiles = sumOf(band.map(p => p.changed_files || 0));
    const comments = sumOf(bandReviews.map(r => r.inline_comments));
    return {
      bucket: label, prs: band.length, prs_share: shareOf(band.length, S.prs.length),
      churn: bandChurn, churn_share: shareOf(bandChurn, S.totalChurn),
      changed_files: bandFiles, changed_files_share: shareOf(bandFiles, S.totalFiles),
      churn_p50: percentile(band.filter(p => p.churn !== null).map(p => p.churn), 0.5),
      files_p50: percentile(band.filter(p => p.changed_files !== null).map(p => p.changed_files), 0.5),
      merged, reviewed_prs: reviewedPrs, review_coverage: shareOf(reviewedPrs, band.length),
      merged_without_review: mergedUnreviewed,
      merged_without_review_rate: shareOf(mergedUnreviewed, merged),
      reviews: bandReviews.length,
      reviews_per_pr: band.length ? r2(bandReviews.length / band.length) : null,
      inline_comments: comments,
      comments_per_pr: band.length ? r2(comments / band.length) : null,
      latency_p50_h: percentile(lats, 0.5), latency_p90_h: percentile(lats, 0.9),
      latency_samples: lats.length,
      approved, changes_requested: changes, verdicts: approved + changes,
      changes_rate: shareOf(changes, approved + changes),
      approve_rate: shareOf(approved, approved + changes),
    };
  });
  const ordered = S.churns.slice().sort((a, b) => b - a);
  const top10 = ordered.length ? ordered.slice(0, Math.max(1, Math.floor(ordered.length / 10))) : [];
  const approvedAll = S.reviews.filter(r => r.state === 'APPROVED').length;
  const changesAll = S.reviews.filter(r => r.state === 'CHANGES_REQUESTED').length;
  const files = S.prs.filter(p => p.changed_files !== null).map(p => p.changed_files);
  return {
    buckets, bucket_labels: SIZE_LABELS, small_max_churn: SMALL_MAX, large_min_churn: LARGE_MIN,
    totals: {
      prs: S.prs.length, churn: S.totalChurn,
      additions: sumOf(S.prs.map(p => p.additions || 0)),
      deletions: sumOf(S.prs.map(p => p.deletions || 0)),
      changed_files: S.totalFiles,
      churn_missing_prs: S.prs.filter(p => p.churn === null).length,
      churn_stats: {
        n: S.churns.length, sum: S.churns.length ? S.totalChurn : null,
        mean: S.churns.length ? r2(S.totalChurn / S.churns.length) : null,
        p50: percentile(S.churns, 0.5), p90: percentile(S.churns, 0.9),
        max: S.churns.length ? Math.max(...S.churns) : null,
      },
      files_stats: {
        n: files.length, sum: files.length ? sumOf(files) : null,
        mean: files.length ? r2(sumOf(files) / files.length) : null,
        p50: percentile(files, 0.5), p90: percentile(files, 0.9),
        max: files.length ? Math.max(...files) : null,
      },
      churn_p25: percentile(S.churns, 0.25),
      churn_p75: percentile(S.churns, 0.75),
      churn_p99: percentile(S.churns, 0.99),
      top_decile_churn_share: shareOf(sumOf(top10), S.totalChurn),
      approved: approvedAll, changes_requested: changesAll, verdicts: approvedAll + changesAll,
      changes_rate: shareOf(changesAll, approvedAll + changesAll),
    },
  };
}

function repoRows(S) {
  const byRepo = new Map();
  for (const p of S.prs) {
    if (!byRepo.has(p.repo)) byRepo.set(p.repo, []);
    byRepo.get(p.repo).push(p);
  }
  const pairsByRepo = new Map();
  for (const p of S.pairs) {
    if (!pairsByRepo.has(p.pr.repo)) pairsByRepo.set(p.pr.repo, []);
    pairsByRepo.get(p.pr.repo).push(p);
  }
  const rows = [];
  for (const [name, created] of byRepo) {
    const meta = REPO_META[name] || {};
    const churns = created.filter(p => p.churn !== null).map(p => p.churn);
    const repoChurn = sumOf(churns);
    const repoFiles = sumOf(created.map(p => p.changed_files || 0));
    const reviews = created.flatMap(p => S.reviewsByPr.get(p) || []);
    const reviewedPrs = created.filter(p => (S.reviewsByPr.get(p) || []).length).length;
    const lats = (pairsByRepo.get(name) || []).filter(p => p.latency !== null).map(p => p.latency);
    const approved = reviews.filter(r => r.state === 'APPROVED').length;
    const changes = reviews.filter(r => r.state === 'CHANGES_REQUESTED').length;
    const prsShare = shareOf(created.length, S.prs.length);
    const churnShare = shareOf(repoChurn, S.totalChurn);
    const mix = Object.fromEntries(SIZE_LABELS.map(l => [l, 0]));
    for (const p of created) if (p.bucket) mix[p.bucket] += 1;
    const large = churns.filter(c => c >= LARGE_MIN).length;
    rows.push({
      repo: name, is_archived: !!meta.is_archived, language: meta.language ?? null,
      prs_created: created.length, prs_share: prsShare,
      prs_merged: created.filter(p => p.merged !== null).length,
      prs_open: created.filter(p => p.state === 'OPEN').length,
      prs_closed_unmerged: created.filter(p => p.state === 'CLOSED').length,
      distinct_authors: new Set(created.map(p => p.author)).size,
      expected_created_in_window: meta.expected_created_in_window ?? null,
      churn: repoChurn, churn_share: churnShare,
      additions: sumOf(created.map(p => p.additions || 0)),
      deletions: sumOf(created.map(p => p.deletions || 0)),
      changed_files: repoFiles, changed_files_share: shareOf(repoFiles, S.totalFiles),
      churn_p50: percentile(churns, 0.5), churn_p90: percentile(churns, 0.9),
      churn_mean: churns.length ? r2(repoChurn / churns.length) : null,
      churn_max: churns.length ? Math.max(...churns) : null,
      weight_index: (churnShare && prsShare) ? r2(churnShare / prsShare) : null,
      large_prs: large, large_pr_rate: shareOf(large, churns.length),
      size_mix: SIZE_LABELS.map(l => ({ bucket: l, prs: mix[l] })),
      reviewed_prs: reviewedPrs, review_coverage: shareOf(reviewedPrs, created.length),
      reviews: reviews.length,
      latency_p50_h: percentile(lats, 0.5), latency_p90_h: percentile(lats, 0.9),
      latency_samples: lats.length,
      approved, changes_requested: changes, verdicts: approved + changes,
      changes_rate: shareOf(changes, approved + changes),
      inline_comments: sumOf(reviews.map(r => r.inline_comments)),
      comments_per_pr: created.length ? r2(sumOf(reviews.map(r => r.inline_comments)) / created.length) : null,
    });
  }
  rows.sort((a, b) => b.prs_created - a.prs_created);
  return rows;
}

function authorRows(S) {
  const by = new Map();
  for (const p of S.prs) {
    if (!by.has(p.author)) by.set(p.author, []);
    by.get(p.author).push(p);
  }
  const rows = [];
  for (const [author, list] of by) {
    const churns = list.filter(p => p.churn !== null).map(p => p.churn);
    const churn = sumOf(churns);
    const prsShare = shareOf(list.length, S.prs.length);
    const churnShare = shareOf(churn, S.totalChurn);
    rows.push({
      author, prs_created: list.length, prs_share: prsShare,
      churn: churn || null, churn_share: churnShare,
      churn_p50: percentile(churns, 0.5),
      churn_mean: churns.length ? r2(churn / churns.length) : null,
      changed_files: sumOf(list.map(p => p.changed_files || 0)) || null,
      weight_index: (churn && list.length && churnShare && prsShare) ? r2(churnShare / prsShare) : null,
    });
  }
  rows.sort((a, b) => b.prs_created - a.prs_created);
  return rows;
}

function bulkEvidence(S) {
  const perPr = new Map();
  for (const p of S.pairs) {
    if (!perPr.has(p.pr)) perPr.set(p.pr, []);
    perPr.get(p.pr).push(p);
  }
  const sizes = [], delays = [];
  for (const [pr, list] of perPr) {
    sizes.push(list.length);
    const first = Math.min(...list.map(p => p.requested));
    delays.push(r3((first - pr.created) / 3600));
  }
  const dist = new Map();
  for (const s of sizes) dist.set(s, (dist.get(s) || 0) + 1);
  return {
    prs_with_requests: sizes.length,
    reviewers_per_pr_mean: sizes.length ? r2(sumOf(sizes) / sizes.length) : null,
    reviewers_per_pr_p50: percentile(sizes, 0.5),
    reviewers_per_pr_distribution: [...dist.keys()].sort((a, b) => a - b).map(k => ({ reviewers: k, prs: dist.get(k) })),
    first_request_delay_p50_h: percentile(delays, 0.5),
    first_request_delay_p90_h: percentile(delays, 0.9),
  };
}

/* Daily series - one point per calendar day in the selected range (UTC). */
function dailyDays(S) {
  const out = [];
  for (let d = S.from; d <= S.to; d = addDays(d, 1)) out.push(d);
  return out.length <= 400 ? out : out.filter((_, i) => i % Math.ceil(out.length / 400) === 0);
}

function dailyVolume(S, days) {
  const created = new Map(), merged = new Map(), reviews = new Map();
  const bump = (m, k) => m.set(k, (m.get(k) || 0) + 1);
  for (const p of S.prs) {
    bump(created, dayKey(p.created));
    if (p.merged !== null && p.merged >= S.lo && p.merged <= S.hi) bump(merged, dayKey(p.merged));
  }
  for (const r of S.reviews) if (r.at >= S.lo && r.at <= S.hi) bump(reviews, dayKey(r.at));
  return days.map(d => ({
    day: d, prs_created: created.get(d) || 0, prs_merged: merged.get(d) || 0, reviews: reviews.get(d) || 0,
  }));
}

function backlogDaily(S, reviewer, days) {
  const pairs = S.pairs.filter(p => p.reviewer === reviewer);
  const requested = new Map(), firsts = new Map();
  const bump = (m, k) => m.set(k, (m.get(k) || 0) + 1);
  for (const p of pairs) {
    if (p.requested !== null) bump(requested, dayKey(p.requested));
    if (p.firstReview !== null) bump(firsts, dayKey(p.firstReview));
  }
  return days.map(d => {
    const edge = dayEnd(d);
    let outstanding = 0;
    for (const p of pairs) {
      if (p.requested === null || p.requested > edge) continue;
      if (p.firstReview !== null && p.firstReview <= edge) continue;
      if (p.removed !== null && p.removed <= edge) continue;
      if (p.pr.closed !== null && p.pr.closed <= edge) continue;
      outstanding += 1;
    }
    return { day: d, outstanding, requested: requested.get(d) || 0, first_reviews: firsts.get(d) || 0 };
  });
}

function reviewerDetail(S, reviewer) {
  const pairs = S.pairs.filter(p => p.reviewer === reviewer);
  const ownReviews = S.reviews.filter(r => r.author === reviewer);
  const ownByPr = new Map();
  for (const r of ownReviews) {
    if (!ownByPr.has(r.pr)) ownByPr.set(r.pr, []);
    ownByPr.get(r.pr).push(r);
  }

  const byRepo = new Map();
  for (const p of pairs) {
    if (!byRepo.has(p.pr.repo)) byRepo.set(p.pr.repo, {
      repo: p.pr.repo, requested: 0, reviewed: 0, outstanding_open: 0,
      merged_without_review: 0, requested_churn: 0, reviewed_churn: 0, lat: [],
    });
    const s = byRepo.get(p.pr.repo);
    s.requested += 1;
    if (p.pr.churn !== null) s.requested_churn += p.pr.churn;
    if (p.reviewed) {
      s.reviewed += 1;
      if (p.pr.churn !== null) s.reviewed_churn += p.pr.churn;
    } else {
      if (p.pr.state === 'OPEN') s.outstanding_open += 1;
      if (p.pr.merged !== null) s.merged_without_review += 1;
    }
    if (p.latency !== null) s.lat.push(p.latency);
  }
  const reviewerChurn = sumOf([...byRepo.values()].map(s => s.requested_churn));
  const repoTotals = new Map();
  for (const p of S.prs) repoTotals.set(p.repo, (repoTotals.get(p.repo) || 0) + 1);
  const repoList = [...byRepo.values()].map(s => ({
    repo: s.repo, requested: s.requested, reviewed: s.reviewed,
    outstanding_open: s.outstanding_open, merged_without_review: s.merged_without_review,
    requested_churn: s.requested_churn, reviewed_churn: s.reviewed_churn,
    response_rate: s.requested ? r4(s.reviewed / s.requested) : null,
    churn_response_rate: s.requested_churn ? r4(s.reviewed_churn / s.requested_churn) : null,
    requested_churn_share: shareOf(s.requested_churn, reviewerChurn),
    churn_per_pr: s.requested ? r2(s.requested_churn / s.requested) : null,
    latency_p50_h: percentile(s.lat, 0.5),
    repo_prs_total: repoTotals.get(s.repo) || 0,
  })).sort((a, b) => b.requested - a.requested);

  const byAuthor = new Map();
  for (const p of pairs) {
    const who = p.pr.author;
    if (!byAuthor.has(who)) byAuthor.set(who, { author: who, requested: 0, reviewed: 0, requested_churn: 0, lat: [] });
    const s = byAuthor.get(who);
    s.requested += 1;
    if (p.pr.churn !== null) s.requested_churn += p.pr.churn;
    if (p.reviewed) s.reviewed += 1;
    if (p.latency !== null) s.lat.push(p.latency);
  }
  const authorList = [...byAuthor.values()].map(s => ({
    author: s.author, requested: s.requested, reviewed: s.reviewed,
    requested_churn: s.requested_churn,
    response_rate: s.requested ? r4(s.reviewed / s.requested) : null,
    requested_churn_share: shareOf(s.requested_churn, reviewerChurn),
    churn_per_pr: s.requested ? r2(s.requested_churn / s.requested) : null,
    latency_p50_h: percentile(s.lat, 0.5),
  })).sort((a, b) => b.requested - a.requested);

  const bySize = SIZE_LABELS.map(label => {
    const band = pairs.filter(p => p.pr.bucket === label);
    const bandReviews = band.flatMap(p => ownByPr.get(p.pr) || []);
    const lats = band.filter(p => p.latency !== null).map(p => p.latency);
    const churn = sumOf(band.filter(p => p.pr.churn !== null).map(p => p.pr.churn));
    const reviewed = band.filter(p => p.reviewed).length;
    const approved = bandReviews.filter(r => r.state === 'APPROVED').length;
    const changes = bandReviews.filter(r => r.state === 'CHANGES_REQUESTED').length;
    const comments = sumOf(bandReviews.map(r => r.inline_comments));
    return {
      bucket: label, requested: band.length, requested_share: shareOf(band.length, pairs.length),
      reviewed, response_rate: shareOf(reviewed, band.length),
      churn, churn_share: shareOf(churn, reviewerChurn),
      latency_p50_h: percentile(lats, 0.5), latency_p90_h: percentile(lats, 0.9),
      latency_samples: lats.length,
      reviews: bandReviews.length, inline_comments: comments,
      comments_per_review: bandReviews.length ? r2(comments / bandReviews.length) : null,
      approved, changes_requested: changes, verdicts: approved + changes,
      changes_rate: shareOf(changes, approved + changes),
      outstanding_open: band.filter(p => !p.reviewed && p.pr.state === 'OPEN').length,
      merged_without_review: band.filter(p => !p.reviewed && p.pr.merged !== null).length,
    };
  });

  const hist = LAT_BUCKETS.map(b => ({ bucket: b.label, count: 0 }));
  for (const p of pairs) {
    if (p.latency === null) continue;
    for (let i = 0; i < LAT_BUCKETS.length; i++) {
      if (LAT_BUCKETS[i].max_hours === null || p.latency <= LAT_BUCKETS[i].max_hours) { hist[i].count += 1; break; }
    }
  }

  const prRow = p => ({
    repo: p.pr.repo, number: p.pr.number, title: p.pr.title, url: p.pr.url,
    author: p.pr.author, churn: p.pr.churn, changed_files: p.pr.changed_files, bucket: p.pr.bucket,
  });
  const outstanding = pairs.filter(p => !p.reviewed && p.pr.state === 'OPEN').map(p => ({
    ...prRow(p), requested_at: iso(p.requested),
    waiting_hours: r3((S.hi - p.requested) / 3600), still_pending_snapshot: p.pending,
  })).sort((a, b) => b.waiting_hours - a.waiting_hours);
  const mergedUnreviewed = pairs.filter(p => !p.reviewed && p.pr.merged !== null).map(p => ({
    ...prRow(p), requested_at: iso(p.requested), merged_at: iso(p.pr.merged),
  })).sort((a, b) => (a.merged_at < b.merged_at ? 1 : -1));
  const heaviest = pairs.filter(p => p.pr.churn !== null).map(p => {
    const own = ownByPr.get(p.pr) || [];
    return {
      ...prRow(p), reviewed: p.reviewed, latency_hours: p.latency, reviews: own.length,
      inline_comments: sumOf(own.map(r => r.inline_comments)),
      verdict: own.slice().sort((a, b) => a.at - b.at)
        .map(r => r.state).find(s => s === 'APPROVED' || s === 'CHANGES_REQUESTED') || null,
    };
  }).sort((a, b) => b.churn - a.churn).slice(0, 30);

  return {
    reviewer, requested_churn: reviewerChurn,
    requested_churn_share: shareOf(reviewerChurn, S.totalChurn),
    by_repo: repoList, by_pr_author: authorList, by_size: bySize,
    latency_histogram: hist, heaviest_prs: heaviest,
    outstanding_open: outstanding, merged_without_review: mergedUnreviewed,
    review_state_mix: {
      approved: ownReviews.filter(r => r.state === 'APPROVED').length,
      changes_requested: ownReviews.filter(r => r.state === 'CHANGES_REQUESTED').length,
      commented: ownReviews.filter(r => r.state === 'COMMENTED').length,
      dismissed: ownReviews.filter(r => r.state === 'DISMISSED').length,
    },
  };
}

function scopeTotals(S) {
  return {
    repos_in_scope: new Set(S.prs.map(p => p.repo)).size,
    repos_archived_in_scope: new Set(S.prs.filter(p => (REPO_META[p.repo] || {}).is_archived).map(p => p.repo)).size,
    prs_created_in_window: S.prs.length,
    prs_merged: S.prs.filter(p => p.merged !== null).length,
    prs_open: S.prs.filter(p => p.state === 'OPEN').length,
    prs_closed_unmerged: S.prs.filter(p => p.state === 'CLOSED').length,
    prs_draft_now: S.prs.filter(p => p.draft === 1).length,
    human_reviews: S.reviews.length,
    review_request_pairs: S.pairs.length,
    distinct_reviewers: new Set(S.pairs.map(p => p.reviewer)).size,
    distinct_pr_authors: new Set(S.prs.map(p => p.author)).size,
    churn_total: S.totalChurn,
    changed_files_total: S.totalFiles,
    churn_per_pr_mean: S.prs.length ? r2(S.totalChurn / S.prs.length) : null,
  };
}

/* Everything the page draws for one window, in one object. Exposed on window so
   check_render.mjs can compute a window and compare it with D.reference. */
function computeView(fromDate, toDate) {
  const S = buildScope(fromDate, toDate);
  const days = dailyDays(S);
  return {
    scope: S, days, totals: scopeTotals(S), reviewers: reviewerTable(S),
    size_overview: sizeOverview(S), repos: repoRows(S), pr_authors: authorRows(S),
    bulk_request_evidence: bulkEvidence(S), daily_volume: dailyVolume(S, days),
    detail: login => reviewerDetail(S, login), backlog: login => backlogDaily(S, login, days),
  };
}
window.computeView = computeView;

/* ================= layout helpers ================= */
function section(host, title, note) {
  const s = el('section');
  s.appendChild(el('h2', {}, [
    el('span', { text: title }),
    note ? el('span', { class: 'note', text: note }) : null,
  ]));
  host.appendChild(s);
  return s;
}

function cards(host, items) {
  const wrap = el('div', { class: 'cards' });
  for (const it of items) {
    wrap.appendChild(el('div', { class: 'card' + (it.hi ? ' hi' : '') }, [
      el('div', { class: 'k', text: it.k }),
      el('div', { class: 'v', html: it.v + (it.u ? '<span class="u">' + it.u + '</span>' : '') }),
    ]));
  }
  host.appendChild(wrap);
}

function table(host, cols, data, opts = {}) {
  if (!data.length) {
    host.appendChild(el('div', { class: 'empty', text: opts.empty || '해당 항목 없음' }));
    return { redraw: () => {} };
  }
  const box = el('div', { class: opts.scroll ? 'scroll' : '' });
  const t = el('table');
  const hr = el('tr');
  cols.forEach(c => hr.appendChild(el('th', { class: c.txt ? 'txt' : '', text: c.label })));
  t.appendChild(el('thead', {}, [hr]));
  const tbody = el('tbody');
  t.appendChild(tbody);
  let sortIdx = opts.sort ?? -1, desc = true;
  const draw = () => {
    tbody.innerHTML = '';
    const list = data.slice();
    if (sortIdx >= 0) {
      const key = cols[sortIdx].key;
      list.sort((a, b) => {
        const x = a[key], y = b[key];
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        return (typeof x === 'number' ? y - x : String(x).localeCompare(String(y))) * (desc ? 1 : -1);
      });
    }
    for (const row of list) {
      const tr = el('tr', { class: opts.highlight && opts.highlight(row) ? 'picked' : '' });
      for (const c of cols) {
        const td = el('td', { class: c.txt ? 'txt' : '' });
        const v = c.render ? c.render(row) : num(row[c.key]);
        if (v instanceof Node) td.appendChild(v);
        else td.innerHTML = v === null || v === undefined ? '<span class="null">–</span>' : String(v);
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  };
  hr.querySelectorAll('th').forEach((th, i) => th.onclick = () => {
    if (sortIdx === i) desc = !desc; else { sortIdx = i; desc = true; }
    draw();
  });
  draw();
  box.appendChild(t);
  host.appendChild(box);
  return { redraw: next => { data = next; draw(); } };
}

const svgns = 'http://www.w3.org/2000/svg';
const sn = (tag, attrs) => {
  const n = document.createElementNS(svgns, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};

function comboChart(host, rows, xKey, series) {
  const W = 1180, H = 260, padL = 48, padR = 16, padT = 14, padB = 34;
  const s = document.createElementNS(svgns, 'svg');
  s.setAttribute('viewBox', `0 0 ${W} ${H}`);
  s.setAttribute('width', '100%');
  s.setAttribute('height', H);
  const maxV = Math.max(1, ...rows.flatMap(r => series.map(ser => r[ser.key] ?? 0)));
  const iw = W - padL - padR, ih = H - padT - padB;
  const x = i => padL + (rows.length <= 1 ? iw / 2 : (i * iw) / (rows.length - 1));
  const y = v => padT + ih - (v / maxV) * ih;

  for (let g = 0; g <= 4; g++) {
    const gy = padT + (ih * g) / 4;
    s.appendChild(sn('line', { x1: padL, x2: W - padR, y1: gy, y2: gy, stroke: '#2b3040', 'stroke-width': 1 }));
    const lbl = sn('text', { x: padL - 8, y: gy + 4, fill: '#9aa3b2', 'font-size': 10, 'text-anchor': 'end' });
    lbl.textContent = Math.round(maxV - (maxV * g) / 4);
    s.appendChild(lbl);
  }
  const bars = series.filter(ser => ser.type === 'bar');
  const bw = Math.max(1, (iw / Math.max(rows.length, 1)) / (bars.length + 1));
  bars.forEach((ser, si) => rows.forEach((r, i) => {
    const v = r[ser.key] ?? 0;
    s.appendChild(sn('rect', {
      x: x(i) - (bars.length * bw) / 2 + si * bw, y: y(v),
      width: Math.max(0.8, bw - 0.5), height: Math.max(0, padT + ih - y(v)),
      fill: ser.color, opacity: 0.75, rx: 1,
    }));
  }));
  series.filter(ser => ser.type !== 'bar').forEach(ser => {
    s.appendChild(sn('polyline', {
      points: rows.map((r, i) => `${x(i)},${y(r[ser.key] ?? 0)}`).join(' '),
      fill: 'none', stroke: ser.color, 'stroke-width': 2.2,
    }));
    if (rows.length <= 60) {
      rows.forEach((r, i) => s.appendChild(sn('circle', { cx: x(i), cy: y(r[ser.key] ?? 0), r: 2.6, fill: ser.color })));
    }
  });
  const every = Math.max(1, Math.ceil(rows.length / 16));
  rows.forEach((r, i) => {
    if (i % every) return;
    const t = sn('text', { x: x(i), y: H - 12, fill: '#9aa3b2', 'font-size': 10, 'text-anchor': 'middle' });
    t.textContent = String(r[xKey]).replace(/^\\d{4}-/, '');
    s.appendChild(t);
  });
  const box = el('div', { class: 'chart' }, [s]);
  const lg = el('div', { class: 'legend' });
  series.forEach(ser => lg.appendChild(el('span', { html: `<i style="background:${ser.color}"></i>${ser.label}` })));
  box.appendChild(lg);
  host.appendChild(box);
}

function barChart(host, rows, labelKey, valueKey, color) {
  const box = el('div', { class: 'chart' });
  const maxV = Math.max(1, ...rows.map(r => r[valueKey] ?? 0));
  for (const r of rows) {
    const v = r[valueKey] ?? 0;
    const line = el('div');
    line.style.cssText = 'display:grid;grid-template-columns:104px 1fr 56px;align-items:center;gap:10px;margin:5px 0';
    line.appendChild(el('span', { text: String(r[labelKey]), style: 'color:var(--dim);font-size:12px' }));
    const track = el('div');
    track.style.cssText = 'background:var(--panel2);border-radius:4px;height:16px';
    const fill = el('div');
    fill.style.cssText = `width:${(v / maxV * 100).toFixed(1)}%;height:100%;background:${color};border-radius:4px`;
    track.appendChild(fill);
    line.appendChild(track);
    line.appendChild(el('span', { text: num(v), style: 'text-align:right;font-size:12px' }));
    box.appendChild(line);
  }
  host.appendChild(box);
}

/* Several share series side by side on one row - built for "count % vs size %", where the
   gap between the two bars is the thing being read. Each series is scaled to its own max
   so a small-percentage series stays legible. */
function multiBarChart(host, rows, labelKey, series) {
  const box = el('div', { class: 'chart' });
  const maxOf = {};
  for (const ser of series) maxOf[ser.key] = Math.max(0.0001, ...rows.map(r => r[ser.key] ?? 0));
  for (const r of rows) {
    const block = el('div');
    block.style.cssText = 'display:grid;grid-template-columns:118px 1fr;align-items:center;gap:10px;margin:8px 0';
    block.appendChild(el('span', { text: String(r[labelKey]), style: 'color:var(--fg);font-size:12px;font-weight:600' }));
    const stack = el('div');
    for (const ser of series) {
      const v = r[ser.key];
      const row = el('div');
      row.style.cssText = 'display:grid;grid-template-columns:96px 1fr 76px;align-items:center;gap:8px;margin:2px 0';
      row.appendChild(el('span', { text: ser.label, style: 'color:var(--dim);font-size:11px' }));
      const track = el('div');
      track.style.cssText = 'background:var(--panel2);border-radius:4px;height:13px';
      const fill = el('div');
      fill.style.cssText = `width:${(((v ?? 0) / maxOf[ser.key]) * 100).toFixed(1)}%;height:100%;background:${ser.color};border-radius:4px`;
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el('span', {
        text: ser.fmt ? ser.fmt(v) : num(v),
        style: 'text-align:right;font-size:11px;color:var(--dim)',
      }));
      stack.appendChild(row);
    }
    block.appendChild(stack);
    box.appendChild(block);
  }
  const lg = el('div', { class: 'legend' });
  series.forEach(ser => lg.appendChild(el('span', { html: `<i style="background:${ser.color}"></i>${ser.label}` })));
  box.appendChild(lg);
  host.appendChild(box);
}

/* ================= date range state ================= */
const COLLECT_FROM = META.collection_start;
const COLLECT_TO = (META.collection_end || META.generated_at.slice(0, 10));
const clampDate = d => d < COLLECT_FROM ? COLLECT_FROM : (d > COLLECT_TO ? COLLECT_TO : d);

const fromInput = document.getElementById('from');
const toInput = document.getElementById('to');
for (const input of [fromInput, toInput]) {
  input.min = COLLECT_FROM;
  input.max = COLLECT_TO;
  input.onchange = () => applyRange(fromInput.value, toInput.value);
}

const PRESETS = [
  { days: 7, label: '최근 7일' },
  { days: 30, label: '최근 30일' },
  { days: 90, label: '최근 90일' },
  { days: null, label: '전체' },
];
const presetHost = document.getElementById('presets');
const presetButtons = new Map();
for (const p of PRESETS) {
  const b = el('button', { text: p.label });
  b.onclick = () => applyPreset(p.days);
  presetHost.appendChild(b);
  presetButtons.set(p.days, b);
}
function rangeForDays(days) {
  if (days === null) return [COLLECT_FROM, COLLECT_TO];
  return [clampDate(addDays(COLLECT_TO, -(days - 1))), COLLECT_TO];
}
function applyPreset(days) {
  const [a, b] = rangeForDays(days);
  applyRange(a, b);
}

let VIEW = null;
let view = null;
let leaderboard = null;
const pick = document.getElementById('pick');

function applyRange(rawFrom, rawTo) {
  let from = clampDate(rawFrom || COLLECT_FROM);
  let to = clampDate(rawTo || COLLECT_TO);
  if (from > to) { const t = from; from = to; to = t; }
  const clamped = (rawFrom && rawFrom !== from) || (rawTo && rawTo !== to);
  fromInput.value = from;
  toInput.value = to;

  view = computeView(from, to);
  VIEW = { from, to };

  const spanDays = Math.round((dayStart(to) - dayStart(from)) / DAY) + 1;
  document.getElementById('rangeChip').textContent =
    from + ' ~ ' + to + ' · ' + spanDays + '일 · PR ' + num(view.totals.prs_created_in_window) + '건';
  for (const [days, b] of presetButtons) {
    const [a, z] = rangeForDays(days);
    b.className = (a === from && z === to) ? 'on' : '';
  }
  const clampChip = document.getElementById('clampChip');
  if (clamped) {
    clampChip.style.display = '';
    clampChip.className = 'chip warn';
    clampChip.textContent = '수집 범위(' + COLLECT_FROM + ' ~ ' + COLLECT_TO + ') 밖은 조회할 수 없어 잘렸습니다';
  } else {
    clampChip.style.display = 'none';
  }

  const roster = view.reviewers.map(r => r.reviewer);
  const wanted = pick.value || META.default_reviewer;
  const chosen = roster.includes(wanted) ? wanted
    : (roster.includes(META.default_reviewer) ? META.default_reviewer : (roster[0] || META.default_reviewer));
  pick.innerHTML = '';
  const listed = roster.length ? roster : [META.default_reviewer];
  for (const login of listed) {
    const r = view.reviewers.find(x => x.reviewer === login) || {};
    pick.appendChild(el('option', {
      value: login,
      text: login + '  —  요청 ' + num(r.requested_prs) + ' / 리뷰 ' + num(r.reviews_given) + ' / 응답률 ' + pct(r.response_rate),
    }));
  }
  pick.value = chosen;

  renderOrg();
  renderReviewer(chosen);
}

/* ================= per-reviewer half ================= */
function renderReviewer(login) {
  const host = document.getElementById('reviewerSections');
  host.innerHTML = '';
  const t = view.reviewers.find(r => r.reviewer === login) || {};
  const det = view.detail(login);
  const win = VIEW.from + ' ~ ' + VIEW.to;

  const s0 = section(host, login + ' 요약', win + ' 사이에 생성된 PR 기준');
  cards(s0, [
    { k: '리뷰 요청받은 PR', v: num(t.requested_prs), hi: true },
    { k: '실제 리뷰한 PR', v: num(t.fulfilled_prs), hi: true },
    { k: '응답률', v: pct(t.response_rate), hi: true },
    { k: '첫 응답 p50', v: hrs(t.latency_p50_h) },
    { k: '첫 응답 p90', v: hrs(t.latency_p90_h) },
    { k: '첫 응답 평균', v: hrs(t.latency_mean_h) },
    { k: '미응답 · 열린 PR', v: num(t.outstanding_open) },
    { k: '미응답 채로 머지', v: num(t.merged_without_review), u: ' (' + pct(t.merged_without_review_rate) + ')' },
    { k: '남긴 리뷰', v: num(t.reviews_given) },
    { k: '리뷰당 인라인 코멘트', v: num(t.comments_per_review) },
    { k: '내용 있는 리뷰 비율', v: pct(t.substantive_review_rate) },
    { k: 'APPROVED / CHANGES', v: num(t.approved) + ' / ' + num(t.changes_requested) },
    { k: 'CHANGES 비율', v: pct(t.changes_rate), u: ' of ' + num(t.verdicts), hi: true },
    { k: 'APPROVED 비율', v: pct(t.approve_rate) },
    { k: '요청받은 변경량', v: num(t.requested_churn), u: ' lines' },
    { k: '전체 변경량 대비', v: pct(t.requested_churn_share), hi: true },
    { k: '리뷰한 변경량', v: num(t.reviewed_churn), u: ' (' + pct(t.reviewed_churn_share) + ')' },
    { k: '변경량 기준 응답률', v: pct(t.churn_response_rate) },
    { k: '리뷰한 PR 중앙 크기', v: num(t.reviewed_churn_p50), u: ' lines' },
    {
      k: '첫 응답 p50 (작은→큰)',
      v: hrs(t.latency_small_p50_h) + ' → ' + hrs(t.latency_large_p50_h),
      hi: true,
    },
  ]);

  const s1 = section(host, login + ' 미이행 잔량 추이', '일자별. 리뷰·요청철회·PR 종료를 모두 반영');
  comboChart(s1, view.backlog(login), 'day', [
    { key: 'requested', label: '신규 요청', color: '#5b9dff', type: 'bar' },
    { key: 'first_reviews', label: '첫 리뷰', color: '#3fb950', type: 'bar' },
    { key: 'outstanding', label: '일 마감 시점 잔량', color: '#a371f7', type: 'line' },
  ]);

  const s2 = section(host, login + ' 첫 응답 지연 분포', '요청 시각 → 해당 PR에 남긴 첫 리뷰 시각');
  barChart(s2, det.latency_histogram, 'bucket', 'count', 'var(--pick)');

  const sz = section(host, login + ' PR 크기별',
    '크기 = additions + deletions. 비중은 이 리뷰어가 요청받은 전체 변경량 대비');
  table(sz, [
    { label: '크기', key: 'bucket', txt: true },
    { label: '요청 PR', key: 'requested' },
    { label: '갯수 비중', key: 'requested_share', render: r => pct(r.requested_share) },
    { label: '변경량', key: 'churn' },
    { label: '변경량 비중', key: 'churn_share', render: r => pct(r.churn_share) },
    { label: '리뷰', key: 'reviewed' },
    { label: '응답률', key: 'response_rate', render: r => pct(r.response_rate) },
    { label: '첫 응답 p50', key: 'latency_p50_h', render: r => hrs(r.latency_p50_h) },
    { label: '첫 응답 p90', key: 'latency_p90_h', render: r => hrs(r.latency_p90_h) },
    { label: '리뷰당 코멘트', key: 'comments_per_review' },
    { label: 'APPROVED', key: 'approved' },
    { label: 'CHANGES', key: 'changes_requested' },
    { label: 'CHANGES 비율', key: 'changes_rate', render: r => pct(r.changes_rate) },
    { label: '미응답(열림)', key: 'outstanding_open' },
    { label: '미응답 머지', key: 'merged_without_review' },
  ], det.by_size, { sort: -1 });
  multiBarChart(sz, det.by_size, 'bucket', [
    { key: 'requested_share', label: '갯수 비중', color: '#5b9dff', fmt: pct },
    { key: 'churn_share', label: '변경량 비중', color: '#a371f7', fmt: pct },
    { key: 'latency_p50_h', label: '첫 응답 p50', color: '#d29922', fmt: hrs },
    { key: 'changes_rate', label: 'CHANGES 비율', color: '#f85149', fmt: pct },
  ]);

  const s3 = section(host, login + ' 상세 분포');
  const g = el('div', { class: 'grid2' });
  const left = el('div'), right = el('div');
  left.appendChild(el('h3', { text: '레포별 (비중은 이 리뷰어의 요청 변경량 대비)' }));
  table(left, [
    { label: '레포', key: 'repo', txt: true },
    { label: '요청', key: 'requested' },
    { label: '리뷰', key: 'reviewed' },
    { label: '응답률', key: 'response_rate', render: r => pct(r.response_rate) },
    { label: '변경량', key: 'requested_churn' },
    { label: '변경량 비중', key: 'requested_churn_share', render: r => pct(r.requested_churn_share) },
    { label: 'PR당 변경량', key: 'churn_per_pr' },
    { label: '변경량 응답률', key: 'churn_response_rate', render: r => pct(r.churn_response_rate) },
    { label: 'p50', key: 'latency_p50_h', render: r => hrs(r.latency_p50_h) },
    { label: '미응답(열림)', key: 'outstanding_open' },
    { label: '미응답 머지', key: 'merged_without_review' },
  ], det.by_repo, { scroll: true, sort: 1 });
  right.appendChild(el('h3', { text: 'PR 작성자별' }));
  table(right, [
    { label: '작성자', key: 'author', txt: true },
    { label: '요청', key: 'requested' },
    { label: '리뷰', key: 'reviewed' },
    { label: '응답률', key: 'response_rate', render: r => pct(r.response_rate) },
    { label: '변경량', key: 'requested_churn' },
    { label: '변경량 비중', key: 'requested_churn_share', render: r => pct(r.requested_churn_share) },
    { label: 'PR당 변경량', key: 'churn_per_pr' },
    { label: 'p50', key: 'latency_p50_h', render: r => hrs(r.latency_p50_h) },
  ], det.by_pr_author, { scroll: true, sort: 1 });
  g.appendChild(left); g.appendChild(right);
  s3.appendChild(g);

  const sh = section(host, login + ' 가장 큰 PR', '요청받은 PR 중 변경량 상위 ' + num(det.heaviest_prs.length) + '건');
  table(sh, [
    { label: 'PR', key: 'number', txt: true, render: r => `<a href="${r.url}" target="_blank" rel="noopener">${r.repo}#${r.number}</a>` },
    { label: '제목', key: 'title', txt: true, render: r => (r.title || '').slice(0, 70) },
    { label: '작성자', key: 'author', txt: true },
    { label: '크기', key: 'bucket', txt: true },
    { label: '변경량', key: 'churn' },
    { label: '파일', key: 'changed_files' },
    { label: '리뷰함', key: 'reviewed', render: r => r.reviewed ? 'yes' : '<span class="null">no</span>' },
    { label: '첫 응답', key: 'latency_hours', render: r => hrs(r.latency_hours) },
    { label: '리뷰 수', key: 'reviews' },
    { label: '코멘트', key: 'inline_comments' },
    { label: 'verdict', key: 'verdict', txt: true },
  ], det.heaviest_prs, { scroll: true, sort: 4, empty: '요청받은 PR 없음' });

  const s4 = section(host, login + ' 미응답 · 열린 PR', num(det.outstanding_open.length) + '건, 대기 시간 순');
  table(s4, [
    { label: 'PR', key: 'number', txt: true, render: r => `<a href="${r.url}" target="_blank" rel="noopener">${r.repo}#${r.number}</a>` },
    { label: '제목', key: 'title', txt: true, render: r => (r.title || '').slice(0, 90) },
    { label: '작성자', key: 'author', txt: true },
    { label: '요청 시각', key: 'requested_at', txt: true, render: r => (r.requested_at || '').slice(0, 10) },
    { label: '대기', key: 'waiting_hours', render: r => hrs(r.waiting_hours) },
    { label: '크기', key: 'bucket', txt: true },
    { label: '변경량', key: 'churn' },
    { label: 'pending 표시', key: 'still_pending_snapshot', render: r => r.still_pending_snapshot ? 'yes' : 'no' },
  ], det.outstanding_open, { scroll: true, sort: 4, empty: '미응답 상태로 열려 있는 PR 없음' });

  const s5 = section(host, login + ' 리뷰 없이 머지된 PR', num(det.merged_without_review.length) + '건');
  table(s5, [
    { label: 'PR', key: 'number', txt: true, render: r => `<a href="${r.url}" target="_blank" rel="noopener">${r.repo}#${r.number}</a>` },
    { label: '제목', key: 'title', txt: true, render: r => (r.title || '').slice(0, 90) },
    { label: '작성자', key: 'author', txt: true },
    { label: '요청', key: 'requested_at', txt: true, render: r => (r.requested_at || '').slice(0, 10) },
    { label: '머지', key: 'merged_at', txt: true, render: r => (r.merged_at || '').slice(0, 10) },
    { label: '크기', key: 'bucket', txt: true },
    { label: '변경량', key: 'churn' },
    { label: '파일', key: 'changed_files' },
  ], det.merged_without_review, { scroll: true, sort: 4, empty: '요청받은 PR이 전부 리뷰를 받고 머지됨' });

  if (leaderboard) leaderboard.redraw(view.reviewers);
}

/* ================= org half ================= */
function renderOrg() {
  const orgHost = document.getElementById('orgSections');
  orgHost.innerHTML = '';
  leaderboard = null;
  const win = VIEW ? VIEW.from + ' ~ ' + VIEW.to : '';

  {
    const s = section(orgHost, '리뷰어 전체 비교', '이름을 누르면 위쪽 상세가 그 리뷰어로 바뀝니다. 열 제목을 누르면 정렬됩니다');
    leaderboard = table(s, [
      {
        label: '리뷰어', key: 'reviewer', txt: true,
        render: r => el('button', { class: 'link', text: r.reviewer, on: { onclick: () => {
          pick.value = r.reviewer;
          renderReviewer(r.reviewer);
          window.scrollTo({ top: 0, behavior: 'smooth' });
        } } }),
      },
      { label: '요청', key: 'requested_prs' },
      { label: '이행', key: 'fulfilled_prs' },
      { label: '응답률', key: 'response_rate', render: r => pct(r.response_rate) },
      { label: '리뷰 수', key: 'reviews_given' },
      { label: 'p50', key: 'latency_p50_h', render: r => hrs(r.latency_p50_h) },
      { label: 'p90', key: 'latency_p90_h', render: r => hrs(r.latency_p90_h) },
      { label: '미응답(열림)', key: 'outstanding_open' },
      { label: '미응답 머지', key: 'merged_without_review' },
      { label: '리뷰당 코멘트', key: 'comments_per_review' },
      { label: '내용 있는 비율', key: 'substantive_review_rate', render: r => pct(r.substantive_review_rate) },
      { label: 'APPROVED', key: 'approved' },
      { label: 'CHANGES', key: 'changes_requested' },
      { label: 'CHANGES 비율', key: 'changes_rate', render: r => pct(r.changes_rate) },
      { label: '요청 변경량', key: 'requested_churn' },
      { label: '변경량 비중', key: 'requested_churn_share', render: r => pct(r.requested_churn_share) },
      { label: '리뷰한 변경량', key: 'reviewed_churn' },
      { label: '변경량 응답률', key: 'churn_response_rate', render: r => pct(r.churn_response_rate) },
      { label: 'PR 중앙 크기', key: 'reviewed_churn_p50' },
      { label: `p50 (≤${SMALL_MAX})`, key: 'latency_small_p50_h', render: r => hrs(r.latency_small_p50_h) },
      { label: `p50 (≥${LARGE_MIN})`, key: 'latency_large_p50_h', render: r => hrs(r.latency_large_p50_h) },
      { label: '크기별 차이', key: 'latency_size_gap_h', render: r => r.latency_size_gap_h === null || r.latency_size_gap_h === undefined ? null : (r.latency_size_gap_h > 0 ? '+' : '') + hrs(r.latency_size_gap_h) },
      { label: '요청 외 리뷰', key: 'unsolicited_prs' },
    ], view.reviewers, { scroll: true, sort: 4, highlight: r => r.reviewer === pick.value, empty: '이 기간에 리뷰 요청이 없습니다' });
  }

  {
    const so = view.size_overview;
    const t = so.totals;
    const s = section(orgHost, '변경 규모 분포',
      '크기 = additions + deletions (GitHub이 PR에 보고하는 값). 갯수 비중과 변경량 비중을 나란히 봅니다');
    cards(s, [
      { k: '전체 변경량', v: num(t.churn), u: ' lines' },
      { k: '변경 파일', v: num(t.changed_files) },
      { k: 'PR당 평균', v: num(t.churn_stats.mean), u: ' lines' },
      { k: 'PR 크기 p50', v: num(t.churn_stats.p50), u: ' lines' },
      { k: 'p25 / p75', v: num(t.churn_p25) + ' / ' + num(t.churn_p75) },
      { k: 'p90 / p99', v: num(t.churn_stats.p90) + ' / ' + num(t.churn_p99) },
      { k: '최대 PR', v: num(t.churn_stats.max), u: ' lines' },
      { k: '상위 10% PR이 차지하는 변경량', v: pct(t.top_decile_churn_share), hi: true },
      { k: '조직 전체 CHANGES 비율', v: pct(t.changes_rate), u: ' of ' + num(t.verdicts), hi: true },
    ]);
    table(s, [
      { label: '크기', key: 'bucket', txt: true },
      { label: 'PR', key: 'prs' },
      { label: '갯수 비중', key: 'prs_share', render: r => pct(r.prs_share) },
      { label: '변경량', key: 'churn' },
      { label: '변경량 비중', key: 'churn_share', render: r => pct(r.churn_share) },
      { label: '변경 파일', key: 'changed_files' },
      { label: '파일 비중', key: 'changed_files_share', render: r => pct(r.changed_files_share) },
      { label: 'PR 중앙 크기', key: 'churn_p50' },
      { label: '리뷰 커버리지', key: 'review_coverage', render: r => pct(r.review_coverage) },
      { label: '첫 응답 p50', key: 'latency_p50_h', render: r => hrs(r.latency_p50_h) },
      { label: '첫 응답 p90', key: 'latency_p90_h', render: r => hrs(r.latency_p90_h) },
      { label: 'PR당 리뷰', key: 'reviews_per_pr' },
      { label: 'PR당 코멘트', key: 'comments_per_pr' },
      { label: 'APPROVED', key: 'approved' },
      { label: 'CHANGES', key: 'changes_requested' },
      { label: 'CHANGES 비율', key: 'changes_rate', render: r => pct(r.changes_rate) },
      { label: '리뷰 없이 머지', key: 'merged_without_review' },
    ], so.buckets, { sort: -1 });
    multiBarChart(s, so.buckets, 'bucket', [
      { key: 'prs_share', label: '갯수 비중', color: '#5b9dff', fmt: pct },
      { key: 'churn_share', label: '변경량 비중', color: '#a371f7', fmt: pct },
      { key: 'latency_p50_h', label: '첫 응답 p50', color: '#d29922', fmt: hrs },
      { key: 'changes_rate', label: 'CHANGES 비율', color: '#f85149', fmt: pct },
      { key: 'review_coverage', label: '리뷰 커버리지', color: '#3fb950', fmt: pct },
    ]);
  }

  {
    const b = view.bulk_request_evidence;
    const s = section(orgHost, '리뷰 요청 패턴');
    cards(s, [
      { k: '요청이 있는 PR', v: num(b.prs_with_requests) },
      { k: 'PR당 리뷰어 평균', v: num(b.reviewers_per_pr_mean) + '명' },
      { k: 'PR당 리뷰어 중앙값', v: num(b.reviewers_per_pr_p50) + '명' },
      { k: 'PR 생성→첫 요청 p50', v: hrs(b.first_request_delay_p50_h) },
      { k: 'PR 생성→첫 요청 p90', v: hrs(b.first_request_delay_p90_h) },
    ]);
    barChart(s, b.reviewers_per_pr_distribution.map(r => ({ l: r.reviewers + '명 요청', v: r.prs })), 'l', 'v', 'var(--accent)');
  }

  {
    const s = section(orgHost, '조직 전체 일별 볼륨', win + ' · 기간 내 생성된 PR과 그 PR에 달린 리뷰');
    comboChart(s, view.daily_volume, 'day', [
      { key: 'prs_created', label: 'PR 생성', color: '#5b9dff', type: 'bar' },
      { key: 'prs_merged', label: 'PR 머지', color: '#3fb950', type: 'bar' },
      { key: 'reviews', label: '리뷰 제출', color: '#d29922', type: 'line' },
    ]);
  }

  {
    const s = section(orgHost, '레포별 분포',
      '가중 지수 = 변경량 비중 ÷ 갯수 비중. 1보다 크면 PR 수보다 변경량 쪽에서 더 무거운 레포입니다');
    table(s, [
      { label: '레포', key: 'repo', txt: true, render: r => r.repo + (r.is_archived ? ' <span class="null">(archived)</span>' : '') },
      { label: '언어', key: 'language', txt: true },
      { label: 'PR 생성', key: 'prs_created' },
      { label: '갯수 비중', key: 'prs_share', render: r => pct(r.prs_share) },
      { label: '변경량', key: 'churn' },
      { label: '변경량 비중', key: 'churn_share', render: r => pct(r.churn_share) },
      { label: '가중 지수', key: 'weight_index' },
      { label: '변경 파일', key: 'changed_files' },
      { label: 'PR 중앙 크기', key: 'churn_p50' },
      { label: 'PR p90 크기', key: 'churn_p90' },
      { label: '최대 PR', key: 'churn_max' },
      { label: `${LARGE_MIN}줄+ PR`, key: 'large_prs' },
      { label: '큰 PR 비율', key: 'large_pr_rate', render: r => pct(r.large_pr_rate) },
      { label: '첫 응답 p50', key: 'latency_p50_h', render: r => hrs(r.latency_p50_h) },
      { label: '첫 응답 p90', key: 'latency_p90_h', render: r => hrs(r.latency_p90_h) },
      { label: '리뷰 커버리지', key: 'review_coverage', render: r => pct(r.review_coverage) },
      { label: 'PR당 코멘트', key: 'comments_per_pr' },
      { label: 'APPROVED', key: 'approved' },
      { label: 'CHANGES', key: 'changes_requested' },
      { label: 'CHANGES 비율', key: 'changes_rate', render: r => pct(r.changes_rate) },
      { label: '머지', key: 'prs_merged' },
      { label: '열림', key: 'prs_open' },
      { label: '닫힘(미머지)', key: 'prs_closed_unmerged' },
      { label: '작성자 수', key: 'distinct_authors' },
      { label: '수집 기준값(전체기간)', key: 'expected_created_in_window' },
    ], view.repos, { scroll: true, sort: 2 });
    multiBarChart(s, view.repos.slice(0, 12), 'repo', [
      { key: 'prs_share', label: '갯수 비중', color: '#5b9dff', fmt: pct },
      { key: 'churn_share', label: '변경량 비중', color: '#a371f7', fmt: pct },
      { key: 'latency_p50_h', label: '첫 응답 p50', color: '#d29922', fmt: hrs },
      { key: 'changes_rate', label: 'CHANGES 비율', color: '#f85149', fmt: pct },
    ]);
  }

  {
    const s = section(orgHost, 'PR 작성자별 분포', '가중 지수 = 변경량 비중 ÷ 갯수 비중');
    table(s, [
      { label: '작성자', key: 'author', txt: true },
      { label: 'PR 생성', key: 'prs_created' },
      { label: '갯수 비중', key: 'prs_share', render: r => pct(r.prs_share) },
      { label: '변경량', key: 'churn' },
      { label: '변경량 비중', key: 'churn_share', render: r => pct(r.churn_share) },
      { label: '가중 지수', key: 'weight_index' },
      { label: 'PR 중앙 크기', key: 'churn_p50' },
      { label: 'PR 평균 크기', key: 'churn_mean' },
      { label: '변경 파일', key: 'changed_files' },
    ], view.pr_authors, { scroll: true, sort: 1 });
  }

  document.getElementById('subtitle').textContent =
    '수집 범위 ' + COLLECT_FROM + ' ~ ' + COLLECT_TO +
    ' · 조회 ' + VIEW.from + ' ~ ' + VIEW.to +
    ' · 레포 ' + num(view.totals.repos_in_scope) +
    ' · PR ' + num(view.totals.prs_created_in_window) + '건' +
    ' · 변경 ' + num(view.totals.churn_total) + '줄 / ' + num(view.totals.changed_files_total) + '파일' +
    ' · 리뷰 ' + num(view.totals.human_reviews) + '건' +
    ' (지표 제외: 봇 ' + num(F.bot_reviews_excluded) + ' · 셀프리뷰 ' + num(F.self_reviews_excluded) + ')' +
    ' · 리뷰어 ' + num(view.reviewers.length) + '명' +
    ' · 생성 ' + META.generated_at;
}

/* ================= boot ================= */
document.getElementById('title').textContent = META.org + ' PR 리뷰 대시보드';
document.getElementById('basisChip').textContent = '기간 기준: PR 생성일 (created)';
document.getElementById('archChip').textContent = 'archived 레포 ' + (META.include_archived ? '포함' : '제외');
pick.onchange = () => renderReviewer(pick.value);
applyPreset(META.view_default_days);

document.getElementById('footer').innerHTML =
  'facts.db 빌드 ' + (META.built_at || '–') +
  ' · raw 페이지 ' + num(Number(META.raw_pr_pages)) + ' + 오버플로 ' + num(Number(META.raw_overflow_pages)) +
  ' · 기본 리뷰어 ' + META.default_reviewer +
  ' · 기본 조회 기간 최근 ' + num(META.view_default_days) + '일' +
  ' · 이 페이지는 <code>dashboard/data.json</code>에 담긴 PR ' + num(F.counts.prs) +
  '건 · 요청쌍 ' + num(F.counts.pairs) + '건 · 리뷰 ' + num(F.counts.reviews) +
  '건의 사실값을 선택한 기간으로 직접 집계합니다. 사실값은 전부 <code>build/facts.db</code>에서 나옵니다.';
</script>
</body>
</html>
"""


def main() -> None:
    data_path = gh.DASHBOARD / "data.json"
    data = json.loads(data_path.read_text())
    title = f"{data['meta']['org']} PR review dashboard"
    html = TEMPLATE.replace("__TITLE__", title).replace(
        "__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    )
    out = gh.DASHBOARD / "index.html"
    out.write_text(html)
    gh.log(f"index.html written ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
