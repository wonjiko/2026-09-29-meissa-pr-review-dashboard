# 2026-09-29-meissa-pr-review-dashboard

CARTA-IS(Meissa) 조직의 Pull Request와 리뷰 기록을 GitHub GraphQL API에서 수집해
SQLite로 적재하고, 리뷰어별 지표 대시보드를 정적 HTML로 생성한다.
조직의 모든 리뷰어를 수집하며 대시보드 상단 선택기로 전환한다. 기본값은
`JUNYEONGLEE-Derek`(이준영)이고 `config.json`의 `default_reviewer`로 바꾼다.

수집 기간은 2026-06-01부터 실행일까지이며 PR 생성일(`created`) 기준이다.
archived 레포를 포함한다.

기간은 두 층으로 나뉜다.

**수집 범위** — `config.json`의 `window_start` / `window_end`. GitHub에서 실제로 받아오는
범위이고, 바꾸면 재수집이 필요하다.

**조회 기간** — 대시보드 상단에서 start ~ end로 직접 고른다. 기본값은 오늘 기준 이전
`view_default_days`일(90일)이고, 최근 7일 / 30일 / 90일 / 전체 프리셋이 있다.
수집 범위 밖은 자동으로 잘리고 상단에 경고 칩이 뜬다. 조회 기간을 바꾸면 카드·표·차트가
전부 그 기간으로 다시 계산된다. 재수집도 재생성도 필요 없다.

## 실행

```bash
./run.sh              # 전체 파이프라인
./run.sh repos        # 레포 목록 + 검증 기준값만 재수집
./run.sh prs          # PR 재수집 후 하위 단계 전부
./run.sh prs saturn carme   # 특정 레포만 재수집
./run.sh offline      # 네트워크 없이 outputs/raw/ 에서 DB·대시보드 재생성
./run.sh dashboard    # 집계 + 렌더만
./run.sh check        # 생성된 HTML을 실제 DOM에 올려 렌더 검증
```

산출물은 `outputs/dashboard/index.html`. `open outputs/dashboard/index.html`으로 바로 열린다.
`gh auth status`가 통과하는 상태여야 하며 `read:org`, `repo` 스코프가 필요하다.

설정은 전부 `config.json`에 있다. 수집 기간, 기본 리뷰어, 기본 조회 일수, archived 포함 여부,
페이지 크기, 봇 계정 목록, 배포 대상 레포(`publish_repo`)를 여기서 바꾼다.
`view_default_days`와 `default_reviewer`는 렌더만 다시 하면 되고(`./run.sh dashboard`),
수집 기간을 바꾸면 `./run.sh`를 다시 돌린다. `publish_repo`는 배포 단계만 쓴다.

## 대시보드 구성

상단 컨트롤 바는 sticky다. 스크롤을 내려도 리뷰어 선택기와 기간 입력이 화면에 남는다.
컨트롤 바에는 입력에 반응하는 것만 둔다 — 리뷰어 선택기, start~end 날짜, 프리셋,
현재 조회 기간 칩, 범위 클램프 경고 칩. 수집 설정처럼 페이지 내내 고정인 표시
(`기간 기준: PR 생성일`, `archived 레포 포함/제외`)는 헤더로 내렸다. 렌더 검증이
이 배치를 확인하므로 새 칩을 컨트롤 바에 넣으려면 검사부터 고쳐야 한다.

페이지는 **범위 그룹(scope group)** 두 개로 나뉜다. 각 그룹은 테두리 색이 다르고, 컨트롤 바
바로 아래에 붙는 sticky 배너를 가진다. 배너에 그룹의 범위 배지와 지표 정의 패널이 들어 있다.

| 그룹 | 배지 | 범위 | 선택기 반응 |
| --- | --- | --- | --- |
| `#gReviewer` (보라) | 리뷰어 선택에 따라 바뀜 | 선택한 리뷰어 한 사람 | 리뷰어·기간 모두에 반응 |
| `#gOrg` (파랑) | 리뷰어 선택과 무관 · 고정 | 리뷰어 전원·레포 전체 합산 | 기간에만 반응 |

리뷰어를 바꿔도 `#gOrg`의 수치는 한 글자도 바뀌지 않는다. 유일한 변화는 리뷰어 전체 비교
표에서 강조되는 행이 옮겨가는 것이고, 렌더 검증이 이 둘을 각각 확인한다.

표는 세로 스크롤을 자체적으로 만들지 않는다. 페이지 스크롤 하나로만 움직이고, 긴 목록은
행을 전부 펼친다. 컬럼이 많아 넘치는 표만 가로로 스크롤하며 그때 첫 컬럼(레포명·계정명·PR)이
`position: sticky; left: 0`으로 고정돼 행을 알아볼 수 있다. 렌더 검증이 `max-height`가
스타일시트에 없는지, 모든 표가 `.xscroll` 래퍼 안에 있는지 확인한다.

| 구역 | 그룹 | 내용 |
| --- | --- | --- |
| 리뷰어 요약 | 리뷰어 | 요청·이행·응답률·지연·미응답·리뷰 품질·verdict 비율·변경량 비중 카드 20개 |
| 미이행 잔량 추이 | 리뷰어 | 일자별 신규 요청 / 첫 리뷰 / 일 마감 시점 잔량 |
| 첫 응답 지연 분포 | 리뷰어 | 1h~168h 버킷 히스토그램 |
| PR 크기별 | 리뷰어 | 크기 6구간별 갯수·변경량 비중, 응답률, 첫 응답 p50/p90, CHANGES 비율 |
| 상세 분포 | 리뷰어 | 레포별 / PR 작성자별 요청·리뷰·응답률·변경량 비중·PR당 변경량·p50 |
| 가장 큰 PR | 리뷰어 | 요청받은 PR 중 변경량 상위 30건. 리뷰 여부·첫 응답·verdict 포함 |
| 미응답 열린 PR | 리뷰어 | PR 링크와 대기 시간, 크기 |
| 리뷰 없이 머지된 PR | 리뷰어 | PR 링크와 요청·머지 시각, 크기 |
| 리뷰어 전체 비교 | 조직 | 조회 기간에 요청이 있는 리뷰어 전원. 이름을 누르면 위쪽 그룹이 전환됨 |
| 변경 규모 분포 | 조직 | 조직 전체 크기 6구간. 갯수/변경량/파일 비중, 커버리지, 지연, verdict |
| 리뷰 요청 패턴 | 조직 | PR당 리뷰어 수 분포, 생성→첫 요청 지연 |
| 조직 일별 볼륨 | 조직 | 일자별 PR 생성·머지, 리뷰 제출 |
| 레포별 분포 | 조직 | 갯수 비중, 변경량 비중, 가중 지수, 크기 분위, 지연, CHANGES 비율 |
| PR 작성자별 분포 | 조직 | 갯수 비중, 변경량 비중, 가중 지수, PR 중앙·평균 크기 |

### 기간을 바꿀 수 있게 만든 방식

`data.json`은 한 기간의 집계 결과가 아니라 **사실값 자체**를 담는다. PR 2,165건,
요청쌍 6,384건, 리뷰 3,558건을 컬럼 배열로 싣고(레포·계정 문자열은 인덱스로,
시각은 epoch 초로, PR url은 규칙이 일정해 생략) 페이지가 선택한 기간으로 직접 집계한다.

`scripts/render.py`의 페이지 스크립트에 `scripts/aggregate.py`와 같은 집계 로직이 들어 있다.
두 구현이 갈라지는 것을 막기 위해 `data.json`에 `reference` 블록을 함께 싣는다.
`reference`는 **수집 범위 전체**에 대해 Python이 facts.db에서 계산한 같은 수치이고,
페이지는 이 값을 화면에 쓰지 않는다. `./run.sh check`가 페이지 엔진에 수집 범위 전체를
계산시켜 `reference`와 대조한다. 건수·합계·churn은 물론 반올림하는 값까지 마지막 자리까지
일치해야 한다. 허용 오차는 부동소수 표현 오차만 흡수하는 1e-9이다.

두 구현을 일치시킬 때 걸리는 함정이 둘 있다.

- **자리수가 다르면 이중 반올림이 된다.** 같은 값을 Python이 1자리, JS가 2자리로 반올림하면
  432.3478 -> 432.35 -> 432.4가 되어 Python의 432.3과 어긋난다. 페이지 엔진의 `r1`/`r2`/`r3`/`r4`/`r6`은
  `aggregate.py`의 대응되는 `round()` 자리수와 반드시 같아야 한다.
- **동점 처리 방향이 다르다.** Python `round()`는 동점을 짝수 자리로 보내고 JS `toFixed()`는
  0에서 멀어지는 쪽으로 올린다. 동점은 실제로 발생한다 -- 563.25는 정확히 표현되는 값이라
  Python은 563.2, `toFixed(1)`은 563.3을 낸다. 페이지의 `pyRoundTo`가 값의 정확한 십진 전개
  위에서 half-even으로 반올림해 Python과 맞춘다. 이 함수는 `window.pyRoundTo`로 노출돼
  검증이 규칙 자체를 직접 확인한다.

## 파이프라인

레포에 들어 있는 것은 입력과 코드뿐이다. 스크립트가 쓰는 모든 것은 `outputs/` 아래에 있고
git 추적 대상이 아니다. `outputs/`를 통째로 지워도 `./run.sh` 한 번이면 복구된다.

```
config.json     수집 범위·기본 리뷰어·기본 조회 일수. 손으로 고치는 유일한 입력
run.sh          단계 실행기
scripts/        6단계 + 검증
outputs/raw/        GraphQL 응답 원본. 수집 후 불변
outputs/build/      facts.db, verification.json, domcheck/(jsdom)
outputs/dashboard/  data.json, index.html
```

| 단계 | 스크립트 | 입력 | 출력 |
| --- | --- | --- | --- |
| 1 | `scripts/fetch_repos.py` | GitHub API | `outputs/raw/meta/repos.json`, `outputs/raw/meta/counts/*.json` |
| 2 | `scripts/fetch_prs.py` | `outputs/raw/meta/repos.json` | `outputs/raw/prs/<repo>/*.json` |
| 3 | `scripts/build_db.py` | `outputs/raw/` | `outputs/build/facts.db` |
| 4 | `scripts/verify.py` | `outputs/build/facts.db`, GitHub search API | `outputs/build/verification.json` |
| 5 | `scripts/aggregate.py` | `outputs/build/facts.db` | `outputs/dashboard/data.json` |
| 6 | `scripts/render.py` | `outputs/dashboard/data.json` | `outputs/dashboard/index.html` |

경로는 `scripts/ghclient.py`의 `OUTPUTS` / `RAW` / `BUILD` / `DASHBOARD` 상수 한 곳에서만
정의된다. 출력 위치를 옮기려면 그 상수와 `run.sh`의 `OUT`만 고치면 된다.

`scripts/ghclient.py`는 공용 모듈이다. `gh` CLI를 통해 GraphQL을 호출하고
모든 응답을 `_meta`(쿼리 종류, 파라미터, 수집 시각, rateLimit)와 함께 `outputs/raw/`에 원본 그대로 저장한다.

`outputs/raw/`는 수집 이후 수정하지 않는다. 3단계 이후는 `outputs/raw/`만 입력으로 받으므로
네트워크 없이 몇 번이든 재생성할 수 있다. 대시보드의 모든 수치는 `facts.db` 질의 결과이며
`outputs/dashboard/data.json`에 그대로 들어 있다. HTML에는 데이터가 JSON으로 임베드되고
표·차트는 페이지가 그 JSON에서 그린다.

## 수집 방식

**created 패스** — `pullRequests(orderBy: {field: CREATED_AT, direction: DESC})`를
커서로 내려가며 `createdAt`이 기간 시작 이전이 되면 멈춘다. `CREATED_AT`은 변하지 않으므로
수집 중 새 PR이 생겨도 페이지 경계가 밀리지 않는다.

**backfill 패스** — 기간 이전에 생성됐지만 기간 안에 갱신된 PR. search API로 번호를 모은 뒤
`pullRequest(number:)` 앨리어스를 한 쿼리에 20개씩 묶어 가져온다.

**overflow 패스** — `reviews` 또는 `timelineItems`가 한 페이지를 넘긴 PR만 번호를 지정해
커서로 끝까지 추가 수집한다.

### API 함정

- `timelineItems.totalCount`는 `itemTypes` 필터를 무시한다. 노드 5개인데 8을 반환하는 경우가 있다.
  페이징과 집계는 `pageInfo` 커서와 실제 노드만 사용한다.
- search API는 쿼리당 1,000건 상한이다. 조직 단위 단일 쿼리로는 전량을 받을 수 없어
  레포 단위로 분리한다. backfill 검색이 상한에 닿으면 2단계 로그에 경고가 남는다.
- `reviewRequests`(현재 pending 스냅샷)는 정리되지 않은 항목이 남는다. 대기 상태는
  `ReviewRequestedEvent` / `ReviewRequestRemovedEvent` 타임라인 이벤트와 리뷰 제출 시각을
  맞춰 계산하고, 스냅샷은 `pending_review_requests` 테이블에 따로 보관해 대조용으로만 쓴다.
- 작성자가 자기 PR에 남긴 리뷰가 `reviews`에 섞인다. 인라인 코멘트 답글도 `COMMENTED` 리뷰로 기록되므로
  양이 상당하다(현재 8,494건 중 4,587건). 리뷰어 지표에서 전부 제외한다.
- 봇 리뷰어는 이름 목록이 아니라 `author_type` / `reviewer_type`이 `Bot`인지로 판별한다.
  `config.json`의 `bot_logins`는 `User` 타입으로 보이는 자동화 계정을 추가로 제외할 때만 쓴다.
- 리뷰 요청은 PR 생성 직후 팀 전원에게 일괄로 나가는 경우가 많다. 요청 건수만으로는
  리뷰어가 구분되지 않으므로 대시보드는 요청 이후 행동(응답률, 지연, 미이행)을 지표로 쓴다.
  PR당 리뷰어 수 분포와 생성→첫 요청 지연은 `리뷰 요청 패턴` 구역에서 확인한다.

## facts.db 스키마

| 테이블 | 내용 |
| --- | --- |
| `meta` | 빌드 시각, 기간, 기본 리뷰어, raw 페이지 수, 2단계 통계 |
| `repos` | 레포 메타데이터와 검증 기준값(search issueCount) |
| `pull_requests` | PR 사실값. `window_source`는 `created` 또는 `updated`(backfill) |
| `pending_review_requests` | 수집 시점의 pending 스냅샷 |
| `review_request_events` | 요청/철회 타임라인 이벤트 |
| `draft_events` | ready_for_review / convert_to_draft |
| `reviews` | 리뷰 단위. 본문 길이와 인라인 코멘트 수 포함 |

결측은 0이 아니라 NULL로 둔다. "없음"과 "못 가져옴"을 구분해야 한다.

## 지표 정의

요청 쌍 = (PR, 사람 리뷰어). 팀 요청과 봇, 작성자 자신은 제외한다.

| 지표 | 정의 |
| --- | --- |
| 요청받은 PR | 요청 이벤트가 있는 PR 수 |
| 응답률 (요청받은 PR 대비) | 리뷰를 남긴 PR 수 ÷ 요청받은 PR 수 |
| 응답률 (요청받은 변경량 대비) | 리뷰를 남긴 PR의 churn 합 ÷ 요청받은 PR의 churn 합 |
| 첫 응답 지연 | 첫 요청 시각 → 요청 이후 첫 리뷰 제출 시각. p50 / p90 |
| 미응답·열린 PR | 리뷰 없이 아직 OPEN인 PR |
| 미응답 머지 | 요청받았으나 리뷰 없이 머지된 PR |
| 내용 있는 리뷰 비율 | 본문 또는 인라인 코멘트가 있는 리뷰 ÷ 그 리뷰어가 남긴 리뷰 수 |
| 요청 외 리뷰 | 요청 이벤트 없이 리뷰를 남긴 PR |
| 주별 잔량 | 각 주 종료 시점에 요청됐고 리뷰·철회·PR 종료가 모두 없는 쌍의 수 |
| CHANGES 비율 | `CHANGES_REQUESTED` ÷ (`APPROVED` + `CHANGES_REQUESTED`). `COMMENTED`·`DISMISSED`는 분모에서 제외 |

### 비율 라벨 규칙

화면의 모든 비율은 이름 뒤 괄호나 표 헤더 둘째 줄에 **분모**를 적는다. 카드에는
분자/분모 실제 값도 함께 적는다. 분모가 셋이나 있어 이름만으로는 구분되지 않기 때문이다.

| 분모 | 어디에 쓰이는지 |
| --- | --- |
| 조회 기간에 생성된 전체 PR / 전체 churn | 조직 구역의 갯수 비중·변경량 비중, 리뷰어의 `요청 변경량 비중` |
| 그 리뷰어가 요청받은 전체 PR / churn | 리뷰어 구역의 크기별·레포별·작성자별 비중 |
| 그 행 자신의 요청 수 | 각 행의 응답률·커버리지 |

`리뷰 커버리지`(조직)와 `응답률`(리뷰어)은 이름이 달라도 혼동하기 쉬운 쌍이다. 커버리지는
**누구든** 리뷰했는지를 그 구간·레포의 PR 수로 나눈 값이고, 응답률은 **지정된 그 사람**이
리뷰했는지를 그 사람의 요청 수로 나눈 값이다.

각 그룹 배너의 `이 구역 지표 정의` 패널에 같은 내용이 들어 있고, 렌더 검증이
비율 컬럼·카드에 분모 표기가 빠진 것이 없는지 확인한다.

### 변경 규모

크기(churn) = `additions` + `deletions`. GitHub이 PR에 보고하는 값을 그대로 쓴다.
구간은 관측 분포에 맞춰 잡았다. 어느 구간도 무시할 만큼 작거나 전체를 지배하지 않는다.

| 구간 | churn |
| --- | --- |
| XS | ≤ 10 |
| S | 11–50 |
| M | 51–200 |
| L | 201–500 |
| XL | 501–1000 |
| XXL | > 1000 |

| 지표 | 정의 |
| --- | --- |
| 갯수 비중 | 해당 구간·레포·작성자의 PR 수 ÷ 기간 내 전체 PR 수 |
| 변경량 비중 | 해당 항목의 churn 합 ÷ 기간 내 전체 churn 합 |
| 가중 지수 | 변경량 비중 ÷ 갯수 비중. 1보다 크면 PR 수보다 변경량 쪽이 무거운 항목 |
| 리뷰 커버리지 | 해당 구간 PR 중 사람 리뷰(셀프 제외)가 하나라도 있는 비율 |
| 크기별 첫 응답 차이 | churn ≥ 501인 PR의 첫 응답 p50 − churn ≤ 200인 PR의 첫 응답 p50 |

churn 합계는 전부 기간 내 생성 PR(`created` 기준)을 분모로 쓴다.
리뷰어별 변경량 비중은 PR 하나가 여러 리뷰어에게 요청되므로 리뷰어 간에 겹친다.
합이 100%를 넘는 것이 정상이다. 반면 레포별·작성자별·구간별 비중은 PR을 한 번만 세므로 합이 100%다.

`additions` / `deletions` / `changed_files`가 NULL인 PR은 churn 집계에서 제외한다.
0으로 치환하지 않는다. 현재 기간 내 PR 2,165건 모두 값이 있다.

기간 기준은 PR 생성일(`created`)이다. 조회 기간을 고르면 그 사이에 **생성된** PR만 범위에
들어가고, 그 PR에 달린 요청·리뷰는 생성 시각과 무관하게 전부 포함된다. 요청·리뷰 시각으로
자르지 않는 이유는 기간 끝에 생성된 PR의 리뷰가 잘려 응답률이 실제보다 낮게 보이기 때문이다.

`activity` 기준(생성 시점과 무관하게 기간 내에 요청 또는 리뷰가 발생한 PR)은 `reference`
블록에만 남아 있다. 대시보드는 `created` 기준만 쓴다.

## 검증

`scripts/verify.py`가 `outputs/build/verification.json`을 만들고 하드 실패가 있으면 종료 코드 1을 반환한다.

- A: 레포별 기간 내 PR 수 == search `issueCount`
- B: 레포별 backfill PR 수 == 해당 search `issueCount`
- C: `hasNextPage`를 보고한 모든 체인의 후속 페이지가 디스크에 있음
- D: `window_source`가 `created_at`과 일치
- E: PR 테이블에 없는 PR을 가리키는 리뷰·요청 이벤트가 없음
- F: 대상 리뷰어의 리뷰 PR 수가 독립 search 쿼리와 2% 이내 (경고)
- G: `timelineItems.totalCount` 불일치 표본 기록 (정보)
- H: `additions` / `deletions` / `changedFiles`를 `outputs/raw/` 원본에서 다시 계산해 DB와 대조
- I: 결측 변경량이 0이 아니라 NULL로 남아 있는지 기록 (정보)

`./run.sh check`는 `scripts/check_render.mjs`를 jsdom에 올려 렌더 결과를 검사한다.
현재 104항목이고 네 부류를 본다.

1. 그려졌는지 — 스크립트 오류, 빈 표·빈 차트, 화면 수치와 엔진 계산값의 불일치.
2. 컨트롤이 동작하는지 — 컨트롤 바가 sticky인지, 고정 설정 칩이 컨트롤 바에서 빠져
   헤더에 있는지, 기본 조회 기간이 최근 90일인지,
   프리셋과 직접 입력이 재집계를 일으키는지, 수집 범위 밖 날짜가 잘리고 경고가 뜨는지,
   짧은 기간이 더 적은 PR을 담는지, 리뷰어 전환이 위쪽 그룹을 다시 그리는지.
3. 범위 분리와 레이아웃 규칙이 유지되는지 — 두 그룹이 각자의 섹션만 감싸는지, 배지가 붙어 있는지,
   배너가 sticky인지, 리뷰어를 바꿨을 때 조직 그룹의 HTML이 강조 행을 제외하고 동일한지,
   비율 컬럼과 카드에 분모 표기가 빠진 것이 없는지, 두 응답률이 이름으로 구분되는지,
   스타일시트에 `max-height`가 없고 모든 표가 `.xscroll` 래퍼 안에 있는지.
4. 페이지 엔진이 Python과 같은 답을 내는지 — `reference`와 전면 대조. 리뷰어별 건수·합계,
   크기 구간, 레포, 작성자, 요청 패턴, 리뷰어 상세까지 항목별로 비교한다.
   건수·합계·churn은 물론 반올림 값까지 마지막 자리까지 일치해야 한다(허용 오차 1e-9).
   페이지 엔진의 반올림 자리수는 aggregate.py의 `round()` 자리수와 같아야 하고, 동점은
   Python과 같이 짝수 자리로 보낸다. 이 규칙 자체를 검사하는 항목이 따로 있다.
   비중 합 100%, 일별 시계열 합계 일치 같은 내부 정합성도 함께 본다.

3번의 분모 표기 검사는 라벨에 `비율`·`응답률`·`비중`·`커버리지`·`당 `이 들어간 컬럼과 카드를
전부 모아 `data-den` 속성이나 `.d` 줄이 있는지 확인한다. 새 비율을 추가하고 분모를 적지
않으면 이 검사에서 걸린다.

현재 104항목이다. 첫 실행 시 `outputs/build/domcheck/`에 jsdom을 설치한다.

## 배포 (gh-pages)

`scripts/publish_pages.py`가 `outputs/dashboard/index.html` 한 파일을 `gh-pages` 브랜치에
올린다. 파이프라인은 GitHub 쪽에서 돌리지 않는다 — `gh` 자격과 org 읽기 권한이 필요하고
그 권한을 러너에 두지 않기 위해, 로컬에서 만든 완성 페이지만 올린다.

```bash
./run.sh pages --dry-run   # 무엇이 올라갈지만 보고
./run.sh pages             # gh-pages 브랜치에 커밋 + 푸시 (공개되지 않음)
./run.sh pages --enable    # Pages 사이트를 켠다 (여기서 공개된다)
```

커밋은 git plumbing(`hash-object` / `mktree` / `commit-tree`)으로 만든다. 작업 트리와
체크아웃된 브랜치를 건드리지 않고, 매번 이전 `gh-pages` 커밋의 자식으로 쌓이므로
force push가 필요 없다. 내용이 이전과 같으면 커밋하지 않지만, 대상 레포의 `gh-pages`
tip과 비교해 대상이 아직 그 커밋을 갖고 있지 않으면 푸시는 수행한다. 사이트 활성화는
내용 변경과 무관하게 실행된다.

### 배포 대상 레포

`config.json`의 `publish_repo`가 페이지를 서빙할 레포를 정한다. 비어 있으면 origin이다.
현재 값은 `wonjiko/2026-09-29-meissa-pr-review-dashboard-page`이고, 이 레포는 public이며
`gh-pages` 브랜치에 `index.html`과 `.nojekyll` 두 파일만 들어 있다.

파이프라인 레포(private)와 페이지 레포(public)를 나눈 이유는 두 가지다. Free 플랜에서는
private 레포의 Pages를 켤 수 없고(`422 Your current plan does not support GitHub Pages
for this repository`), 파이프라인 레포를 public으로 바꾸면 페이지에 없는 것 -- 스크립트,
`config.json`의 대상 계정, 이 문서의 턴 기록에 담긴 사람별 수치 -- 까지 함께 공개된다.
페이지 전용 레포는 공개 범위를 페이지 내용 그 자체로 한정한다.

라이브 주소: https://wonjiko.github.io/2026-09-29-meissa-pr-review-dashboard-page/

public 레포에 `gh-pages`를 푸시하면 GitHub가 사이트를 자동으로 켜기 때문에, 이어지는
활성화 POST는 `409 already enabled`를 받는다. 이것이 원하는 상태이므로 성공으로 처리한다.

**Pages 사이트는 공개된다.** URL을 아는 누구나 열 수 있고, 페이지에는 PR 제목 2,165건과
링크, 레포명 25개, GitHub 계정 21개, 사람별 응답률·지연·CHANGES 비율이 담긴다. 이 때문에
브랜치 푸시와 `--enable`을 분리했다. 공개를 내리려면 페이지 레포를 private으로 바꾸거나
삭제한다 -- 파이프라인 레포는 영향을 받지 않는다.

## git

`.gitignore`가 무시하는 것은 `outputs/` 하나다. 그 아래 전부가 스크립트 산출물이고
`outputs/raw/`만 12MB 남짓이다. 클론한 쪽은 `gh auth`를 맞춘 뒤 `./run.sh`를 돌리면
같은 산출물을 얻는다.

## 진행 기록

각 턴이 끝날 때 `scripts/log_turn.py`로 항목을 추가한다.

```bash
python3 scripts/log_turn.py "한 줄 요약" -d "세부" -d "세부" --next "다음 할 일"
```

<!-- turn-log -->

### #1 · 2026-09-29 15:44 KST · `(no commit)`

프로젝트 초기 구축. 6단계 파이프라인·검증·정적 대시보드까지 전부 스크립트로 생성되는 상태로 완료.

- 설정을 config.json 한 곳으로 모음: 기간, 대상 리뷰어(JUNYEONGLEE-Derek), archived 포함, 페이지 크기, 봇 목록.
- 1단계 수집: 95개 레포 중 기간 내 PR이 있는 25개가 범위. 검증 기준값을 레포별 search issueCount로 확보.
- 2단계 수집: created 2,165건 + backfill 114건. 레포 26곳 전부 기준값과 일치. GraphQL 141요청 / 141포인트.
- 3단계 facts.db: pull_requests 2,279 / reviews 8,107 / review_request_events 7,644 / pending 4,209 / draft_events 1,614.
- 4단계 검증 A~G 전부 통과. 대상 리뷰어 리뷰 PR 수 1,597이 독립 search 쿼리와 delta 0.
- 5~6단계: data.json 114KB, 단일 파일 index.html 118KB. ./run.sh check로 jsdom 렌더 검증 10항목 통과.
- 측정 결과 — 요청 1,922 / 이행 1,595 / 응답률 83.0% / 첫 응답 p50 4.5h p90 68.4h / 미응답 열림 21건 / 리뷰 없이 머지 221건(11.5%) / 리뷰당 인라인 코멘트 1.73.
- 일괄 요청 가설 확인됨: PR당 리뷰어 평균 3.27명, 중앙값 3명, PR 생성→첫 요청 p50 0.0h.

다음: 대시보드 실사용 후 지표 조정. 커밋 여부와 CARTA-IS 업로드 여부는 미정.

### #2 · 2026-09-29 15:46 KST · `(no commit)`

봇·셀프리뷰 필터를 이름 목록이 아닌 타입 판별로 교체하고 재생성.

- 리뷰어 판별을 author_type / reviewer_type == 'Bot'로 변경. chatgpt-codex-connector(67), cursor(1)가 리뷰어 표에서 빠져 16행 → 15행.
- 셀프리뷰 규모 확인: 전체 리뷰 8,106건 중 4,302건이 작성자 자신의 리뷰(인라인 코멘트 답글이 COMMENTED 리뷰로 기록됨). 전부 지표에서 제외.
- l2ejin 132건, hsyoon97 78건은 전량 셀프리뷰여서 리뷰어 표에 등장하지 않음 — 제외 로직이 의도대로 동작.
- totals에 bot_reviews / self_reviews 추가하고 대시보드 부제에 제외 규모를 표기.

다음: 대시보드 열어보고 지표·레이아웃 조정.

### #3 · 2026-09-29 15:54 KST · `(no commit)`

결정 사항 반영: created 기준 확정, archived 포함, 리뷰어 선택기 도입(기본 준영님), 폴더명에 날짜·주제 부여.

- 폴더를 Repositories/2026-09-29-meissa-pr-review-dashboard 로 이동.
- config 키를 target_reviewer → default_reviewer 로 변경. 대상 한 명이 아니라 처음 열리는 리뷰어라는 의미.
- 리뷰어별 상세를 로스터 15명 전원에 대해 미리 계산해 data.json의 reviewer_detail에 담음. 상단 select와 비교 표의 이름 클릭으로 전환. data.json 1,235KB / index.html 1,078KB.
- 기간 기준을 created로 고정. 카드·추이·지연 분포·상세·미응답 목록 전부 created 기준. activity는 리뷰어 비교 표의 참고 토글로만 남김.
- 레포별 분포에서 특정 리뷰어 컬럼을 제거하고 언어·작성자 수를 추가. 리뷰어별 수치는 상세 구역이 담당.
- totals에 repos_archived_in_scope 추가. 범위 25개 레포 중 archived 1개(carta-cs 52건 포함).
- 검증 A~G 전부 통과, 렌더 검증 20항목 전부 통과. 선택기 전환 후에도 표·수치가 data.json과 일치하는지까지 검사에 포함.

다음: 대시보드 열어보고 지표·레이아웃 조정.

### #4 · 2026-09-29 18:18 KST · `(no commit)`

PR 변경량(churn) 축을 전 구역에 추가. 갯수 비중과 변경량 비중을 나란히 보고, 크기별 응답시간과 CHANGES 비율을 함께 낸다.

- 재수집 없음. additions/deletions/changedFiles는 1차 수집부터 raw와 facts.db에 있었다. 집계·렌더만 확장.
- churn = additions + deletions. 구간 XS≤10 / S 11-50 / M 51-200 / L 201-500 / XL 501-1000 / XXL>1000. 관측 분포(p50 181, p90 1288)에 맞춰 잡음.
- size_overview 신설: 구간별 갯수·변경량·파일 비중, PR 중앙 크기, 리뷰 커버리지, 첫 응답 p50/p90, PR당 리뷰·코멘트, APPROVED/CHANGES와 CHANGES 비율.
- 레포별 표에 갯수 비중·변경량 비중·가중 지수(변경량비중÷갯수비중)·크기 분위(p50/p90/max)·큰 PR 비율·첫 응답 p50/p90·리뷰 커버리지·CHANGES 비율 추가.
- PR 작성자별 표에 같은 비중·가중 지수·PR 중앙/평균 크기 추가.
- 리뷰어 비교 표에 CHANGES 비율, 요청/리뷰 변경량, 변경량 기준 응답률, 리뷰 PR 중앙 크기, 작은(≤200)·큰(≥501) PR 첫 응답 p50과 그 차이 추가.
- 리뷰어 상세에 'PR 크기별' 구역과 '가장 큰 PR' 30건 표 신설. 레포별·작성자별 표에 변경량 비중·PR당 변경량·p50 추가. 미응답/미응답머지 목록에 크기 열 추가.
- 검증 H 추가: raw 원본에서 additions/deletions/changedFiles를 다시 계산해 DB와 대조. 2,165건 전부 일치, churn 1,576,334 동일. I는 결측이 0이 아니라 NULL로 남는지 기록(정보).
- 렌더 검증 20 -> 38항목. 비중 합 100%, 구간·레포 churn 합 == 전체 churn, changes_rate가 자기 분자/분모와 일치, 새 구역 렌더 여부를 검사.
- 측정 결과 -- 전체 변경량 1,576,334줄 / 27,889파일. XXL(>1000)이 PR 12.1%인데 변경량 75.0%. 상위 10% PR이 71.5%.
- CHANGES 비율이 크기와 함께 단조 증가: XS 1.8% -> S 4.2% -> M 8.5% -> L 11.1% -> XL 12.4% -> XXL 18.2%. 조직 전체 9.7%.
- 첫 응답은 크기와 함께 늘지 않는다. XXL p50 1.9h로 M(4.5h)·L(5.4h)보다 빠르고, 리뷰 커버리지는 79.5%로 가장 낮다.
- 준영님: 요청 변경량 1,363,804줄(전체의 86.5%), 변경량 기준 응답률 78.9%, 크기별 첫 응답 4.5h -> 2.6h. XXL 구간 CHANGES 22.4%.
- 가중 지수 상위: meissa-guard 4.45(PR 1.2% / 변경량 5.6%, 중앙 1,476줄), dji-cloud-api 3.67, carta-core 1.90. carta-frontend는 PR 21.8% / 변경량 35.8%로 1.64.

다음: 대시보드 열어보고 구간 경계·열 구성 조정.

### #5 · 2026-09-29 18:52 KST · `(no commit)`

조회 기간을 대시보드에서 직접 고르도록 바꿨다. 집계를 페이지로 옮기고 컨트롤 바를 sticky로 만들었다.

- 기간이 두 층이 됐다. 수집 범위(config의 window_start/window_end, 바꾸면 재수집)와 조회 기간(페이지에서 start~end 선택). 조회 기간 기본값은 오늘 기준 이전 90일(config의 view_default_days), 프리셋은 최근 7일/30일/90일/전체.
- data.json이 한 기간의 집계 결과가 아니라 사실값을 담는다. PR 2,165 / 요청쌍 6,384 / 리뷰 3,558을 컬럼 배열로 싣는다. 레포·계정은 문자열 테이블 인덱스, 시각은 epoch 초, PR url은 규칙이 일정해 생략하고 페이지가 조립. facts 801KB.
- 리뷰어 15명 상세 사전계산을 제거했다. index.html 1,524KB -> 991KB.
- 페이지에 aggregate.py와 같은 집계 엔진을 넣었다. 리뷰어 표, 크기 구간, 레포별, 작성자별, 요청 패턴, 리뷰어 상세, 일별 시계열 전부 선택한 기간으로 즉시 재계산.
- 두 구현이 갈라지지 않게 data.json에 reference 블록을 싣는다. 수집 범위 전체에 대한 Python 계산값이고 화면에는 쓰지 않는다. check_render가 페이지 엔진에 같은 기간을 계산시켜 전면 대조한다. 건수·합계·churn 완전 일치, 반올림 값은 비율 0.0002 / 시간 0.05 오차.
- Python의 round()는 동점을 짝수로, JS Math.round()는 위로 올린다. 백분위수 인덱스가 짝수 표본 p50에서 정확히 .5가 되므로 JS에 half-even 반올림을 구현해 맞췄다.
- reference totals의 정의 불일치 3건을 고쳤다. human_reviews / review_request_pairs / distinct_reviewers가 DB 전체를 세고 있어 기간 기준으로 바꾸고, DB 전체 수치는 *_all_db로 분리.
- 주별 시계열을 일별로 교체. 잔량 추이와 조직 볼륨 모두 일자별. 400점 초과 시 균등 샘플링.
- 컨트롤 바를 sticky(position:sticky, top:0)로 분리해 스크롤을 내려도 리뷰어 선택기와 기간 입력이 남는다. 표 헤더 sticky와 z-index로 분리.
- 수집 범위 밖 날짜는 자동으로 잘리고 경고 칩이 뜬다. start>end는 교환.
- 렌더 검증 38 -> 82항목. sticky 여부, 기본 90일, 프리셋 동작, 클램프 경고, 짧은 기간이 더 적은 PR을 담는지, 일별 시계열 합계 일치, reference 전면 대조를 포함.
- 기간별 확인 -- 전체 PR 2,165 / 90일 1,579 / 30일 604 / 7일 96. XXL 변경량 비중은 75.0% / 75.9% / 69.6% / 77.5%로 안정. 조직 CHANGES 비율은 9.7% -> 11.5% -> 16.1% -> 15.5%로 최근이 높다.
- .gitignore에 .DS_Store 추가. raw/(12MB)와 build/, 생성물은 추적하지 않는다.

다음: private 레포 생성 후 wonjiko 아래로 푸시.

### #6 · 2026-09-29 22:45 KST · `85bb907`

private 레포 생성 후 푸시 완료.

- wonjiko/2026-09-29-meissa-pr-review-dashboard (private). 추적 파일 13개(스크립트 9, run.sh, config.json, CLAUDE.md, .gitignore) 4,531줄.
- 브랜치명이 initial-import다. main으로의 push가 보호 브랜치 정책에 막혀 피처 브랜치로 올렸고, 현재 레포 기본 브랜치도 initial-import로 잡혀 있다. main으로 바꾸려면 사용자가 직접 실행해야 한다.
- git push가 처음 두 번 멈춘 원인: macOS 키체인 헬퍼가 -25320으로 실패한 뒤 git이 사용자명 입력을 기다렸다. GIT_TERMINAL_PROMPT=0과 credential.helper='!gh auth git-credential'를 명령 단위로 넘겨 해결. git config는 변경하지 않았다.

다음: 대시보드 실사용 후 조회 기간 프리셋·지표 조정.

### #7 · 2026-09-30 10:36 KST · `85bb907`

비율의 분모를 화면에 명시하고, 리뷰어 선택에 반응하는 구역과 조직 전체 구역을 범위 그룹으로 분리했다.

- 페이지를 범위 그룹 두 개로 감쌌다. #gReviewer(보라, 배지 '리뷰어 선택에 따라 바뀜')와 #gOrg(파랑, 배지 '리뷰어 선택과 무관 · 고정'). 각 그룹은 컨트롤 바 아래에 붙는 sticky 배너를 갖고, 배너 높이는 컨트롤 바 실측값으로 맞춘다.
- 리뷰어 그룹 배너에 선택된 계정명과 '이 구역의 모든 수치는 한 사람 기준' 문구를, 조직 그룹 배너에 '리뷰어 전원·레포 전체 합산, 선택과 무관' 문구를 넣었다.
- 비율 이름 뒤 괄호에 분모를 적는 규칙을 도입했다. 표 헤더는 둘째 줄에 '/ 분모'를 작게 적고 th에 data-label/data-den을 남긴다. 카드는 값 아래에 분자/분모 실제 값을 적는다.
- 같은 이름이던 두 지표를 분리했다. 응답률 (요청받은 PR 대비) / 응답률 (요청받은 변경량 대비). 표 컬럼도 응답률(변경량)으로 바꿨다.
- 조직 구역의 리뷰 커버리지가 리뷰어 응답률과 다른 지표임을 정의 패널과 문서에 명시했다.
- 각 그룹에 접이식 '이 구역 지표 정의' 패널을 넣었다. 리뷰어 9항목, 조직 9항목.
- 렌더 검증 82 -> 96항목. 그룹이 각자 섹션만 감싸는지, 배지·sticky 배너가 있는지, 리뷰어를 바꿨을 때 조직 구역 HTML이 강조 행만 빼고 동일한지, 비율 컬럼·카드에 분모 표기가 빠진 것이 없는지, 두 응답률이 이름으로 구분되는지를 검사한다.
- 수집 검증 A~I 9항목 전부 통과. 집계 수치는 변경 없음.

다음: 대시보드 열어보고 그룹 경계·정의 문구 조정.

### #8 · 2026-09-30 11:08 KST · `85bb907`

sticky 컨트롤 바에서 고정 설정 칩 두 개를 빼 헤더로 내렸다. 바가 화면을 덜 가린다.

- '기간 기준: PR 생성일 (created)'와 'archived 레포 포함' 칩을 header로 이동. 두 값은 config에서 오는 고정값이라 스크롤과 함께 사라져도 된다.
- 컨트롤 바에는 입력에 반응하는 것만 남겼다: 리뷰어 선택기, start~end 날짜, 프리셋, 조회 기간 칩, 클램프 경고 칩.
- 렌더 검증 96 -> 99항목. 두 칩이 컨트롤 바 밖·헤더 안에 있는지, 페이지에 여전히 표기되는지, 컨트롤 바가 나머지 다섯 요소를 유지하는지 검사한다.

다음: 대시보드 열어보고 헤더 높이·칩 배치 조정.

### #9 · 2026-09-30 11:19 KST · `85bb907`

표 안의 세로 스크롤을 없애고, 스크립트 산출물을 전부 outputs/ 아래로 옮겼다.

- .scroll(max-height 460px, overflow auto)을 .xscroll(overflow-x만)로 교체. 페이지 스크롤 하나로만 움직이고 긴 목록은 행을 전부 펼친다. 기본 리뷰어의 '리뷰 없이 머지' 표가 221행이라 페이지가 길어졌다.
- 가로로 넘치는 표는 첫 컬럼을 position:sticky left:0으로 고정. 배경은 불투명색이어야 아래 컬럼이 비치지 않는다. hover·picked용 배경도 따로 지정.
- 표 헤더 sticky를 제거했다. overflow-x 컨테이너 안에서는 세로 sticky가 걸리지 않아 죽은 규칙이었다.
- 경로를 outputs/ 아래로 모았다: outputs/raw, outputs/build, outputs/dashboard. ghclient.py의 OUTPUTS 상수와 run.sh의 OUT 한 곳에서만 정의된다.
- .gitignore가 무시하는 것이 outputs/ 하나로 줄었다. 레포 루트에는 config.json, run.sh, scripts/, CLAUDE.md만 남는다.
- outputs/build와 outputs/dashboard를 지우고 ./run.sh offline으로 복구되는 것을 확인했다.
- 렌더 검증 99 -> 103항목. max-height가 스타일시트에 없는지, 모든 표가 .xscroll 래퍼 안에 있는지, 첫 컬럼이 고정인지, 긴 표가 행을 전부 렌더하는지 검사한다.
- 수집 검증 A~I 9항목 전부 통과. 집계 수치 변경 없음.

다음: gh pages 배포 검토.

### #10 · 2026-09-30 11:22 KST · `85bb907`

gh-pages 배포 스테이지를 만들고 브랜치까지 올렸다. Pages 사이트는 켜지 않았다.

- scripts/publish_pages.py 신설. outputs/dashboard/index.html 한 파일과 .nojekyll을 gh-pages 브랜치에 올린다. 파이프라인은 러너에서 돌리지 않는다 — gh 자격과 org 읽기 권한이 필요해서 로컬 산출물만 올리는 쪽을 택했다.
- 커밋을 git plumbing(hash-object/mktree/commit-tree/update-ref)으로 만든다. 작업 트리와 체크아웃 브랜치를 건드리지 않고, 이전 gh-pages 커밋의 자식으로 쌓여 force push가 필요 없다. 트리가 같으면 커밋하지 않는다.
- git 호출에 GIT_CONFIG_COUNT로 credential.helper='!gh auth git-credential'을 명령 단위로 넘긴다. macOS 키체인 -25320 실패로 사용자명 입력을 대기하는 문제를 스크립트 안에서 막았다.
- ./run.sh pages / --dry-run / --enable 추가.
- gh-pages 브랜치 푸시 완료(48bd085). 레포가 private이므로 아직 공개되지 않았다.
- --enable은 실행하지 않았다. private 레포라도 Pages 사이트는 공개되고, 페이지에 PR 제목 2,165건·레포명 25개·계정 21개·사람별 응답률이 담긴다. 그리고 private 레포 Pages는 Pro/Team 이상에서만 켜진다.

다음: 공개 여부 결정. 켜면 ./run.sh pages --enable 한 번.

### #11 · 2026-09-30 16:44 KST · `85bb907`

Pages 사이트를 켜 공개 배포했다. Free 플랜에서 private 레포의 Pages가 거부돼(422) 페이지 전용 public 레포로 분리했다.

- 라이브: https://wonjiko.github.io/2026-09-29-meissa-pr-review-dashboard-page/ (http 200, 1,028,044 바이트, 로컬 파일과 sha256 동일).
- config에 publish_repo 추가. 비어 있으면 origin, 현재는 wonjiko/2026-09-29-meissa-pr-review-dashboard-page. 그 레포는 public이고 gh-pages에 index.html과 .nojekyll 두 파일만 있다.
- 파이프라인 레포는 private 유지. 레포를 public으로 돌리는 대신 페이지 전용 레포를 쓴 이유는 스크립트·config의 대상 계정·이 문서의 턴 기록에 담긴 사람별 수치까지 공개되기 때문이다.
- publish_pages.py 버그 수정: 내용이 이전과 같으면 조기 반환해 --enable까지 건너뛰었다. 배포와 활성화를 분리하고, 대상 레포의 tip과 비교해 대상에 없으면 푸시한다.
- public 레포에 gh-pages를 푸시하면 GitHub가 사이트를 자동으로 켜서 활성화 POST가 409를 받는다. 원하는 상태이므로 성공으로 처리한다.
- 배포 전 ./run.sh offline 재생성 후 검증. 렌더 103항목, 수집 A~I 9항목 전부 통과.

다음: 수집 갱신 주기 결정. 갱신 후 ./run.sh pages로 페이지가 교체된다.

### #12 · 2026-10-02 11:44 KST · `85bb907`

현재 시점으로 전량 재수집하고, 미커밋이던 코드 변경(#9~#11)과 함께 커밋·배포했다.

- 재수집: 레포 97개 중 기간 내 PR이 있는 27곳(기존 25). PR 2,257건 + backfill 114건, 리뷰 8,583건. GraphQL 342요청.
- 범위 변화: carta-api 837->867, carta-frontend 473->505, saturn 188->190. 신규 진입 레포 2곳. 전체 변경량 1,576,334->1,687,953줄.
- 수집 검증 A~I 9항목 전부 통과. 레포별 PR 수가 search issueCount와 전량 일치.
- 렌더 검증에서 3건 실패를 발견했다. 값 오류가 아니라 Python과 JS 엔진의 반올림 자리수 불일치였다.
- 원인 1 이중 반올림: churn_mean 등 9개 필드를 Python은 round(,1), 엔진은 r2로 처리해 432.3478 -> 432.35 -> 432.4가 되어 Python의 432.3과 어긋났다. 엔진에 r1을 추가해 자리수를 맞췄다.
- 원인 2 동점 방향: 563.25는 정확히 표현되는 값이어서 Python은 half-even으로 563.2, toFixed(1)은 563.3을 냈다. pyRoundTo를 구현해 값의 정확한 십진 전개 위에서 half-even으로 반올림하고 r1~r6 전부 이 함수를 쓰게 했다.
- 자리수가 맞았으므로 검증 허용오차를 0.0002/0.05에서 1e-9로 조였다. 1자리 필드에서 0.05는 어떤 차이든 흡수해 검출력이 없었다.
- window.pyRoundTo를 노출하고 동점 10케이스를 Python 실제 출력과 대조하는 검사를 추가했다. 렌더 검증 103 -> 104항목, 실패 0.
- 커밋 범위: 미커밋이던 publish_pages.py 신설, config.json의 publish_repo, outputs/ 경로 이전, 표 내부 스크롤 제거, 범위 그룹 분리, 분모 표기까지 전부 포함.

다음: 배포된 페이지 확인 후 수집 갱신 주기 결정.
