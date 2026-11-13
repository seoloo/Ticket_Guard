<!--
[홍석환] 관리자 대시보드 실행 안내
관리자 인증, MongoDB 연결, 서비스 실행 및 전용 검증 방법을 설명한다.
-->
# DB 관리자 대시보드

## 실제 사용자 흐름 공개 지표

- `/admin/`: Spark가 검증 후 공개한 사용자 흐름의 최신 수치·네트워크 그래프·시계열을 표시한다.
- `/admin/db`: 기존 정제 이벤트·컬렉션·사용자 관측 조회를 보존한 경로다.
- `/admin/preview`: 실제 DB를 사용하지 않는 고정 시안이다.

기존 `TICKET_GUARD_ADMIN_MONGO_URI`만 사용한다. 새 연결 환경변수·데이터 API·자동 갱신은 추가하지 않는다. 현재 연결 대상에서 `flow_read_current`, `flow_read_series`를 읽을 수 있어야 한다. 파이프라인의 공개 뷰·계정은 별도 DB 담당 설정이며 관리자 앱이 생성하지 않는다.

실제 공개 조회는 `user_flow/reader.py`, 계약 검사는 `user_flow/contracts.py`, 표시 형식은 `user_flow/presentation.py`, 페이지 연결은 `user_flow/pages.py`에서 담당한다. 시안과 실제 화면은 관점 탐색·사용자 흐름 템플릿·그래프 코드를 공유하지만 자료 공급 경로는 분리한다.

네트워크·이상탐지는 실제 집계 계약이 아직 연결되지 않아 실제 화면에 미연결 안내만 표시한다. 공개 결과 없음·인증 실패·권한 부족·형식 오류·버전 불일치를 샘플이나 0으로 대체하지 않는다. 기존 이벤트 화면도 현재 연결 설정과 권한에 따라 조회되며, 서로 다른 DB의 자료를 임의로 찾아 합치지 않는다.

실제 연결 상태와 검사 기록은 [공개 지표 연결 기록](LIVE_CONNECTION.md)을 참고한다.

## 세 관점 화면 시안

- 사용자 흐름: `/admin/preview#flow` — 확정 지표 다섯 가지를 네트워크 그래프·수치·시계열로 표현한다.
- 네트워크 상태: `/admin/preview#network` — 요청·오류·응답 미수신·관측 시간의 검토용 제안이다.
- 이상탐지: `/admin/preview#anomaly` — 신호 유형과 대상별 관측 근거를 확인하는 검토용 제안이다.

모든 시안은 고정 샘플이며 실제 DB 연결·자동 갱신·운영 조치를 수행하지 않는다. 기존 `/admin/` 실제 화면은 유지한다.

샘플 데이터는 `src/ticket_guard_admin/monitoring_preview_data.py`, 공통 틀은 `templates/monitor_preview.html`, 관점별 화면은 `templates/preview_*.html`, 그래프와 동작은 `static/monitor_*.js`에 분리한다. 실제 데이터를 연결할 때는 이 데이터 전달 경계를 교체하고 단위·버전·결측값 계약을 확인한다.

브라우저 검사 도구는 `tests/check_preview_browser.cjs`다. 기존 관리자 설정과 게이트웨이를 사용하고 `output/admin-preview/`에 화면을 저장한다. 별도 공개 포트나 DB 쓰기는 수행하지 않는다. 관리자 로그인 과정의 일반 웹 관측 이벤트는 기존 수집 경로를 따른다.

```powershell
$env:PYTHONPATH='admin_dashboard/src;qa/src'
.venv/Scripts/python.exe -m pytest admin_dashboard/tests qa/tests/unit_tests/test_live_mongo_reader.py -q
```

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

Docker 설정은 루트 `.env` 하나이며 예시는 루트 `.env.example`이다.
웹 관리자 로그인과 DB 계정은 다르다. 앱은 `TICKET_GUARD_ADMIN_MONGO_URI`를 사용하며
URI 설정만으로 DB에 사용자를 생성하지 않는다.

기본 설치는 기존 `MONGO_WRITER_USERNAME/PASSWORD`, `MONGO_DATABASE`에 맞춰
관리자 URI를 작성한다. writer로 조회할 수 있고 관리자 앱 코드는 조회만 수행한다.
URI 자격 증명은 URL 인코딩하고 `authSource`는 계정이 생성된 `MONGO_DATABASE`로 지정한다.
reader가 없는 설치에서는 reader 검사를 실행하지 않는다.

- 내부 주소: `ticket-guard-workspace-db-mongo-1:27017`
- 네트워크: `TICKET_GUARD_ADMIN_MONGO_NETWORK`, 기본 `ticket-guard-workspace-db_mongo-backend`
- PC 포트: `mongo/compose.local.yml`의 `MONGO_HOST_PORT`
- QA의 `TICKET_GUARD_QA_SYSTEM_MONGO_URI`는 관리자 앱과 별도 설정이다.

최초 설치·writer 검사·게이트웨이 실행·Compass·재시작·오류 해결은
[루트 DB 매뉴얼](../README.md#db별-포트-번호)을 기준으로 한다.
환경 파일 통합만을 이유로 계정이나 볼륨을 변경하지 않는다.

### 관리자 서비스만 갱신

웹·QA·게이트웨이가 이미 실행 중인 경우만 사용한다.
`--no-deps`는 중지된 의존 서비스를 시작하지 않는다.

```powershell
docker compose --env-file .env -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml build admin-dashboard
docker compose --env-file .env -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml up -d --no-deps admin-dashboard
docker compose --env-file .env -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml exec -T gateway nginx -t
docker compose --env-file .env -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml exec -T gateway nginx -s reload
```

### 선택적 읽기 계정

필요한 경우만 `MONGO_ADMIN_READER_USERNAME/PASSWORD`를 둘 다 설정한다.
둘 다 없으면 생성이 생략된다. root·writer와 다른 사용자명을 사용한다.
빈 볼륨에서 자동 생성하며 기존 DB에는 유효한 관리자 인증으로 적용한다.

```powershell
docker compose --env-file .env -p ticket-guard-workspace-db -f compose.yml -f mongo/compose.local.yml --profile mongo up -d --no-deps --wait mongo
docker compose --env-file .env -p ticket-guard-workspace-db -f compose.yml --profile mongo exec -T mongo mongosh --quiet --norc /opt/mongo/setup-reader.js
docker compose --env-file .env -p ticket-guard-workspace-db -f compose.yml --profile mongo exec -T -e MONGO_VERIFY_ROLE=reader mongo mongosh --quiet --norc /opt/mongo/verify.js
```

기존 계정의 비밀번호·권한이 다르면 덮어쓰지 않는다. 원하는 경우 관리자 URI를
조회 계정으로 지정한다. QA의 외부 DB 검증은 별도의 읽기 전용 연결이며
[선택적 QA 연결](../README.md#4-선택-별도-읽기-계정과-qa-외부-db-검증)을 따른다.
팀 내부망·AWS 접속과 미검증 범위는 [DB 연결 문서](../docs/mongodb.md)를 참고한다.

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

DB 설치 재현 검사는 `pymongo==4.10.1`을 설치한 별도 Python 환경에서 다음과 같이 실행한다.
Docker와 로컬 `mongo:8.0.34`, `ticket-guard-qa:dev` 이미지가 필요하다. 실제 `.env`를 읽지 않고 무작위
테스트 계정, `tg-bootstrap-*` 프로젝트, 별도 빈 볼륨과 로컬 임시 포트를 사용한다.
종료 시 해당 검사에서 만든 자원만 제거한다. 최초 계정·권한, 내부/PC 접속,
재시작 후 유지, 기존 계정 추가와 비밀번호·권한 불일치 시 변경 거부를 검사한다.

```powershell
python -m unittest discover -s mongo/tests -v
```
