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
│  ├─ domain/             enums · models · pass_criteria · detection_targets
│  ├─ system_targets/     target_interfaces · fake_system · live_django_system · live_mongo_reader · target_factory
│  ├─ answer_key/         expected_verdicts · answer_key_repository
│  ├─ macro_bots/         bot_catalog · bot_profiles · behavior_fields · bot_profile_store
│  │                      behavior_sampling · bot_trial_run · rule_hit_preview
│  ├─ test_suites/        suite_interface · suite_registry · self_check · event_contract · verdict_accuracy
│  │                      pipeline_latency · seat_concurrency · load_capacity · failure_recovery
│  ├─ scoring/            latency_metrics · detection_metrics · confusion_matrix · detection_breakdown
│  ├─ test_runs/          run_service · run_repository · run_progress_stream
│  ├─ qa_database/        database · tables
│  ├─ reports/            json_report · html_report
│  └─ dashboard/          dashboard_app · dependencies · screen_format · routes/ · templates/(layout · screen_parts · screen_*) · static/css/(theme_tokens · screen_layout)
├─ traffic_generators/    locust_traffic · user_behaviors · bot_c_browser
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
| 9 | `test_runs/run_repository.py` · `qa_database/tables.py` | 결과 저장 |
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
빠뜨리면 `tests/unit_tests/test_macro_bots.py`가 실패해요.
1. `domain/enums.py`의 `ActorType`에 이름을 추가해요.
2. `macro_bots/bot_catalog.py`에 소개 한 줄(이름 · 설명 · 트래픽 종류 · 색 변수)을 추가해요. 색은 `theme_tokens.css`와 [`ui.md`](ui.md) 2장에 함께 추가해요.
3. `macro_bots/bot_profiles.py`의 `DEFAULT_BEHAVIOR_BY_ACTOR_TYPE`에 시작 행동 값을 추가해요. 이후 값은 B2 화면에서 버전으로 바꿔요.
4. 목표가 있으면 `domain/pass_criteria.py`에 기준, `domain/detection_targets.py`에 묶음 한 줄을 추가해요. B1 · B4 · 점수 계산이 같이 따라와요.
5. 트래픽 구성에 넣으려면 `domain/models.py`의 `TrafficMix`와 02 화면 입력 칸을 고쳐요.
6. 브라우저가 필요하면 `traffic_generators/bot_c_browser.py` 방식으로 따로 만들어요. 대기 시간 식은 `macro_bots/behavior_sampling.py`를 써요.

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
| 이벤트 계약 시험 | `test_suites/event_contract.py` · `live_django_system.py` | 동작 (Mock + Live 2026-11-05 PASS · 요청 22건) | 예매 확정 사례 1건 · 저장 값 확인 | `/api/action/` 사례 · MongoDB 연결 후 저장 확인 |
| Live 예매 흐름 (1-b · 1-d) | `system_targets/live_booking_client.py` · `live_django_system.py` · `test_suites/booking_flow.py` | 동작 (Run 설정 "예매 흐름 테스트" · 시험 계정 로그인 → 대기열 → 보안문자 → 좌석 선택 단계 · VU마다 다음 계정 · 끝나면 예매 취소로 계정 반환 · 단계별 p95) · 시스템 테스트 훅 필요 (Issue #6) | VU 한 명씩 차례로 · 좌석 클릭 · 확정 · 행동 값 미적용 | 1-c 트래픽 생성기 (동시 실행 · 봇 프로필) |
| 터미널 명령 · 종료 코드 | `command_line.py` | 동작 | | |
| QA DB · 실행 관리 | `qa_database/` · `test_runs/` | 동작 | | 스키마 바뀌면 Alembic |
| 보고서 | `reports/` | 동작 | | |
| 화면 01 ~ 04 | `dashboard/` | 동작 (시안 기준 · 가짜 대상 숫자) | 실제 대상 실시간 수치 없음 | 결과 알림 보내기 |
| 화면 05 | `dashboard/` | 껍데기 | 시스템 DB 없음 | |
| 화면 B1 ~ B4 · 매크로 봇 | `dashboard/` · `macro_bots/` | 동작 (가짜 대상 · 탐지율 · 버전 저장 · 모의 판정 · 실시간 진행) · 문구는 ui.md 3장 문구 규칙 | 규칙별 결과 · 좌석 선택 · 확정 단계 · 봇 C 캡처 없음 | 판정 규칙 · 트래픽 생성기 연결 |
| 관리자 확인 (A안) | `dashboard/dependencies.py` | 동작 (팀 입구가 붙인 `X-Admin-User`만) | | |
| 판정 정확도 | `test_suites/verdict_accuracy.py` | 가짜만 동작 (행동 값으로 가짜 판정 · 정답표 저장 · 탐지율 · 오탐률) | 실제 대상: 시스템 판정 없음 · 저장 위치 미정 | |
| Gold 반영 시간 | `test_suites/pipeline_latency.py` · `live_mongo_reader.py` | 가짜만 동작 | Kafka · Spark · MongoDB 없음 | 시험 이벤트 먼저 보내기 |
| 03 실시간 수치 | `test_runs/run_service.py` · `LiveMetricsReader` | 가짜만 동작 (`fake_run_duration_sec` 동안) | 실제 대상: 트래픽 생성기 없음 | |
| 좌석 동시 확정 | `test_suites/seat_concurrency.py` | 껍데기 | 좌석 점유 · Redis 미정 | |
| 부하 | `test_suites/load_capacity.py` · `traffic_generators/` | 껍데기 | 개발 계정 2개뿐 | |
| 장애 복구 | `test_suites/failure_recovery.py` | 껍데기 | 복구할 파이프라인 없음 | |
| 봇 설정 저장 · 규칙 미리 보기 | `macro_bots/` | 저장 · 실행에 반영 동작 · 규칙 미리 보기는 대기 표시 | 판정 규칙 R1 ~ R6 정의 대기 | `RULE_CHECKS` 채우기 |
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
