# DB 관리자 대시보드

관리자 앱은 `admin_dashboard` 브랜치의 루트 `admin_dashboard/`에 둔다. Python 패키지는 `src/ticket_guard_admin/`이며 `ticket_guard_qa`를 import하지 않는다.
QA 시험 실행 앱과 별도 프로세스로 실행하며 QA DB, Run 상태, 정답표를 초기화하거나 조회하지 않는다.

## 프로젝트 구조

```text
admin_dashboard/
├─ pyproject.toml · Dockerfile · .dockerignore · README.md
├─ src/ticket_guard_admin/
│  ├─ app.py              앱 생성 · 실제 화면과 샘플 주소
│  ├─ settings.py         관리자 전용 환경 변수
│  ├─ dependencies.py     게이트웨이 관리자 헤더 확인
│  ├─ pages.py            HTML 렌더링
│  ├─ mongo_reader.py     읽기 전용 조회 · 관측 지표 집계
│  ├─ preview_data.py     시안용 고정 샘플
│  ├─ templates/          실제 화면 · 샘플 화면
│  └─ static/             CSS · JavaScript
└─ tests/                 관리자 전용 테스트
```

관리자만 설치할 때는 저장소 루트에서 `python -m pip install -e "./admin_dashboard[dev]"`를 실행한다.
QA 패키지, Kafka 클라이언트, QA 데이터베이스는 관리자 앱 설치·실행에 필요하지 않다.

## 로그인과 접속

- 주소: `http://127.0.0.1:8000/admin/`
- 시안용 샘플: `http://127.0.0.1:8000/admin/preview` (동일한 관리자 인증 필요)
- 웹 로그인: 루트 `.env`의 `DEMO_ADMIN_USERNAME` / `DEMO_ADMIN_PASSWORD`.
- 기존 웹 로그인 후 QA 화면으로 이동했다면 DB 대시보드 메뉴를 선택한다. `/qa/db`는 게이트웨이에서 `/admin/`로 연결한다.
- 게이트웨이는 웹의 `/auth/check-admin/`으로 세션을 검증한 뒤 `X-Admin-User`를 새로 넣는다. 외부에서 보낸 헤더는 사용하지 않는다.
- 관리자 컨테이너의 포트는 외부에 공개하지 않는다. 웹과 QA 컨테이너 내부의 같은 포트와 충돌하지 않는다.

## DB 연결 설정

웹 로그인 계정과 DB 서비스 계정은 역할이 다르다. 웹 관리자로 로그인한 후 서버가 별도의 읽기 전용 계정으로 조회한다.

- `TICKET_GUARD_ADMIN_MONGO_URI`: 관리자 앱 전용 URI. 대상 DB와 계정이 생성된 `authSource`를 명시한다.
- `TICKET_GUARD_ADMIN_MONGO_NETWORK`: MongoDB가 실행 중인 외부 Docker 네트워크 이름.
- QA의 `TICKET_GUARD_QA_SYSTEM_MONGO_URI`는 관리자 앱에서 사용하지 않는다.
- URI와 비밀번호는 무시된 루트 `.env`에만 보관한다.

2026-11-09 로컬 확인 시 실제 생성된 애플리케이션 DB는 `ticketguard`였다. `ticketguard_results`는 생성되어 있지 않았다.
`ticketguard`에 관리자 앱 전용 계정 `ticketguard_admin_reader`를 추가했고 역할은 해당 DB의 `read` 하나다.
기존 root와 writer 계정의 권한, 기존 QA URI, 업무 컬렉션은 변경하지 않았다.

관리자 서비스만 반영:

```powershell
docker compose -f compose.yml -f compose.gateway.yml build admin-dashboard
docker compose -f compose.yml -f compose.gateway.yml up -d --no-deps admin-dashboard
docker exec ticket-guard-gateway-1 nginx -t
docker exec ticket-guard-gateway-1 nginx -s reload
```

## 표시 데이터와 한계

- `clean_events`: `userId`, `bookingAttemptId`, `showId`, `scheduleId`, `eventId`, `eventType`, `result`, `errorCode`, `occurredAt` 기반 집계.
- `quarantine_events`: 전체 기간 `reason`별 문서 수. `rawValue`는 읽거나 노출하지 않는다.
- `event_metrics`: 컬렉션 문서 수. 문서 수와 실제 이벤트 수를 혼동하지 않는다.
- 공연명 사전이 없으므로 공연 ID와 회차 ID를 표시한다.
- 대기열 시작은 `queue_enter` 또는 `queue_register`가 관측된 고유 `bookingAttemptId`다. 두 이벤트가 있어도 하나로 센다.
- 전환율은 위 시작 ID 중 `booking_confirm_success`와 `result=success`가 관측된 비율이다. 선행 단계가 없는 성공 이벤트는 분자에 포함하지 않는다.
- 단계별 관측 수는 단계마다 고유 예매 시도를 센다. 누락된 단계를 추정해 채우지 않는다.
- 체류 시간은 동일 시도에서 양쪽 단계의 `occurredAt`이 있고 시간 순서가 맞는 표본만 사용한다. 표본이 없으면 미관측이다. p95는 nearest-rank 방식이다.
- 봇 판정 컬렉션이 없으므로 봇 여부와 우선순위를 생성하지 않는다. 의심 활동 화면은 거부·실패 이벤트가 있는 사용자와 실제 근거를 검토하는 조회 화면이다.
- 실제 화면의 검토 상태·메모 저장은 미연결이다. 샘플의 브라우저 저장 기록을 실제 판정에 적용하지 않는다.
- 전체 기간이 기본이다. 오늘과 최근 24시간, 공연·회차 ID, 시뮬레이션 여부 필터는 DB 조회에 적용한다.
- 이벤트 분석은 최근 5,000건으로 제한한다. 상한에 도달하면 부분 분석을 명시한다. 컬렉션 문서 수와 격리 사유는 필터와 무관한 전체 기간 값으로 별도 표시한다.
- DB 조회 실패 시 오류 상태를 표시한다. 샘플 데이터로 대체하지 않는다.

## 검증

관리자 전용 테스트는 `python -m pytest admin_dashboard/tests`로 실행한다. 앱 생성 시 QA import를 차단하는 검사도 포함한다.
공용 연결을 변경했다면 QA MongoDB 회귀 테스트, QA 화면과 경계 검사를 포함해 `python -m pytest qa/tests`도 실행한다.
실제 게이트웨이에서는 비로그인·일반 사용자 차단, `DEMO_ADMIN_USERNAME` 로그인, DB 조회, 필터와 상세 타임라인을 확인한다.
