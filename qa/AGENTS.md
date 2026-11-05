# AGENTS.md · 티켓가드 QA

`qa/` 폴더에서 일하는 사람과 AI 에이전트가 지켜야 할 규칙이에요.
기획서 기준: `티켓가드 실시간 매크로 탐지 예매 시스템 기획서` (2026-11-02) 20 · 21 · 26쪽.

---

## 0. 적용 범위

- 이 문서는 **`qa/` 폴더 안에서만** 적용돼요. 저장소의 다른 폴더(웹 · db 등)는 각 팀의 규칙을 따라요.
- 함께 보는 문서

| 문서 | 언제 보나 |
|---|---|
| [`docs/implementation_guide.md`](docs/implementation_guide.md) | 기능을 만들거나 추가할 때 · 폴더별 책임 · 실행 흐름 · 추가 방법 · 구현 현황 |
| [`docs/ui.md`](docs/ui.md) | 화면을 만들거나 고칠 때 · UI 기준 · 테마 · 화면 명세 · 주소 |
| [`docs/contracts.md`](docs/contracts.md) | 시스템 데이터를 읽거나 db 브랜치와 형식을 맞출 때 |

## 1. 목표와 범위

- 이 폴더의 목표는 **자동화 QA 프로그램**을 만드는 것이에요.
- 하는 일: 입력 넣기 → 정답 따로 계산 → 시스템 결과 꺼내기 → 비교 · 보고.
- 정답표(누가 봇인지)는 **QA만** 가져요.

## 2. 절대 규칙

어기면 PR을 받지 않아요.

0. **AI 에이전트는 사용자가 직접 말하기 전에는 절대 커밋 · 푸시하지 않아요.** 한 번 허락받은 커밋 · 푸시는 그 한 번에만 해당해요. 다음 작업은 다시 허락을 받아요.
1. **정답표 · 봇 설정 · 다음 시험 계획은 QA DB 밖으로 내보내지 않아요.** 시스템 DB · 시스템 로그 · 다른 브랜치 · Issue 본문 어디에도 넣지 않아요.
   - 예외: 팀이 요청하고 QA 담당이 승인하면 **끝난 Run의 필요한 부분만** 6장 "QA 데이터 넘기기"대로 넘겨요. 시스템 DB에는 넣지 않아요.
   - 다음 시험 계획 · 아직 끝나지 않은 Run은 예외 없음.
2. **시스템 코드를 import 하지 않아요.** HTTP · Kafka · DB로만 접근해요. (`tests/boundary`가 CI에서 검사)
3. **시스템 DB에 쓰지 않고, 시스템 DB 구조에 QA 전용 필드 · 컬렉션을 요청하지 않아요.** 읽기 전용 계정만 써요.
   - 시스템 DB는 **실제 운영 데이터 기준**으로 설계해요. 운영에서 비어 있을 QA 필드는 그 자체로 비용이에요.
   - QA가 읽어야 하는 값은 운영에도 필요한 값(세션 번호 · 처리 시각 · 규칙 버전 등)으로만 요청해요.
4. **다른 브랜치에 직접 커밋하거나 merge 하지 않아요.** 바뀌어야 할 것은 Issue로 요청해요. 예외는 4장 "QA 테스트 훅"만이에요.
5. **시안 · 보고서 · PNG · PDF는 저장소에 넣지 않아요.** 코드 · 규칙 문서 · 시험 데이터만 넣어요.
6. **한글 식별자를 쓰지 않아요.** 이름은 10장 용어집을 따라요.

## 3. 작업 방식

1. 화면 시안은 **PNG 파일**로 보여 줘요. 방향을 정할 때는 **시안 10개**를 먼저 보여 주고 고르게 해요.
2. 도구 · 기술을 소개할 때는 **왜 필요한지 → 이 프로젝트 어디에 쓰이는지**를 먼저 쓰고, 설치 · 방법은 그다음에 써요.
3. 자동화 QA · Kafka · Spark는 처음 다루는 팀원이 있어요. **남에게 설명할 수 있을 만큼 쉬운 말**로 써요.

## 4. 브랜치와 협업

```text
main ← develop ← qa   (qa/ 만)
               ← db   (db 쪽 폴더만)
               ← 웹 · 앱 브랜치
```

- **develop을 거쳐서만 합쳐요.** qa는 develop에 PR로 넣고, 필요하면 develop을 qa로 받아와요. qa ↔ db 직접 merge는 하지 않아요.
- **폴더 주인**: qa는 `qa/`만 고쳐요. `qa/` 밖이 바뀌어야 하면 Issue로 요청해요.
  - 예외: `.github/workflows/qa.yml` 하나. GitHub Actions는 이 위치에서만 동작해요.
  - 예외: **QA 테스트 훅** (시험 계정 · 보안문자 고정 정답 등 QA 자동화에 필요한 시험 환경 전용 장치). QA가 시스템 코드에 직접 구현할 수 있어요. 조건은 아래 전부예요.
    1. **AI 에이전트는 `qa/` 밖을 고치기 전에 반드시 QA 담당자에게 먼저 묻고 승인받아요.** 무엇을 · 왜 · 어느 파일을 고치는지 먼저 알려요.
    2. 작업 전에 Issue로 해당 팀에 알리고 진행 중인 작업과 충돌하는지 확인해요. (예: Issue #6)
    3. `develop`에서 브랜치를 따서 `develop`으로 PR을 보내고, 해당 팀의 리뷰 승인 뒤에 병합해요. qa 브랜치에 섞지 않아요.
    4. `DJANGO_DEBUG=1` + 환경 변수를 켰을 때만 동작하고, 기본값은 꺼짐이에요. 끈 상태에서 기존 테스트가 전부 통과해야 해요.
- **아직 develop에 안 들어간 다른 브랜치를 시험할 때**: merge 하지 않고, 그 브랜치를 별도 폴더(`git worktree`)로 꺼내 컨테이너를 띄운 뒤 QA의 시험 대상 주소만 바꿔요.
- **입구 · 포트 (A안 · 2026-11-04 확정)**: 밖에서 들어오는 주소는 **`127.0.0.1:8000` 하나**예요. 팀 입구(nginx)가 주소를 보고 나눠요.

  | 포트 | 무엇 | 밖에서 접속 |
  |---|---|---|
  | 8000 | 팀 입구(nginx) · 유일한 입구 · `/`는 Django, `/qa/`는 QA 대시보드 | O |
  | `web` 컨테이너 안 8000 | Django 예매 웹 · 로그인 (develop) | X |
  | `qa-dashboard` 컨테이너 안 8000 | QA 대시보드 | X |

  - 관리자로 로그인하면 Django가 `/qa/`로 보내요. 팀 입구가 Django `/auth/check-admin/`에 물어보고, 관리자일 때만 `X-Admin-User` 헤더를 붙여 QA로 넘겨요. 브라우저가 보낸 같은 헤더는 팀 입구가 지워요.
  - QA 대시보드는 **팀 compose(`compose.gateway.yml`)의 `qa-dashboard` 컨테이너로만** 띄워요. 내 PC 포트를 따로 열지 않아요. 화면 확인: `127.0.0.1:8000`에서 관리자로 로그인.
  - 컨테이너는 서로 포트 공간이 달라서 `web`과 `qa-dashboard`가 둘 다 안쪽 8000을 써도 충돌하지 않아요.
  - `TICKET_GUARD_QA_SYSTEM_BASE_URL`(컨테이너 안에서는 `http://web:8000`)은 시험 대상 주소예요.
- **커밋 제목**: `[QA] 무엇을 했는지` (예: `[QA] add fake verdict api`)
- **PR 체크리스트**
  - [ ] 정답표 · 봇 설정이 포함되지 않았다
  - [ ] `qa/` 밖을 고치지 않았다
  - [ ] `pytest qa/tests` 통과
  - [ ] 이름 · 주석이 10장 규칙을 따른다

## 5. 시험 대상 현황

시스템이 바뀌면 이 표를 고쳐요. (마지막 확인: develop `d323060`, 2026-11-03)

| 기획서 | 현재 시스템 코드 | QA에서 할 수 있는 것 |
|---|---|---|
| FastAPI | Django 5.2 1단계 시뮬레이션 | HTTP 시험 가능 (`/api/action/` · `/api/events/` · `/health/`) |
| Kafka · Spark · MongoDB | 없음 · 전부 서버 메모리 · 재시작하면 초기화 | 가짜 대상으로만 |
| Redis 좌석 점유 5분 (E16) | 선택만으로는 재고를 잡지 않음 | 보류 |
| 판정 R1 ~ R6 · 4단계 | 없음 | 가짜 판정 서버로만 |
| 이벤트 스키마 | v1 확정 (`docs/contracts.md`) | 형식 검사 시험 가능 |

## 6. 데이터 경계와 공유

**저장소별 권한**

| 저장소 | 시스템 | QA |
|---|---|---|
| 시스템 MongoDB (`ticketguard`) · 운영 데이터 구조만 | 읽기 · 쓰기 | **읽기만** |
| QA DB (정답표 · 봇 설정 · 실행 기록 · 점수) · 지금 SQLite · 서버 배포 시 PostgreSQL | **접근 못 함** | 읽기 · 쓰기 |
| QA 전달용 (`ticketguard_qa_archive` 또는 JSON 파일) · 요청 시에만 | 분석 담당만 읽기 · 판정 코드 읽기 금지 | 만듦 |
| 실행 보고서 | 볼 수 있음 | 만듦 |

**공유 3단계**

| 단계 | 내용 | 언제 · 어디로 |
|---|---|---|
| 바로 공유 | 합격 기준 n / 7 · 지연 p95 · 오류율 · 격리 · 중복 건수 · 복구 시간 같은 **숫자** | 언제든 · QA 대시보드 · Issue |
| 실행 끝난 뒤 · 요청 시 | Run 결과 숫자 · 적발 목록 (놓친 봇 · 오탐 · 실제 종류) | 그 Run이 끝난 뒤에만 · 6장 QA 데이터 넘기기 · 실행 보고서 |
| 요청 · QA 담당 승인 시 | 끝난 Run의 정답표 · 시드 · 그 Run이 쓴 봇 설정 | 6장 QA 데이터 넘기기 · 내보낸 봇 버전은 공개됨 |
| 공유 안 함 | 진행 중 · 다음 Run의 정답표 · 봇 설정값 · 다음 시험 계획 | QA DB에만 |

- QA가 만드는 시험 사용자는 `qa-0001`처럼 **사람인지 봇인지 드러나지 않는 이름**을 써요. 어떤 이름이 봇인지는 QA DB에만 있어요.
- 시험 트래픽은 QA 필드 없이 구분해요. 시험 계정 이름(`qa-user-*`) · Run 시간 범위 · 또는 시험용 DB 이름(`ticketguard_test`)

**QA 데이터 넘기기** (필요할 때만 · 형식: [`docs/contracts.md`](docs/contracts.md) 3-5)

- **조건**: 팀 요청(Issue) + **QA 담당 승인** · 대시보드 버튼 없이 명령으로만
  `ticket-guard-qa export-archive --run … --recipient … --reason … [--collection …]`
- **끝난 Run만**: `PASSED` · `FAILED` · 실행 중 · 취소 · 오류 Run은 거절
- **필요한 부분만**: 기본은 결과 숫자(`QA_ARCHIVE_RUNS`) + 적발 목록(`QA_ARCHIVE_FINDINGS`) · 정답표(`QA_ARCHIVE_ANSWER_KEYS`) · 봇 설정(`QA_ARCHIVE_BOT_VERSIONS`)은 `--collection`으로 직접 지정 · 시드는 정답표 · 봇 설정과 함께일 때만
- **받는 곳**: JSON 파일 → 받는 쪽이 `mongoimport`로 **시스템 DB와 다른 DB** `ticketguard_qa_archive`에 넣음 · 판정 코드 읽기 금지 · 시스템 DB(`ticketguard`)에는 넣지 않음
- **넣지 않는 것**: 다음 시험 계획 · 그 Run이 쓰지 않은 봇 버전 · 행동 근거는 시스템이 측정한 `SESSION_FEATURES`를 세션 번호로 연결
- **새 필드가 필요할 때**: `qa_database/archive_export.py`의 `*_FIELDS`에 한 줄 · 새 묶음은 `ExportCollection` 하나 추가 · `contracts.md` 3-5 표도 같이 고침
- **복사이지 이동이 아님**: 원본은 QA DB에 그대로 · 이후 바뀐 내용은 자동으로 따라가지 않음 · 필요하면 다시 내보내기
- **기록**: QA DB `archive_exports`에 언제 · 누구에게 · 왜 · 어떤 Run · 어떤 컬렉션 · 공개된 봇 버전
- **정답표 · 봇 설정을 넘긴 뒤**: 그 봇 버전은 **공개됨** · 그 버전으로 Run을 시작하면 03 화면에 경고 · B2에서 새 버전 저장 · 새 시드로 시험

## 7. db 브랜치와 주고받는 것

**받을 것** (QA가 요청)

| # | 무엇 | 왜 필요한가 |
|---|---|---|
| 1 | QA용 읽기 전용 계정 | 시스템 DB를 바꾸지 않고 결과만 읽기 |
| 2 | 컬렉션 이름 · 필드 · 인덱스 | 시험 결과를 찾는 조회가 느려지지 않게 (userId · bookingAttemptId · receivedAt) |
| 3 | 판정 결과 저장 위치 | 정답표와 비교할 대상 |
| 4 | 시험 전 초기화 방법 또는 QA 전용 DB 이름 | 실행마다 같은 조건에서 시작 |
| 5 | Docker 네트워크 이름 | QA 컨테이너가 같은 네트워크에 붙기 |

**줄 것** (QA가 전달)

| # | 무엇 | 경로 |
|---|---|---|
| 1 | 요청 사항 (위 표) | Issue · 라벨 `db` |
| 2 | 발견한 결함 (eventId 중복 저장 · 재시작 후 두 번 집계 · 격리 누락 · TTL 미적용 · 재고 동시 차감 오류 등) | Issue · 라벨 `db` `qa-finding` · 결함 하나에 Issue 하나 |
| 3 | 계약 시험 데이터 (올바른 · 틀린 이벤트 샘플) | `qa/case_data/event_contracts/` · db 팀이 가져다 씀 |
| 4 | 결과 요약 | QA 대시보드 · 실행 보고서 (6장 공유 단계를 따름) |
| 5 | 요청 시 · 끝난 Run의 필요한 부분 (결과 · 적발 목록 · 승인 시 정답표 · 봇 설정) | JSON 파일 → `ticketguard_qa_archive` (6장 QA 데이터 넘기기 · QA 담당 승인) |

**결함 Issue에 꼭 적는 것**
- 제목: `[QA][db] 무엇이 잘못됐는지`
- 실행 번호(`run_id`) · 관련 E 코드 · 재현 방법
- 기대한 결과 / 실제 결과
- [ ] 정답표 · 봇 설정이 포함되지 않았다

**형식이 바뀔 때**
1. db 팀이 원본 문서를 고치고 Issue로 알려 줘요.
2. QA가 `docs/contracts.md`와 계약 시험 데이터를 고쳐요.
3. 계약 시험을 다시 돌리고 결과를 같은 Issue에 남겨요.

## 8. 일정

- 이번 주: **큰 틀**(뼈대 · 가짜 대상 · 자체 점검 · 콘솔 · CI · 화면 틀).
- 다음 주부터: QA 시작(실제 대상 연결 · 트래픽 · 부하 · 복구).

## 9. 기술 방향

| 결정 | 이유 |
|---|---|
| 데스크톱 앱 대신 **웹 대시보드** | 내 PC에서 띄워 보고, AWS(EC2)에 올려 브라우저로 확인 가능 |
| C# 대신 **Python으로 통일** | 시스템이 Python · 팀원이 화면과 시험을 함께 추가할 수 있어야 함 |
| 대시보드 사용자 = **관리자** | DB 관련 기능(조회 · 시험 데이터)까지 화면에 포함 |
| 포트폴리오 고려 | QA 자동화 · 데이터 품질 · 탐지 모델 평가를 숫자로 보여 줄 수 있게 |

**스택**: Python 3.13 · pytest · httpx · Locust · Playwright · Maestro · confluent-kafka · pymongo · redis-py(Redis 결정 후) · Docker SDK · FastAPI + Jinja2 + HTMX(QA 대시보드) · Chart.js · SQLAlchemy(QA DB) · GitHub Actions · Docker Compose

- 시스템 쪽 프레임워크(지금은 Django)와 상관없이 QA는 HTTP · DB로만 붙어요.

## 10. 코드 규칙

### 이름
- 현업 엔지니어가 짓는 것처럼, **사람이 이름만 보고 무엇인지 알 수 있게** 지어요. 영어 · 파이썬 관례(snake_case 함수 · PascalCase 클래스 · UPPER 상수).
- 패키지 이름은 `ticket_guard_qa`예요.
- **줄임말을 쓰지 않아요.** (`cfg` → `run_config`, `db.py` → `database.py`) 허용하는 약어: `id` · `url` · `api` · `http` · `json` · `html` · `p95`
- 폴더는 무엇을 모아 둔 곳인지(`system_targets`, `macro_bots`), 파일은 안에 든 것 하나(`confusion_matrix.py`), 시험 묶음은 무엇을 확인하는지(`pipeline_latency.py`)로 지어요.
- 화면 파일은 시안 번호를 앞에 붙여요. (`screen_01_home.html`, `screen_b4_detection_result.html`)
- 함수는 동사로 시작(`build_answer_key`, `calculate_detection_rate`) · 클래스는 명사(`RunService`, `LiveDjangoSystem`).
- 참 / 거짓은 `is_` · `has_` · 단위는 이름 끝(`latency_ms`, `timeout_sec`, `detection_rate_percent`).

| 기획서 용어 | 코드 이름 |
|---|---|
| 정답표 | `answer_key` |
| 정상 · 관찰 · 추가 확인 · 보류 | `VerdictStage.NORMAL / OBSERVE / CHALLENGE / HOLD` |
| 사람 · 봇 A ~ D · 새 유형 | `ActorType.HUMAN / BOT_A / BOT_B / BOT_C / BOT_D / BOT_NEW` |
| 실행 · 시험 묶음 · 사례 | `run` · `suite` · `case` |
| 합격 기준 | `pass_criteria` |
| 격리 | `quarantine` |
| 놓친 봇 · 오탐 | `missed_bot` · `false_positive` |
| 탐지율 | `detection_rate` |
| 가짜 대상 · 실제 대상 | `fake` · `live` |

시스템 필드는 camelCase 그대로 읽고, QA 코드 안에서는 snake_case로 바꿔요. 대응표는 [`docs/contracts.md`](docs/contracts.md)에 있어요.

### 주석
- 다시 리팩터링하지 않도록, **중요한 코드에만 핵심을 짧게** 달아요. 설명 문장은 쓰지 않아요.
- 근거가 기획서에 있으면 쪽수 · E 코드를 붙여요.

```python
SEAT_HOLD_TIMEOUT_SEC = 300      # 좌석 점유 5분 · E16
# QA DB 전용 · 시스템 접근 금지
# 탐지 = CHALLENGE 이상
```

- 폴더 · 파일 첫 줄, `TODO` 형식은 [`docs/implementation_guide.md`](docs/implementation_guide.md) 6장을 따라요.

### 구조

폴더 트리 · 폴더별 책임 · 실행 흐름 · 추가 방법은 [`docs/implementation_guide.md`](docs/implementation_guide.md) 한 곳에만 있어요.

### 테스트
- 새 시험은 E 코드 · T 코드 하나 이상에 연결해요. 연결이 없으면 `case_data/`에 먼저 사례를 추가해요.
- 가짜 대상에서 먼저 통과시키고, 실제 대상은 5장 표에서 "가능"인 것만 돌려요.
- 시간 · 난수는 고정값을 넣을 수 있게 만들어요. 같은 입력이면 같은 정답표가 나와야 해요.

## 11. 열린 결정

- [x] 매크로 봇 화면 연결 확정 (`docs/ui.md` 매크로 봇) · 2026-11-04
- [ ] QA DB를 SQLite로 시작할지 확정
- [ ] 판정 결과를 어느 컬렉션에 저장할지 (db 팀과)
- [ ] QA가 읽을 운영 필드 확인 (`bookingAttemptId` · 처리 시각 · `ruleSetVersion`) · QA 읽기 전용 계정 (db 팀 · Issue)
- [ ] QA DB를 PostgreSQL로 옮기는 시점 (서버 배포 · 팀원 직접 조회 필요할 때)
- [ ] Redis를 쓸지 (좌석 점유 시험 E16 여부가 달라짐)
- [ ] 세션 구분 키: 기획서의 `session_hash`인지, 시스템의 `bookingAttemptId`인지
- [ ] MongoDB가 붙는 시점 (QA가 실제 대상으로 넘어가는 시점)
- [ ] 팀 입구(nginx) · Django 관리자 계정과 `/auth/check-admin/` 반영 시점 (develop · 팀 compose)
- [x] 관리자 로그인 → QA 대시보드 · 입구 하나(A안) · 관리자 = QA 대시보드를 쓰는 팀원 (운영자 상황판과 별개) · 2026-11-04
