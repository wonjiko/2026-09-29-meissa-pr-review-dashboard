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
./run.sh offline      # 네트워크 없이 raw/ 에서 DB·대시보드 재생성
./run.sh dashboard    # 집계 + 렌더만
./run.sh check        # 생성된 HTML을 실제 DOM에 올려 렌더 검증
```

산출물은 `dashboard/index.html`. `open dashboard/index.html`으로 바로 열린다.
`gh auth status`가 통과하는 상태여야 하며 `read:org`, `repo` 스코프가 필요하다.

설정은 전부 `config.json`에 있다. 수집 기간, 기본 리뷰어, 기본 조회 일수, archived 포함 여부,
페이지 크기, 봇 계정 목록을 여기서 바꾼다. `view_default_days`와 `default_reviewer`는
렌더만 다시 하면 되고(`./run.sh dashboard`), 수집 기간을 바꾸면 `./run.sh`를 다시 돌린다.

## 대시보드 구성

상단 컨트롤 바는 sticky다. 스크롤을 내려도 리뷰어 선택기와 기간 입력이 화면에 남는다.
리뷰어를 바꾸면 페이지 위쪽 절반이 그 리뷰어 기준으로 다시 그려지고, 아래쪽 절반은
조직 전체 지표라 리뷰어와 무관하다. 기간을 바꾸면 양쪽이 모두 다시 계산된다.

| 구역 | 내용 |
| --- | --- |
| 리뷰어 요약 | 요청·이행·응답률·지연·미응답·리뷰 품질·verdict 비율·변경량 비중 카드 20개 |
| 미이행 잔량 추이 | 일자별 신규 요청 / 첫 리뷰 / 일 마감 시점 잔량 |
| 첫 응답 지연 분포 | 1h~168h 버킷 히스토그램 |
| PR 크기별 | 크기 6구간별 갯수·변경량 비중, 응답률, 첫 응답 p50/p90, CHANGES 비율 |
| 상세 분포 | 레포별 / PR 작성자별 요청·리뷰·응답률·변경량 비중·PR당 변경량·p50 |
| 가장 큰 PR | 요청받은 PR 중 변경량 상위 30건. 리뷰 여부·첫 응답·verdict 포함 |
| 미응답 열린 PR | PR 링크와 대기 시간, 크기 |
| 리뷰 없이 머지된 PR | PR 링크와 요청·머지 시각, 크기 |
| 리뷰어 전체 비교 | 조회 기간에 요청이 있는 리뷰어 전원. 이름을 누르면 위쪽 상세가 전환됨 |
| 변경 규모 분포 | 조직 전체 크기 6구간. 갯수/변경량/파일 비중, 커버리지, 지연, verdict |
| 리뷰 요청 패턴 | PR당 리뷰어 수 분포, 생성→첫 요청 지연 |
| 조직 일별 볼륨 | 일자별 PR 생성·머지, 리뷰 제출 |
| 레포별 분포 | 갯수 비중, 변경량 비중, 가중 지수, 크기 분위, 지연, CHANGES 비율 |
| PR 작성자별 분포 | 갯수 비중, 변경량 비중, 가중 지수, PR 중앙·평균 크기 |

### 기간을 바꿀 수 있게 만든 방식

`data.json`은 한 기간의 집계 결과가 아니라 **사실값 자체**를 담는다. PR 2,165건,
요청쌍 6,384건, 리뷰 3,558건을 컬럼 배열로 싣고(레포·계정 문자열은 인덱스로,
시각은 epoch 초로, PR url은 규칙이 일정해 생략) 페이지가 선택한 기간으로 직접 집계한다.

`scripts/render.py`의 페이지 스크립트에 `scripts/aggregate.py`와 같은 집계 로직이 들어 있다.
두 구현이 갈라지는 것을 막기 위해 `data.json`에 `reference` 블록을 함께 싣는다.
`reference`는 **수집 범위 전체**에 대해 Python이 facts.db에서 계산한 같은 수치이고,
페이지는 이 값을 화면에 쓰지 않는다. `./run.sh check`가 페이지 엔진에 수집 범위 전체를
계산시켜 `reference`와 대조한다. 건수·합계·churn은 완전히 일치해야 하고, 양쪽이 각각
반올림하는 값(시간 백분위수, 비율)은 허용 오차 안에서 비교한다.

## 파이프라인

| 단계 | 스크립트 | 입력 | 출력 |
| --- | --- | --- | --- |
| 1 | `scripts/fetch_repos.py` | GitHub API | `raw/meta/repos.json`, `raw/meta/counts/*.json` |
| 2 | `scripts/fetch_prs.py` | `raw/meta/repos.json` | `raw/prs/<repo>/*.json` |
| 3 | `scripts/build_db.py` | `raw/` | `build/facts.db` |
| 4 | `scripts/verify.py` | `build/facts.db`, GitHub search API | `build/verification.json` |
| 5 | `scripts/aggregate.py` | `build/facts.db` | `dashboard/data.json` |
| 6 | `scripts/render.py` | `dashboard/data.json` | `dashboard/index.html` |

`scripts/ghclient.py`는 공용 모듈이다. `gh` CLI를 통해 GraphQL을 호출하고
모든 응답을 `_meta`(쿼리 종류, 파라미터, 수집 시각, rateLimit)와 함께 `raw/`에 원본 그대로 저장한다.

`raw/`는 수집 이후 수정하지 않는다. 3단계 이후는 `raw/`만 입력으로 받으므로
네트워크 없이 몇 번이든 재생성할 수 있다. 대시보드의 모든 수치는 `facts.db` 질의 결과이며
`dashboard/data.json`에 그대로 들어 있다. HTML에는 데이터가 JSON으로 임베드되고
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
  양이 상당하다(현재 8,106건 중 4,302건). 리뷰어 지표에서 전부 제외한다.
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
| 응답률 | 요청받은 PR 중 해당 리뷰어의 리뷰가 하나라도 있는 비율 |
| 첫 응답 지연 | 첫 요청 시각 → 요청 이후 첫 리뷰 제출 시각. p50 / p90 |
| 미응답·열린 PR | 리뷰 없이 아직 OPEN인 PR |
| 미응답 머지 | 요청받았으나 리뷰 없이 머지된 PR |
| 내용 있는 리뷰 비율 | 본문 또는 인라인 코멘트가 있는 리뷰의 비율 |
| 요청 외 리뷰 | 요청 이벤트 없이 리뷰를 남긴 PR |
| 주별 잔량 | 각 주 종료 시점에 요청됐고 리뷰·철회·PR 종료가 모두 없는 쌍의 수 |
| CHANGES 비율 | `CHANGES_REQUESTED` ÷ (`APPROVED` + `CHANGES_REQUESTED`). `COMMENTED`·`DISMISSED`는 분모에서 제외 |

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
| 변경량 응답률 | 리뷰한 PR의 churn 합 ÷ 요청받은 PR의 churn 합 |
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

`scripts/verify.py`가 `build/verification.json`을 만들고 하드 실패가 있으면 종료 코드 1을 반환한다.

- A: 레포별 기간 내 PR 수 == search `issueCount`
- B: 레포별 backfill PR 수 == 해당 search `issueCount`
- C: `hasNextPage`를 보고한 모든 체인의 후속 페이지가 디스크에 있음
- D: `window_source`가 `created_at`과 일치
- E: PR 테이블에 없는 PR을 가리키는 리뷰·요청 이벤트가 없음
- F: 대상 리뷰어의 리뷰 PR 수가 독립 search 쿼리와 2% 이내 (경고)
- G: `timelineItems.totalCount` 불일치 표본 기록 (정보)
- H: `additions` / `deletions` / `changedFiles`를 `raw/` 원본에서 다시 계산해 DB와 대조
- I: 결측 변경량이 0이 아니라 NULL로 남아 있는지 기록 (정보)

`./run.sh check`는 `scripts/check_render.mjs`를 jsdom에 올려 렌더 결과를 검사한다.
세 부류를 본다.

1. 그려졌는지 — 스크립트 오류, 빈 표·빈 차트, 화면 수치와 엔진 계산값의 불일치.
2. 컨트롤이 동작하는지 — 컨트롤 바가 sticky인지, 기본 조회 기간이 최근 90일인지,
   프리셋과 직접 입력이 재집계를 일으키는지, 수집 범위 밖 날짜가 잘리고 경고가 뜨는지,
   짧은 기간이 더 적은 PR을 담는지, 리뷰어 전환이 위쪽 절반을 다시 그리는지.
3. 페이지 엔진이 Python과 같은 답을 내는지 — `reference`와 전면 대조. 리뷰어별 건수·합계,
   크기 구간, 레포, 작성자, 요청 패턴, 리뷰어 상세까지 항목별로 비교한다.
   건수·합계·churn은 완전 일치, 반올림 값은 비율 0.0002 / 시간 0.05 오차 안에서 비교한다.
   비중 합 100%, 일별 시계열 합계 일치 같은 내부 정합성도 함께 본다.

현재 82항목이다. 첫 실행 시 `build/domcheck/`에 jsdom을 설치한다. `build/`는 git 추적 대상이 아니다.

## git

`raw/`, `build/`, `dashboard/data.json`, `dashboard/index.html`은 추적하지 않는다.
전부 스크립트로 재생성되고, `raw/`만 12MB 남짓이다. 클론한 쪽은 `gh auth`를 맞춘 뒤
`./run.sh`를 돌리면 같은 산출물을 얻는다.

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
