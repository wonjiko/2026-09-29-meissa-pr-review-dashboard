/**
 * Optional stage - load dashboard/index.html in a real DOM and assert it rendered.
 *
 *   ./run.sh check      (provisions build/domcheck/node_modules on first run)
 *
 * Three things are checked:
 *
 *  1. The page drew - no script error, no empty table or chart, figures on screen agree
 *     with what the in-page engine computed.
 *  2. The controls work - the reviewer picker is in a sticky bar, the date range defaults
 *     to the last `view_default_days` days, presets and manual dates re-aggregate, and a
 *     range outside the collection window is clamped rather than silently wrong.
 *  3. The in-page engine agrees with Python. data.json carries `reference`: the same
 *     figures computed by aggregate.py from facts.db over the FULL collection window. The
 *     page is asked for that window and every figure is compared. Counts, sums and churn
 *     must match EXACTLY; values that both sides round (hour percentiles, rates) are
 *     compared within a tolerance, because the two runtimes round independently.
 */
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM, VirtualConsole } from 'jsdom';

const htmlPath = process.argv[2] || path.resolve(import.meta.dirname, '..', 'dashboard', 'index.html');
if (!fs.existsSync(htmlPath)) {
  console.error(`FAIL  dashboard not found at ${htmlPath} - run ./run.sh dashboard first`);
  process.exit(1);
}
const html = fs.readFileSync(htmlPath, 'utf8');

const errors = [];
const vc = new VirtualConsole()
  .on('jsdomError', (e) => errors.push(String(e.stack || e)))
  .on('error', (...a) => errors.push('console.error: ' + a.join(' ')));

const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc });
const doc = dom.window.document;

const failures = [];
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`);
  if (!ok) failures.push(name);
};

check('page script ran without errors', errors.length === 0, errors.slice(0, 3).join(' | ').slice(0, 400));

const payload = JSON.parse(doc.getElementById('payload').textContent);
const meta = payload.meta;
const ref = payload.reference;
const facts = payload.facts;
const pick = doc.getElementById('pick');
const fromInput = doc.getElementById('from');
const toInput = doc.getElementById('to');
const presets = [...doc.querySelectorAll('#presets button')];

const sum = (list, key) => list.reduce((acc, r) => acc + (r[key] ?? 0), 0);
const near = (a, b, tol) => a === null || a === undefined || b === null || b === undefined
  ? a === b : Math.abs(a - b) <= tol;

/* ---------- 1. structure ---------- */
check('window basis is created', meta.basis === 'created', meta.basis);
check('archived repos included', meta.include_archived === true, String(meta.include_archived));
check('facts shipped instead of one precomputed window',
  facts.counts.prs > 0 && facts.counts.pairs > 0 && facts.counts.reviews > 0,
  JSON.stringify(facts.counts));
check('page exposes its aggregation engine', typeof dom.window.computeView === 'function');

const controls = doc.querySelector('.controls');
check('picker and date range share one control bar',
  !!controls && controls.contains(pick) && controls.contains(fromInput) && controls.contains(toInput));
const controlPos = dom.window.getComputedStyle(controls).position;
const cssHasSticky = /\.controls\s*\{[^}]*position:\s*sticky/.test(html);
check('control bar is sticky so the picker survives scrolling',
  controlPos === 'sticky' || cssHasSticky, `computed=${controlPos || 'n/a'} css=${cssHasSticky}`);

const reviewerSections = () => doc.querySelectorAll('#reviewerSections section').length;
const orgSections = () => doc.querySelectorAll('#orgSections section').length;
check('per-reviewer sections rendered', reviewerSections() >= 7, `${reviewerSections()} sections`);
check('org sections rendered', orgSections() >= 6, `${orgSections()} sections`);

const tables = () => [...doc.querySelectorAll('table')];
const charts = () => [...doc.querySelectorAll('svg')];
check('every table has rows', tables().length > 0 && tables().every((t) => t.querySelectorAll('tbody tr').length > 0),
  tables().map((t) => t.querySelectorAll('tbody tr').length).join(','));
check('every chart has geometry', charts().length > 0 && charts().every((s) => s.childNodes.length > 10),
  charts().map((s) => s.childNodes.length).join(','));

/* ---------- 2. date range controls ---------- */
const collectFrom = meta.collection_start;
const collectTo = meta.collection_end || meta.generated_at.slice(0, 10);
const addDays = (d, n) => new Date(Date.parse(d + 'T00:00:00Z') + n * 86400000).toISOString().slice(0, 10);
const spanOf = (a, b) => Math.round((Date.parse(b + 'T00:00:00Z') - Date.parse(a + 'T00:00:00Z')) / 86400000) + 1;

check('date inputs are clamped to the collection window',
  fromInput.min === collectFrom && fromInput.max === collectTo
  && toInput.min === collectFrom && toInput.max === collectTo,
  `${fromInput.min}..${fromInput.max}`);
check('presets offer last 7 / 30 / 90 days and the whole collection',
  presets.map((b) => b.textContent).join('|') === '최근 7일|최근 30일|최근 90일|전체',
  presets.map((b) => b.textContent).join('|'));
check(`range opens on the last ${meta.view_default_days} days`,
  toInput.value === collectTo && spanOf(fromInput.value, toInput.value) === meta.view_default_days,
  `${fromInput.value} ~ ${toInput.value} = ${spanOf(fromInput.value, toInput.value)}d`);
check('the matching preset is marked active on load',
  presets.find((b) => b.textContent === `최근 ${meta.view_default_days}일`)?.className === 'on');
const chip = doc.getElementById('rangeChip').textContent;
check('range chip states the window on screen',
  chip.includes(fromInput.value) && chip.includes(toInput.value), chip);

const prsIn = (from, to) => dom.window.computeView(from, to).totals.prs_created_in_window;
const full = prsIn(collectFrom, collectTo);
const d90 = prsIn(addDays(collectTo, -89), collectTo);
const d30 = prsIn(addDays(collectTo, -29), collectTo);
const d7 = prsIn(addDays(collectTo, -6), collectTo);
check('a shorter range holds strictly fewer PRs', full >= d90 && d90 > d30 && d30 > d7 && d7 > 0,
  `full ${full} / 90d ${d90} / 30d ${d30} / 7d ${d7}`);

const clickPreset = (label) => {
  const b = presets.find((x) => x.textContent === label);
  b.dispatchEvent(new dom.window.Event('click'));
};
clickPreset('최근 7일');
check('clicking a preset moves the dates',
  spanOf(fromInput.value, toInput.value) === 7, `${fromInput.value} ~ ${toInput.value}`);
check('clicking a preset re-aggregates the page',
  doc.getElementById('rangeChip').textContent.includes('PR ' + d7.toLocaleString() + '건'),
  doc.getElementById('rangeChip').textContent);
check('7-day window redrew the reviewer half',
  doc.querySelectorAll('#reviewerSections section').length >= 7);

fromInput.value = '2000-01-01';
toInput.dispatchEvent(new dom.window.Event('change'));
check('a start date before the collection window is clamped',
  fromInput.value === collectFrom, fromInput.value);
check('clamping is reported to the user',
  doc.getElementById('clampChip').style.display !== 'none'
  && doc.getElementById('clampChip').textContent.includes(collectFrom));

const manualFrom = addDays(collectTo, -20);
fromInput.value = manualFrom;
toInput.value = collectTo;
fromInput.dispatchEvent(new dom.window.Event('change'));
check('a hand-typed range is honoured',
  fromInput.value === manualFrom && doc.getElementById('rangeChip').textContent.includes('21일'),
  doc.getElementById('rangeChip').textContent);

/* ---------- 3. engine vs the Python reference ---------- */
clickPreset('전체');
check('the whole-collection preset selects the reference window',
  fromInput.value === collectFrom && toInput.value === collectTo,
  `${fromInput.value} ~ ${toInput.value}`);

const view = dom.window.computeView(collectFrom, collectTo);

for (const key of Object.keys(view.totals)) {
  if (!(key in ref.totals)) continue;
  check(`totals.${key} == Python`, near(view.totals[key], ref.totals[key], 0.02),
    `${view.totals[key]} vs ${ref.totals[key]}`);
}

const exactKeys = [
  'requested_prs', 'fulfilled_prs', 'outstanding_open', 'merged_without_review', 'reviews_given',
  'reviewed_prs', 'latency_samples', 'inline_comments', 'approved', 'changes_requested',
  'commented', 'dismissed', 'verdicts', 'unsolicited_prs', 'requested_churn', 'fulfilled_churn',
  'reviewed_churn', 'latency_small_samples', 'latency_large_samples',
];
const roundedKeys = [
  'response_rate', 'merged_without_review_rate', 'latency_p50_h', 'latency_p90_h', 'latency_mean_h',
  'comments_per_review', 'substantive_review_rate', 'approve_rate', 'changes_rate',
  'changes_per_100_reviews', 'requested_churn_share', 'churn_response_rate', 'reviewed_churn_share',
  'reviewed_churn_p50', 'reviewed_churn_mean', 'latency_small_p50_h', 'latency_large_p50_h',
  'latency_size_gap_h',
];
const engineByReviewer = Object.fromEntries(view.reviewers.map((r) => [r.reviewer, r]));
const refByReviewer = Object.fromEntries(ref.reviewers.created.map((r) => [r.reviewer, r]));
check('engine found the same reviewer roster as Python',
  JSON.stringify(Object.keys(engineByReviewer).sort()) === JSON.stringify(Object.keys(refByReviewer).sort()),
  `${Object.keys(engineByReviewer).length} vs ${Object.keys(refByReviewer).length}`);
let exactBad = [], roundedBad = [];
for (const [login, r] of Object.entries(refByReviewer)) {
  const e = engineByReviewer[login];
  if (!e) continue;
  for (const k of exactKeys) if (e[k] !== r[k]) exactBad.push(`${login}.${k}: ${e[k]} vs ${r[k]}`);
  for (const k of roundedKeys) {
    const tol = k.endsWith('_rate') || k.endsWith('_share') ? 0.0002 : 0.05;
    if (!near(e[k], r[k], tol)) roundedBad.push(`${login}.${k}: ${e[k]} vs ${r[k]}`);
  }
}
check('every reviewer count/sum matches Python exactly', exactBad.length === 0, exactBad.slice(0, 4).join(' | '));
check('every reviewer rate/percentile matches Python within rounding', roundedBad.length === 0,
  roundedBad.slice(0, 4).join(' | '));

const bucketBad = [];
view.size_overview.buckets.forEach((b, i) => {
  const r = ref.size_overview.buckets[i];
  for (const k of ['bucket', 'prs', 'churn', 'changed_files', 'merged', 'reviewed_prs',
    'merged_without_review', 'reviews', 'inline_comments', 'approved', 'changes_requested', 'verdicts']) {
    if (b[k] !== r[k]) bucketBad.push(`${b.bucket}.${k}: ${b[k]} vs ${r[k]}`);
  }
  for (const k of ['prs_share', 'churn_share', 'changed_files_share', 'review_coverage',
    'changes_rate', 'merged_without_review_rate']) {
    if (!near(b[k], r[k], 0.0002)) bucketBad.push(`${b.bucket}.${k}: ${b[k]} vs ${r[k]}`);
  }
  for (const k of ['churn_p50', 'files_p50', 'latency_p50_h', 'latency_p90_h', 'reviews_per_pr', 'comments_per_pr']) {
    if (!near(b[k], r[k], 0.05)) bucketBad.push(`${b.bucket}.${k}: ${b[k]} vs ${r[k]}`);
  }
});
check('size bucket table matches Python', bucketBad.length === 0, bucketBad.slice(0, 4).join(' | '));
for (const k of ['churn', 'changed_files', 'additions', 'deletions', 'prs', 'approved', 'changes_requested']) {
  check(`size totals.${k} == Python`, view.size_overview.totals[k] === ref.size_overview.totals[k],
    `${view.size_overview.totals[k]} vs ${ref.size_overview.totals[k]}`);
}
check('churn concentration matches Python',
  near(view.size_overview.totals.top_decile_churn_share, ref.size_overview.totals.top_decile_churn_share, 0.0002),
  `${view.size_overview.totals.top_decile_churn_share} vs ${ref.size_overview.totals.top_decile_churn_share}`);

const engineRepos = Object.fromEntries(view.repos.map((r) => [r.repo, r]));
const refRepos = Object.fromEntries(ref.repos.map((r) => [r.repo, r]));
check('engine found the same repositories as Python',
  JSON.stringify(Object.keys(engineRepos).sort()) === JSON.stringify(Object.keys(refRepos).sort()),
  `${Object.keys(engineRepos).length} vs ${Object.keys(refRepos).length}`);
const repoBad = [];
for (const [name, r] of Object.entries(refRepos)) {
  const e = engineRepos[name];
  if (!e) continue;
  for (const k of ['prs_created', 'prs_merged', 'prs_open', 'prs_closed_unmerged', 'distinct_authors',
    'churn', 'additions', 'deletions', 'changed_files', 'churn_max', 'large_prs', 'reviewed_prs',
    'reviews', 'approved', 'changes_requested', 'inline_comments']) {
    if (e[k] !== r[k]) repoBad.push(`${name}.${k}: ${e[k]} vs ${r[k]}`);
  }
  for (const k of ['prs_share', 'churn_share', 'changed_files_share', 'large_pr_rate',
    'review_coverage', 'changes_rate']) {
    if (!near(e[k], r[k], 0.0002)) repoBad.push(`${name}.${k}: ${e[k]} vs ${r[k]}`);
  }
  for (const k of ['weight_index', 'churn_p50', 'churn_p90', 'churn_mean', 'latency_p50_h', 'latency_p90_h']) {
    if (!near(e[k], r[k], 0.05)) repoBad.push(`${name}.${k}: ${e[k]} vs ${r[k]}`);
  }
}
check('every repo row matches Python', repoBad.length === 0, repoBad.slice(0, 4).join(' | '));

const engineAuthors = Object.fromEntries(view.pr_authors.map((r) => [r.author, r]));
const authorBad = [];
for (const r of ref.pr_authors) {
  const e = engineAuthors[r.author];
  if (!e) { authorBad.push(`${r.author}: missing`); continue; }
  for (const k of ['prs_created', 'churn', 'changed_files']) {
    if (e[k] !== r[k]) authorBad.push(`${r.author}.${k}: ${e[k]} vs ${r[k]}`);
  }
  for (const k of ['prs_share', 'churn_share']) {
    if (!near(e[k], r[k], 0.0002)) authorBad.push(`${r.author}.${k}: ${e[k]} vs ${r[k]}`);
  }
  for (const k of ['weight_index', 'churn_p50', 'churn_mean']) {
    if (!near(e[k], r[k], 0.05)) authorBad.push(`${r.author}.${k}: ${e[k]} vs ${r[k]}`);
  }
}
check('every PR author row matches Python', authorBad.length === 0, authorBad.slice(0, 4).join(' | '));

const bulkBad = [];
for (const k of ['prs_with_requests']) {
  if (view.bulk_request_evidence[k] !== ref.bulk_request_evidence[k]) {
    bulkBad.push(`${k}: ${view.bulk_request_evidence[k]} vs ${ref.bulk_request_evidence[k]}`);
  }
}
for (const k of ['reviewers_per_pr_mean', 'reviewers_per_pr_p50', 'first_request_delay_p50_h', 'first_request_delay_p90_h']) {
  if (!near(view.bulk_request_evidence[k], ref.bulk_request_evidence[k], 0.05)) {
    bulkBad.push(`${k}: ${view.bulk_request_evidence[k]} vs ${ref.bulk_request_evidence[k]}`);
  }
}
check('review request pattern matches Python', bulkBad.length === 0, bulkBad.join(' | '));

const refDetail = ref.reviewer_detail[meta.default_reviewer];
const engineDetail = view.detail(meta.default_reviewer);
check('reviewer requested churn matches Python',
  engineDetail.requested_churn === refDetail.requested_churn,
  `${engineDetail.requested_churn} vs ${refDetail.requested_churn}`);
const detailBad = [];
engineDetail.by_size.forEach((b, i) => {
  const r = refDetail.by_size[i];
  for (const k of ['bucket', 'requested', 'reviewed', 'churn', 'reviews', 'inline_comments',
    'approved', 'changes_requested', 'verdicts', 'outstanding_open', 'merged_without_review']) {
    if (b[k] !== r[k]) detailBad.push(`by_size ${b.bucket}.${k}: ${b[k]} vs ${r[k]}`);
  }
  for (const k of ['requested_share', 'response_rate', 'churn_share', 'changes_rate']) {
    if (!near(b[k], r[k], 0.0002)) detailBad.push(`by_size ${b.bucket}.${k}: ${b[k]} vs ${r[k]}`);
  }
  for (const k of ['latency_p50_h', 'latency_p90_h', 'comments_per_review']) {
    if (!near(b[k], r[k], 0.05)) detailBad.push(`by_size ${b.bucket}.${k}: ${b[k]} vs ${r[k]}`);
  }
});
const engRepoDet = Object.fromEntries(engineDetail.by_repo.map((r) => [r.repo, r]));
for (const r of refDetail.by_repo) {
  const e = engRepoDet[r.repo];
  if (!e) { detailBad.push(`by_repo ${r.repo}: missing`); continue; }
  for (const k of ['requested', 'reviewed', 'outstanding_open', 'merged_without_review',
    'requested_churn', 'reviewed_churn', 'repo_prs_total']) {
    if (e[k] !== r[k]) detailBad.push(`by_repo ${r.repo}.${k}: ${e[k]} vs ${r[k]}`);
  }
}
check('reviewer size and repo breakdowns match Python', detailBad.length === 0, detailBad.slice(0, 4).join(' | '));
check('latency histogram matches Python',
  JSON.stringify(engineDetail.latency_histogram) === JSON.stringify(refDetail.latency_histogram),
  JSON.stringify(engineDetail.latency_histogram).slice(0, 160));
check('review state mix matches Python',
  JSON.stringify(engineDetail.review_state_mix) === JSON.stringify(refDetail.review_state_mix),
  JSON.stringify(engineDetail.review_state_mix));

/* ---------- internal consistency of whatever window is on screen ---------- */
const shown = dom.window.computeView(fromInput.value, toInput.value);
check('size buckets cover every PR in the window',
  sum(shown.size_overview.buckets, 'prs') === shown.totals.prs_created_in_window,
  `${sum(shown.size_overview.buckets, 'prs')} vs ${shown.totals.prs_created_in_window}`);
check('size bucket count shares sum to 100%', near(sum(shown.size_overview.buckets, 'prs_share'), 1, 0.001),
  (sum(shown.size_overview.buckets, 'prs_share') * 100).toFixed(2) + '%');
check('size bucket churn shares sum to 100%', near(sum(shown.size_overview.buckets, 'churn_share'), 1, 0.001),
  (sum(shown.size_overview.buckets, 'churn_share') * 100).toFixed(2) + '%');
check('repo churn sums to the window total',
  sum(shown.repos, 'churn') === shown.totals.churn_total,
  `${sum(shown.repos, 'churn')} vs ${shown.totals.churn_total}`);
check('repo count shares sum to 100%', near(sum(shown.repos, 'prs_share'), 1, 0.001),
  (sum(shown.repos, 'prs_share') * 100).toFixed(2) + '%');
check('author churn shares sum to 100%', near(sum(shown.pr_authors, 'churn_share'), 1, 0.001),
  (sum(shown.pr_authors, 'churn_share') * 100).toFixed(2) + '%');
check('verdict counts equal approved + changes for every reviewer',
  shown.reviewers.every((r) => r.verdicts === r.approved + r.changes_requested));
check('daily series has one point per day in the window',
  shown.daily_volume.length === spanOf(fromInput.value, toInput.value),
  `${shown.daily_volume.length} vs ${spanOf(fromInput.value, toInput.value)}`);
check('daily PR counts sum to the window total',
  sum(shown.daily_volume, 'prs_created') === shown.totals.prs_created_in_window,
  `${sum(shown.daily_volume, 'prs_created')} vs ${shown.totals.prs_created_in_window}`);

/* ---------- what is on screen agrees with the engine ---------- */
const leaderboard = doc.querySelector('#orgSections table');
check('leaderboard row count == engine',
  leaderboard.querySelectorAll('tbody tr').length === shown.reviewers.length,
  `${leaderboard.querySelectorAll('tbody tr').length} vs ${shown.reviewers.length}`);
const rowFor = (login) =>
  [...leaderboard.querySelectorAll('tbody tr')].find((r) => r.cells[0].textContent === login);
const figuresMatch = (login) => {
  const r = shown.reviewers.find((x) => x.reviewer === login);
  const row = rowFor(login);
  if (!row || !r) return ['row missing', ''];
  return [
    [...row.cells].slice(1, 5).map((c) => c.textContent).join('|'),
    [r.requested_prs.toLocaleString(), r.fulfilled_prs.toLocaleString(),
      (r.response_rate * 100).toFixed(1) + '%', r.reviews_given.toLocaleString()].join('|'),
  ];
};
const [s1, e1] = figuresMatch(pick.value);
check('selected reviewer row figures == engine', s1 === e1, `${s1} vs ${e1}`);
check('selected reviewer row is highlighted', rowFor(pick.value)?.classList.contains('picked') === true);

const headlineOf = () => doc.querySelector('#reviewerSections h2 span').textContent;
check('per-reviewer heading names the selected reviewer', headlineOf().startsWith(pick.value), headlineOf());
const other = shown.reviewers.map((r) => r.reviewer).find((l) => l !== pick.value);
pick.value = other;
pick.dispatchEvent(new dom.window.Event('change'));
check('switching the picker redraws the per-reviewer half', headlineOf().startsWith(other), headlineOf());
check('highlight followed the switch', rowFor(other)?.classList.contains('picked') === true);
const [s2, e2] = figuresMatch(other);
check('switched reviewer row figures == engine', s2 === e2, `${s2} vs ${e2}`);

const sizeHeads = [...doc.querySelectorAll('h2 span')].map((n) => n.textContent);
check('org change-size section rendered', sizeHeads.includes('변경 규모 분포'));
check('daily volume section rendered', sizeHeads.includes('조직 전체 일별 볼륨'));
check('per-reviewer size section rendered', sizeHeads.some((h) => h === other + ' PR 크기별'));
check('heaviest-PR section rendered', sizeHeads.some((h) => h === other + ' 가장 큰 PR'));

const sizeTable = [...doc.querySelectorAll('#orgSections table')].find(
  (t) => t.querySelector('thead th')?.textContent === '크기'
    && [...t.querySelectorAll('thead th')].some((th) => th.textContent === '변경량 비중'));
const lastBand = shown.size_overview.buckets[shown.size_overview.buckets.length - 1];
check('size bucket table drew every band',
  sizeTable && sizeTable.querySelectorAll('tbody tr').length === shown.size_overview.buckets.length,
  `${sizeTable ? sizeTable.querySelectorAll('tbody tr').length : 0}`);
const shownShare = sizeTable && [...sizeTable.querySelectorAll('tbody tr')]
  .find((r) => r.cells[0].textContent === lastBand.bucket)?.cells[4].textContent;
check('largest band churn share on screen == engine',
  shownShare === (lastBand.churn_share * 100).toFixed(1) + '%', `${shownShare}`);

const links = doc.querySelectorAll('tbody a[href^="https://github.com/"]').length;
check('PR drill-down links rendered', links > 0, `${links} links`);
check('no script error after interaction', errors.length === 0, errors.slice(0, 2).join(' | ').slice(0, 300));

process.exit(failures.length ? 1 : 0);
