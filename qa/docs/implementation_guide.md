# 구현 가이드 · 어디에 무엇을 어떻게

기능을 새로 만들거나 추가할 때 보는 문서예요. 규칙은 [`../AGENTS.md`](../AGENTS.md), 화면은 [`ui.md`](ui.md), 시스템 데이터 형식은 [`contracts.md`](contracts.md)를 봐요.

- 같은 내용은 한 곳에만 써요. 이 문서는 **위치와 순서**를, 코드 안 첫 줄은 **그 파일의 역할**을 맡아요.
- 폴더 · 파일을 옮기거나 이름을 바꾸면 이 문서 2장과 5장을 같이 고쳐요.

---

## 1. 한눈에 보기

```text
dashboard · command_line          화면 · 터미널 명령
        ↓
test_runs                         실행 관리 (한 번에 하나 · 진행 상황)
        ↓
test_suites                       시험 묶음
        ↓
scoring · answer_key · reports    점수 계산 · 정답표 · 보고서
        ↓
domain                            용어 · 합격 기준 (아무것도 import 하지 않음)

system_targets   ← test_suites가 Protocol로만 사용 · fake / live 구현이 여기에
qa_database      ← answer_key · test_runs만 사용
```

- 화살표는 **위가 아래를 가져다 쓰는 방향**이에요. 아래에서 위로 import 하지 않아요.
- 시험 코드(`test_suites`)는 시스템이 가짜인지 실제인지 몰라요. `system_targets/target_interfaces.py`의 Protocol만 봐요.

## 2. 폴더별 책임

```text
qa/
├─ pyproject.toml · .env.example · Dockerfile
├─ src/ticket_guard_qa/
│  ├─ settings.py · command_line.py
│  ├─ domain/             enums · models · pass_criteria · detection_targets · raw_event_routing
│  ├─ system_targets/     target_interfaces · fake_system · live_django_system · live_mongo_reader · target_factory
│  │                      live_kafka_reader · live_raw_mongo_reader
│  ├─ answer_key/         expected_verdicts · answer_key_repository
│  ├─ macro_bots/         bot_catalog · bot_profiles · behavior_fields · bot_profile_store
│  │                      behavior_sampling · bot_trial_run · rule_hit_preview
│  ├─ test_suites/        suite_interface · suite_registry · self_check · event_contract · verdict_accuracy
│  │                      event_delivery · raw_ingest · pipeline_latency · seat_concurrency · load_capacity · failure_recovery
│  ├─ scoring/            latency_metrics · detection_metrics · confusion_matrix · detection_breakdown
│  ├─ test_runs/          run_service · run_repository · run_progress_stream
│  ├─ qa_database/        database (MongoDB 연결 · 컬렉션 이름) · archive_export
│  ├─ reports/            json_report · html_report
│  └─ dashboard/          dashboard_app · dependencies · screen_format · routes/ · templates/(layout · screen_parts · screen_*) · static/css/(theme_tokens · screen_layout)
├─ traffic_generators/    virtual_user_traffic (VU 동시 실행 · 브라우저 유형 구분 · 캡처 저장) · locust_traffic
├─ case_data/             exception_codes/ · event_contracts/
└─ tests/                 unit_tests/ · boundary_tests/

.github/workflows/qa.yml  (qa/ 밖 · AGENTS.md 4장 예외)
```

| 폴더 | 하는 일 | 넣으면 안 되는 것 |
|---|---|---|
| `domain/` | 용어(enum) · 데이터 모양 · 합격 기준 7개 | 다른 폴더 import · DB · HTTP |
| `system_targets/` | 시스템과 연결하는 유일한 곳 · Protocol과 fake / live 구현 | 정답표 · 점수 계산 · 시스템 코드 import |
| `answer_key/` | 정답표 만들기 · QA DB에 저장 | 시스템 쪽으로 내보내는 코드 |
| `macro_bots/` | 봇 종류 소개 · 행동 값 · 버전 저장(QA DB) · 행동 값 → 대기 시간 식 · 모의 판정 · 룰 매칭 예측 | 실제 트래픽 보내기(→ `traffic_generators`) · 시스템 쪽으로 봇 설정 내보내기 |
| `test_suites/` | 시험 묶음 하나 = 파일 하나 · 입력 → 결과 수집 → 점수 → 판정 | 화면 코드 · 직접 HTTP 호출 |
| `scoring/` | p95 · 오류율 · 탐지율 · 오탐률 · 정답 × 판정 표 | 입출력(DB · HTTP · 파일) |
| `test_runs/` | 실행 시작 · 중지 · 동시 실행 잠금 · 진행 상황 전달 | 시험 내용 |
| `qa_database/` | QA DB 연결 · 테이블 정의 | 시스템 DB 연결 |
| `reports/` | 실행 결과를 JSON · HTML로 | 점수 다시 계산 |
| `dashboard/` | 화면 · 주소 · 관리자 확인 | 점수 계산 · 시험 로직 (→ `test_runs`를 호출만) |
| `traffic_generators/` | 사람 · 봇 트래픽 보내기 (Locust · Playwright) | 정답표 저장 (→ `answer_key`) |
| `case_data/` | 시험에 쓰는 데이터 (E · T 코드 사례 · 계약 시험 JSON) | 정답표 · 봇 설정 |
| `tests/` | QA 프로그램 자체를 검사하는 pytest | 시스템을 시험하는 코드 (→ `test_suites`) |

## 3. 실행 한 번의 흐름

02 화면에서 **시험 시작**을 누른 뒤 04 결과가 나올 때까지 거치는 파일이에요.

| 순서 | 파일 | 하는 일 |
|---|---|---|
| 1 | `dashboard/routes/test_run_routes.py` | 입력 확인 → `RunConfig` 만들기 |
| 2 | `test_runs/run_service.py` | 다른 실행 중인지 확인 · 실행 번호 발급 · 03 화면으로 이동 |
| 3 | `system_targets/target_factory.py` | 설정 보고 fake / live 대상 고르기 |
| 4 | `answer_key/expected_verdicts.py` | 트래픽 구성으로 정답표 만들기 → `answer_key_repository.py`로 저장 |
| 5 | `test_suites/suite_registry.py` | 고른 시험 묶음 찾기 · 묶음 모양은 `suite_interface.py` |
| 6 | `test_suites/verdict_accuracy.py` 등 | 트래픽 보내기(`traffic_generators`) → 시스템 결과 읽기(`system_targets`) |
| 7 | `scoring/detection_metrics.py` 등 | 정답표와 비교해 숫자 계산 |
| 8 | `domain/pass_criteria.py` | 숫자를 합격 기준에 대 보기 |
| 9 | `test_runs/run_repository.py` · `qa_database/database.py` | 결과 저장 (`runs` 문서 하나 = Run 하나 · Suite 결과 포함) |
| 10 | `reports/html_report.py` · `json_report.py` | 보고서 만들기 |
| 11 | `test_runs/run_progress_stream.py` | 단계마다 03 화면에 진행 보내기 · 끝나면 04로 |
| 12 | `dashboard/templates/screen_04_test_result.html` | 결과 보여 주기 |

터미널에서 돌릴 때는 1번 대신 `command_line.py`가 `RunConfig`를 만들고 2번부터 같아요. 11 · 12번 대신 종료 코드(0 통과 · 1 실패 · 2 오류)를 돌려줘요.

## 4. 이렇게 추가해요

### 새 시험 묶음
1. `case_data/exception_codes/`에 관련 E · T 코드 사례가 있는지 확인하고, 없으면 먼저 추가해요.
2. `test_suites/<무엇을_확인하는지>.py`를 만들어요. (예: `queue_limit.py`)
3. `test_suites/suite_registry.py`에 등록해요.
4. 필요한 시스템 기능이 Protocol에 없으면 `system_targets/target_interfaces.py`에 추가하고, `fake_system.py`부터 구현해요.
5. `tests/unit_tests/`에 가짜 대상으로 통과 · 실패 둘 다 확인하는 테스트를 넣어요.
6. 이 문서 5장 표에 한 줄 추가해요.

### 새 사례
1. `case_data/exception_codes/E??_<내용>.yaml` 또는 `case_data/event_contracts/<내용>.json`을 만들어요.
2. 파일 안에 입력 · 기대 결과 · 근거(기획서 쪽수 · E 코드)를 적어요.
3. 05 화면의 "QA 사례로 저장"으로 만든 사례도 같은 형식이에요.

### 새 화면
1. [`ui.md`](ui.md)에 화면 명세와 번호를 먼저 적어요. (시안이 필요하면 PNG 시안부터)
2. `dashboard/templates/screen_<번호>_<이름>.html`을 만들어요. 색은 `static/css/theme_tokens.css` 변수만 써요.
3. `dashboard/routes/`에서 알맞은 파일에 주소를 추가해요. 계산은 하지 않고 `test_runs` · `answer_key` 등을 호출만 해요.
4. [`ui.md`](ui.md) 5장 주소 표를 고쳐요. 화면 문구는 3장 문구 규칙을 따라요.

### 새 시험 대상 (예: MongoDB 연결)
1. [`contracts.md`](contracts.md)에 형식이 있는지 확인해요. 없으면 db 팀에 Issue로 요청해요.
2. `system_targets/live_<대상>.py`에 Protocol을 구현해요. 읽기 전용 계정만 써요.
3. `system_targets/target_factory.py`에서 설정으로 고를 수 있게 해요.
4. `.env.example`에 설정 이름을 추가해요. (값은 넣지 않아요)
5. AGENTS.md 5장 시험 대상 현황과 이 문서 5장을 고쳐요.

### 새 봇
봇 추가는 두 가지예요. 기존 행동 값의 새 조합이면 화면, 새 행동 방식이면 코드예요.

**화면에서 추가 (B5 · 코드 수정 없음)** · 행동 값(`SessionBehavior`) 조합으로 만들 수 있는 봇
1. B1 "새 봇 추가" → ① 시작 봇 복사 → ② 이름 · 한 줄 정의 · 공격 수법 분류 → ③ 예매 중 행동 → ④ 탐지 흔적 · 합격 기준 묶음 → ⑤ 모의 판정 · 저장
2. 저장 위치: QA DB `bot_types` (이름 · 분류 · 상태 · 탐지 흔적 · 합격 기준 · v1 행동 값) · 이후 행동 값은 B2 버전(`bot_versions`)
3. 상태: 작성 중(Run 제외) → 검증 중(Run 포함) → 사용 중 · B1 상세에서 전환
4. 유형 id `BOT_E` · `BOT_F` … 자동 · 색은 `bot_catalog.CUSTOM_BOT_COLORS` 순서 · 구분은 아이콘 + 알파벳 코드
5. 따라오는 곳: 02 트래픽 구성 칸 · 정답표 · 합격 기준 합산(`detection_target_id`) · B1 분류 타일 · B3 · B4 · 실행 트래픽

**코드로 추가** · 새 행동 방식(대기열 우회 · 보안문자 판독 등)이 필요한 봇 · 빠뜨리면 `tests/unit_tests/test_macro_bots.py`가 실패해요.
1. `domain/enums.py`의 `ActorType` 상수 · `BUILT_IN_ACTOR_TYPES`에 추가해요.
2. `macro_bots/bot_catalog.py`의 `BUILT_IN_BOT_TYPES`에 한 줄(이름 · 한 줄 정의 · 역할 · 아이콘 · 탐지 흔적 · 분류 · 합격 기준 묶음 · 색 변수)을 추가해요. 새 분류는 `BOT_CATEGORIES`에 한 줄이에요. 색은 `theme_tokens.css`와 [`ui.md`](ui.md) 2장에 함께 추가해요.
3. `macro_bots/bot_profiles.py`의 `DEFAULT_BEHAVIOR_BY_ACTOR_TYPE`에 시작 행동 값을 추가해요.
4. 새 합격 기준이 필요하면 `domain/pass_criteria.py`에 기준, `domain/detection_targets.py`에 묶음 한 줄을 추가해요. 소속은 봇마다 `detection_target_id`로 정해요.
5. 새 행동 방식은 `SessionBehavior` 필드(아래 "새 행동 값") + `system_targets/live_booking_client.py` 실행 단계로 넣어요. 브라우저가 필요하면 `traffic_generators/bot_c_browser.py` 방식이에요.

### 새 행동 값 (예: ③ 화면 흐름)
1. `domain/models.py`의 `SessionBehavior`에 필드를 추가해요.
2. `macro_bots/behavior_fields.py`의 `BEHAVIOR_FIELD_SPECS`에 입력 칸 한 줄을 추가해요. B1 · B2 화면은 이 목록을 그대로 그려요.
3. `DEFAULT_BEHAVIOR_BY_ACTOR_TYPE`에 종류별 시작값을 넣어요. 예전에 저장한 버전은 새 필드를 기본값으로 읽어요.
4. `PENDING_BEHAVIOR_GROUPS`에서 그 항목을 지워요.

### 판정 규칙이 정해지면 (R1 ~ R6)
- B2 예상: `macro_bots/rule_hit_preview.py`의 `RULE_CHECKS`에 규칙마다 조건 한 줄을 넣어요.
- B4 "어떤 규칙이 잡았나": `verdict_accuracy`가 결과 `details["rule_hit_count_by_rule_id"]`를 채우면 화면이 바로 표를 그려요.

## 5. 구현 현황

이 표 **한 곳에서만** 관리해요. 상태: **동작**(실제로 돌아감) · **껍데기**(Protocol · 함수 이름까지 있고 `NotImplementedError`) · **미착수**.

| 기능 | 위치 | 상태 | 막힌 이유 | 다음 단계 |
|---|---|---|---|---|
| 설정 · 용어 · 합격 기준 | `settings.py` · `domain/` | 동작 | | |
| 가짜 대상 · 일부러 틀리는 대상 | `system_targets/fake_system.py` | 동작 | | |
| 점수 계산 | `scoring/` | 동작 | | |
| 정답표 계획 · 저장 | `answer_key/` | 동작 | | 트래픽 후 세션 키 연결 |
| QA 자기 검사 | `test_suites/self_check.py` | 동작 | | |
| 이벤트 계약 시험 | `test_suites/event_contract.py` · `live_django_system.py` · `live_kafka_injector.py` | 동작 (브라우저 이벤트 Mock + Live 2026-11-05 PASS · 예매 확정 오래된 순번 거부(E20) Mock + Live 연결 · 토픽 주입 → 정제 · 격리 저장 대조 Mock) | 토픽 주입 Live: 시험 환경 주입 허용(`IS_KAFKA_CONTRACT_INJECTION_ENABLED`) · 시스템 MongoDB 읽기 계정 · 격리 사유 필드 확정 | Live Run |
| Live 예매 흐름 (1-b ~ 1-d) | `system_targets/live_booking_client.py` · `live_django_system.py` · `traffic_generators/virtual_user_traffic.py` · `test_suites/booking_flow.py` | 동작 (Run 설정 "예매 흐름 테스트" · VU 동시 실행 · 오픈 전 로그인 → 오픈 전 공연 목록 · 상세 조회(행동 값 ③ · 화면마다 체류 시간 · 브라우저 흔적이면 page_enter · page_exit + 브라우저 User-Agent) → 오픈 + 예매 시작 지연(기기 1대당 예매 창 2개 이상 = 같은 기기 VU끼리 같은 순간 · 첫 창이 받은 기기 쿠키 `tg_capture`를 나머지 창이 공유 · `traffic_generators/virtual_user_traffic.assign_devices` · 결과에 `device_key`) → 대기열 → 보안문자 → 좌석 클릭(봇 프로필 간격 · seat_select 이벤트) → 확정 · 먼저 팔린 좌석은 다른 좌석으로 행동 값 ⑤ 횟수 · 대기만큼 재시도 · 확정 못 한 계정은 예매 취소로 반환 · 시험 시간 넘으면 TIMEOUT · 예매 완료 · 매진 · 중복 판매 · 단계별 p95) · 시스템 테스트 훅 필요 (Issue #6) | 초기화: QA 대시보드에 시스템 관리자 계정 미전달(compose.gateway.yml) → 건너뜀 · 브라우저 telemetry(/api/capture/) 미재현 · 기기 쿠키는 시스템 `DJANGO_DEBUG=1`(http)에서만 공유(운영 설정은 Secure 쿠키) · 접속 IP는 모든 VU가 같은 컨테이너 주소 · Run 중지는 Suite 사이에서만 | 관리자 계정 전달 (develop PR) · 부하 테스트 Locust |
| Live 예상 소요 · Suite별 최대 시간 | `test_runs/run_estimate.py` · `run_service.estimate_run` · `run_repository.list_recent_suite_durations` · `dashboard/routes/test_run_routes.estimate_test_run` | 동작 (Suite마다 실제 소요 `SuiteResult.duration_sec` 기록 → 최근 Live Run 5개 중앙값 · 트래픽 Suite는 VU 비율 환산 · 실측 없으면 계산 = 오픈 전 준비 + max(대기열 처리, 브라우저 차례 대기) · 트래픽 Suite 최대 시간 자동 = 예상 × 2 (120 ~ 900초) · `RunConfig.duration_sec` 0 = 자동 · 03 경과 기준 = 예상 합계 · Mock = 시뮬레이션 시간 고정) | 계산 초기값(1명 예매 6초 · 브라우저 1세션 35초 · 동시 입장 25명)은 실측 전 추정 · 첫 Live Run 뒤부터 실측 | - |
| Live 브라우저 예매 흐름 (봇 C · 봇 D 등) | `system_targets/live_browser_client.py` · `live_django_system.run_browser_session` · `traffic_generators/virtual_user_traffic.build_planned_user_session_plans` · `macro_bots/browser_capture.save_browser_capture_frames` | 코드 · 시험 동작 (브라우저 트래픽 유형 VU = 실제 화면 · 로그인 → 오픈 전 공연 상세 → 예매하기 클릭 → 대기열 → 보안문자 입력 → 좌석 클릭(행동 값 간격) → 확정 · 먼저 팔린 좌석은 다른 좌석 재시도 · 단계별 PNG 캡처 → B3 · 클릭은 마우스 이동 궤적 없이 · 동시 브라우저 4개 · 창 16개 · 화면 요소는 파일 위 상수 한 곳 · 봇 D 등 기기 1대당 예매 창 2개 이상 = 기기 1대당 브라우저 1개(`live_django_system.use_browser`) · 계정마다 쿠키 분리 창 (탭은 로그인 쿠키를 같이 써서 계정 여러 개 불가) · 첫 창이 받은 기기 쿠키 `tg_capture`를 나머지 창에 넣음 · 브라우저 정보 · 화면 크기 같음 · 마지막 창이 끝나면 브라우저 종료 · 브라우저 흔적 없음(⑥ = 0) = 기본 User-Agent + 화면 이벤트 전송(`/api/events/` · `/api/capture/`) 차단 · B3 캡처 = 목록 순서상 첫 브라우저 트래픽 유형) | 실제 Chromium 확인 완료(로컬 Chrome · 예매 화면 흉내 사이트 · 로그인 → 확정 · 팔린 좌석 건너뜀 · 캡처 5장) · qa-dashboard 컨테이너 안 실제 예매 웹(`http://web:8000`) 확인: 봇 C 1명 · 봇 D 창 3개 로그인 → 대기열 → 보안문자 → 좌석 화면 통과 (좌석 전부 판매 상태 · 초기화 미설정이라 확정 미확인) · `http://web:8000` = 보안 컨텍스트 아님 → 예매 화면 `crypto.randomUUID` 없음 → Chromium에 시험 대상 주소를 HTTPS처럼 취급하는 옵션(`build_trusted_origin`) · 보안문자 정답은 이미지 요청 때 생성 → 이미지 로드 뒤 입력 · 화면 스크립트 미동작 = 세션 오류 `browser login · BROWSER_SCRIPT_NOT_RUNNING` · Chromium 위치 = `TICKET_GUARD_QA_BROWSER_EXECUTABLE_PATH`(qa-dashboard 이미지 `/usr/bin/chromium` · 내 PC는 설치된 Chrome 경로 또는 `playwright install chromium`) · 없으면 세션 오류 `browser · 실행 환경 없음` | qa-dashboard 이미지 다시 빌드(Debian `chromium` · `fonts-noto-cjk` · `.[dashboard,browser]`) → 실제 예매 웹 Run |
| 이벤트 전달 검증 (2단계) | `system_targets/live_kafka_reader.py` · `test_suites/event_delivery.py` · Mock `FakeEventStreamReader` | 동작 (Run 설정 "이벤트 전달 검증" · Run 직전 토픽 끝 위치 기록 → VU 트래픽 → QA 전용 소비자 그룹으로 읽기(commit 없음) → 좌석 클릭 · 서버 이벤트 완전성 · 중복 · 형식 · 파티션 키 · 전달 지연 p95 · 관측 이벤트 수) · `docs/contracts.md` 4-1 | 전달 지연 기준선 미정 | |
| 원본 적재 검증 (2-b) | `system_targets/live_raw_mongo_reader.py` · `test_suites/raw_ingest.py` · `domain/raw_event_routing.py` · Mock `FakeRawEventReader` | Mock 동작 (Run 설정 "원본 적재 검증" · 이벤트 전달 검증과 같은 트래픽 · 토픽 읽기 → QA 메시지 위치(파티션 · 오프셋)로 원본 DB 9개 컬렉션 조회 · 최대 30초 적재 대기 → 적재 누락 · 중복 적재 · 오분류 · 미분류 · 원문 변형 · 적재 지연 p95) · `docs/contracts.md` 4-2 | Live 미실행: 원본 DB 읽기 전용 계정 · qa-dashboard ↔ `raw-backend` 네트워크 없음 · 적재 지연 기준선 미정 | Live 연결 (db팀 계정 · 네트워크) |
| QA 데이터 넘기기 | `qa_database/archive_export.py` · `command_line.py` (`export-archive`) · `archive_exports` 테이블 | 동작 (요청 · QA 담당 승인 시 · 끝난 Run만 · 기본 결과 숫자 + 적발 목록 · 정답표 · 봇 설정은 `--collection` 직접 지정 · 컬렉션별 JSON + manifest → 받는 쪽 `ticketguard_qa_archive` · 시스템 DB에는 쓰지 않음 · 필드 추가 = `*_FIELDS` 한 줄 · 정답표 · 봇 설정을 넘긴 봇 버전으로 Run 시작 시 03 경고) | 대시보드 버튼 없음(의도) · 받는 쪽 가져오기는 수동(`mongoimport`) | |
| QA DB MongoDB | `compose.qa-db.yml` · `compose.qa-db.local.yml` · `compose.qa-db.init.js` · `qa_database/database.py` | 동작 (QA 전용 인스턴스 `qa-mongo` · 팀 compose에 덧붙여 실행 · `qa-backend` 네트워크 = qa-dashboard · qa-mongo만 · QA 계정 = `ticketguard_qa` 읽기 · 쓰기만 · 컬렉션 `runs` · `answer_keys` · `bot_versions` · `bot_types` · `archive_exports` · 컨테이너 안 27017 · 내 PC 27021은 local 파일로만 · 단위 테스트는 `mongomock://` 메모리 DB) | 백업 미구성 | 서버 배포 시 백업 (`mongodump`) |
| 터미널 명령 · 종료 코드 | `command_line.py` | 동작 | | |
| QA DB · 실행 관리 | `qa_database/` · `test_runs/` | 동작 | | 스키마 바뀌면 Alembic |
| 보고서 | `reports/` | 동작 | | |
| 화면 01 ~ 04 | `dashboard/` | 동작 (시안 기준 · 가짜 대상 숫자) | 실제 대상 실시간 수치 없음 | 결과 알림 보내기 |
| 화면 05 | `dashboard/` | 껍데기 | 시스템 DB 없음 | |
| 화면 B1 ~ B4 · 매크로 봇 | `dashboard/` · `macro_bots/` | 동작 (가짜 대상 · 탐지율 · 버전 저장 · 모의 판정 · 실시간 진행) · 문구는 ui.md 3장 문구 규칙 | 규칙별 결과 · 좌석 선택 · 확정 단계 | 판정 규칙 · 트래픽 생성기 연결 |
| 관리자 확인 (A안) | `dashboard/dependencies.py` | 동작 (팀 입구가 붙인 `X-Admin-User`만) | | |
| 판정 정확도 | `test_suites/verdict_accuracy.py` | 가짜만 동작 (행동 값으로 가짜 판정 · 정답표 저장 · 탐지율 · 오탐률) | 실제 대상: 시스템 판정 없음 · 저장 위치 미정 | |
| Gold 반영 시간 | `test_suites/pipeline_latency.py` · `live_mongo_reader.py` | 가짜만 동작 | Kafka · Spark · MongoDB 없음 | 시험 이벤트 먼저 보내기 |
| 03 실시간 수치 | `test_runs/run_service.py` · `LiveMetricsReader` | 가짜: `fake_run_duration_sec` 동안 수치 · 실제: 경과 시간 / 시험 시간 표시 · 트래픽이 먼저 끝나면 04로 | 실제 대상: 판정 지연 · EPS · Gold 수치 없음 (MongoDB 연결 전) | |
| 좌석 동시성 (E12 · E20) | `test_suites/seat_concurrency.py` · `BookingApi.prepare_seat_contender` · `send_confirms` · Mock 재고 · `is_seat_lock_broken` | 동작 (Run 설정 "좌석 동시성" · VU를 좌석 선택 단계까지 준비 → 확정 동시 전송 · 같은 지정석 2석 VU 20명 → 예매 1건 · 자유석 잔여 수량보다 많은 4석 요청 → 판매 합계 ≤ 잔여 · 잔여 수량 일치 · 같은 확정 동시 2회 → 예매 번호 1개 · 재고는 선택 단계 응답(sold · remaining) 기준 · 끝난 계정은 다음 시나리오에서 재사용) | 좌석 점유 5분(E16) 측정 불가 · 초기화 없으면 자유석 잔여 0 → 측정 불가 | 관리자 계정 전달 (develop PR) · Redis 결정 후 E16 |
| 부하 (T1 · T2 · E08) | `test_suites/load_capacity.py` · `BookingApi.hold_admitted_session` · `send_request_burst` · Mock 대기열 상한 · 요청 속도 제한 | Mock 동작 (VU 동시 진입 → 입장 구간 겹침 = 최대 동시 입장 · 연속 요청 429 · 사람 속도 요청 허용 · 서버 오류 0 · 상한 붕괴 · 속도 제한 없음 결함 Mock = FAIL) · Live 연결 코드 (시험 계정 · 대기열 입장 시각 · 공연 목록 연속 요청) | Live 미실행 · 시스템 상한 · 속도 제한 미구현 | Live Run |
| 장애 복구 (RTO) | `test_suites/failure_recovery.py` · `ProcessControl` · `PipelineReader.find_processed_event_ids` · Mock 저장 작업 중지 · 재시작 | Mock 동작 (중지 전 이벤트 저장 확인 → 중지 → 이벤트 전송 → 재시작 → 전부 저장까지 시간 · 누락 · 중복 0 · 유실 · checkpoint 결함 Mock = FAIL) · Live 연결 코드 (Docker 소켓 컨테이너 중지 · 시작 · `clean_events` · `quarantine_events` eventId 조회) | Live: 컨테이너 이름 · Docker 소켓 · 시스템 MongoDB 읽기 계정 | Live Run |
| 봇 설정 저장 · 규칙 미리 보기 | `macro_bots/` · `domain/rule_sets.py` | 동작 · 룰셋 `mock-1`(가짜 판정과 같은 규칙 4개) · B2 · B4 일치 | 실제 판정 규칙 R1 ~ R6 | `RULE_SETS`에 버전 추가 · `TICKET_GUARD_QA_RULE_SET_VERSION` |
| 테스트 케이스 · Ground Truth 탭 | `dashboard/routes/test_case_routes.py` · `screen_c1_test_cases.html` · `test_suites/exception_cases.py` · `case_data/exception_codes/` | 동작 (E01 ~ E22 · T1 · T2 사례 24건 · 시스템 오류 코드 · 검증 Suite = 각 Suite `related_codes` · 이벤트 계약 사례 목록 · Run별 정답표 조회) | Suite 미연결 예외 코드 16건 | 예외 흐름 Suite |
| 봇 C 화면 캡처 (B3) | `macro_bots/browser_capture.py` | Mock 동작 (봇 C 행동 값 → 단계별 프레임 · 클릭 위치) · Live 연결 코드 (`captures/{run_id}/frames.json` + 이미지 읽기) | 브라우저 자동화 실행 환경 | 브라우저 봇이 `save_capture_frames` 호출 |
| db 스키마 대응 (0단계) | `docs/contracts.md` 3 · 5장 · `case_data/event_contracts/` · `domain/models.py` 레코드 · `fake_system.py` | 동작 (Mock이 SESSION_VERDICTS · SESSION_FEATURES · QUARANTINE_EVENTS 모양 반환 · B4 룰별 Hit 수) | db 스키마 확정 · QA 읽기 전용 계정 | `live_mongo_reader.py` 구현 · `expected_storage` 대조 |
| 경계 검사 · CI | `tests/boundary_tests/` · `.github/workflows/qa.yml` | 동작 (로컬) · CI는 push 후 확인 | | |

## 6. 코드 안 표시 규칙

**폴더 첫 줄** (`__init__.py`): 하는 일 · 금지

```python
"""시험 대상 연결 · 시험 코드는 target_interfaces의 Protocol만 사용 · 시스템 코드 import 금지"""
```

**파일 첫 줄**: 역할 · 근거

```python
"""판정 정확도 시험 · 기획서 21쪽 · 탐지 = CHALLENGE 이상"""
```

**아직 못 만든 곳**: `TODO(언제): 무엇` + 이유를 담은 `NotImplementedError`

```python
def read_system_verdicts(run_id: str) -> list[SessionVerdict]:
    # TODO(MongoDB 연결 후): 판정 결과 컬렉션에서 읽기 · AGENTS.md 11장
    raise NotImplementedError("판정 저장 위치 미정")
```

- `NotImplementedError`를 만난 시험 묶음은 **실패가 아니라 "건너뜀"**으로 기록하고, 메시지를 이유로 보여 줘요.
- 남은 일은 `TODO(` 검색 한 번으로 모두 찾을 수 있어야 해요. 다른 형식(`FIXME`, `XXX`)은 쓰지 않아요.
