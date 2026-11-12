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

웹 로그인 계정과 DB 서비스 계정은 역할이 다르다. 웹 관리자로 로그인한 후 서버가 별도의 읽기 전용 계정으로 조회한다.

- `TICKET_GUARD_ADMIN_MONGO_URI`: 관리자 앱 전용 URI. 대상 DB와 계정이 생성된 `authSource`를 명시한다.
- `TICKET_GUARD_ADMIN_MONGO_NETWORK`: MongoDB가 실행 중인 외부 Docker 네트워크 이름.
- QA의 `TICKET_GUARD_QA_SYSTEM_MONGO_URI`는 관리자 앱에서 사용하지 않는다.
- URI와 비밀번호는 무시된 루트 `.env`에만 보관한다.

### 최초 설치 · 빈 DB

모든 명령은 저장소 루트에서 실행한다. `.env`가 없을 때만
`Copy-Item .env.example .env`로 만들고 placeholder를 실제 값으로 교체한다.
기존 `.env`는 덮어쓰지 않는다.

| 환경 변수 | 용도 / 인증 DB |
|---|---|
| `MONGO_ROOT_USERNAME`, `MONGO_ROOT_PASSWORD` | 최초 관리자 생성 / `admin` |
| `MONGO_WRITER_USERNAME`, `MONGO_WRITER_PASSWORD` | 적재 계정 생성 / `MONGO_DATABASE` |
| `MONGO_ADMIN_READER_USERNAME`, `MONGO_ADMIN_READER_PASSWORD` | 대시보드 조회 계정 생성 / `MONGO_DATABASE`, `read` 하나 |
| `MONGO_DATABASE` | 시스템 DB 이름, 기본 `ticketguard` |
| `MONGO_HOST_PORT` | 컴퍼스용 PC 포트, 컨테이너 내부는 항상 `27017` |
| `TICKET_GUARD_ADMIN_MONGO_URI` | 위 조회 계정과 같은 비밀번호·DB·`authSource` |
| `TICKET_GUARD_ADMIN_MONGO_NETWORK` | DB 프로젝트의 외부 네트워크, 기본 `ticket-guard-workspace-db_mongo-backend` |

조회 계정 설정은 기존 설치 호환을 위해 두 값이 모두 비어 있으면 생략된다.
대시보드를 사용할 새 환경에서는 반드시 둘 다 설정한다. 관리자·쓰기·조회 계정은
서로 다른 사용자명과 비밀번호를 사용한다. URI 사용자명·비밀번호의 특수문자는
URL 인코딩하고, 계정 생성 변수에는 인코딩 전 값을 사용한다.
예시 URI는 `.env.example`에 있다. 내부 주소는
`ticket-guard-workspace-db-mongo-1:27017`이며 PC의 공개 포트와 다르다.

먼저 시스템 DB만 실행한다. 아래 고정 프로젝트 이름을 사용해야 기본 네트워크와
URI의 컨테이너 이름이 일치한다. DB만 실행할 때 Kafka는 필요하지 않다.

```powershell
docker compose --env-file .env -p ticket-guard-workspace-db -f compose.yml -f mongo/compose.local.yml --profile mongo config --quiet
docker compose --env-file .env -p ticket-guard-workspace-db -f compose.yml -f mongo/compose.local.yml --profile mongo up -d --wait mongo
docker compose --env-file .env -p ticket-guard-workspace-db -f compose.yml --profile mongo exec -T mongo mongosh --quiet --norc /opt/mongo/verify.js
docker compose --env-file .env -p ticket-guard-workspace-db -f compose.yml --profile mongo exec -T -e MONGO_VERIFY_ROLE=writer mongo mongosh --quiet --norc /opt/mongo/verify.js
docker compose --env-file .env -p ticket-guard-workspace-db -f compose.yml --profile mongo exec -T -e MONGO_VERIFY_ROLE=reader mongo mongosh --quiet --norc /opt/mongo/verify.js
```

각 명령의 종료 코드 0과 검증 성공 출력을 확인한다. 빈 볼륨에서는 공식 MongoDB
진입점이 root를 만들고, `mongo/init.js`가 writer와 조회 계정, 기존 `raw_events`를
만든다. 대시보드는 존재하는 업무 컬렉션을 읽으며 임의의 판정 데이터나 샘플을
DB에 생성하지 않는다. `ticketguard_results`가 자동 생성된다고 가정하지 않는다.

그다음 웹·Kafka·게이트웨이를 실행한다. 현재 팀 게이트웨이는 QA 서비스도 함께
사용하므로 먼저 [QA 설치 문서](../qa/README.md)의 `QA_MONGO_*`를 루트 `.env`에
준비한다. QA 계정·구조는 이 관리자 초기화에서 생성하거나 변경하지 않는다.

```powershell
docker compose -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml build web qa-dashboard admin-dashboard
docker compose -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml up -d --wait
docker compose -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml exec -T gateway nginx -t
```

관리자로 로그인하고 `/admin/`에서 DB 조회를 확인한다.
관리자 서비스만 갱신하는 아래 명령은 웹·QA·게이트웨이가 이미 실행 중일 때 사용한다.
`--no-deps`는 중지된 다른 서비스를 시작하지 않는다.

```powershell
docker compose -f compose.yml -f compose.gateway.yml build admin-dashboard
docker compose -f compose.yml -f compose.gateway.yml up -d --no-deps admin-dashboard
docker exec ticket-guard-gateway-1 nginx -t
docker exec ticket-guard-gateway-1 nginx -s reload
```

### 기존 DB · 조회 계정 추가

공식 이미지의 초기화는 빈 볼륨에서만 실행된다. `.env` 수정이나 컨테이너 재생성은
기존 DB 계정을 변경하지 않는다. DB 관리자가 보유한 유효한 기존 root 정보와
추가할 조회 계정을 `.env`에 설정한 뒤 직접 실행한다.

```powershell
docker compose --env-file .env -p ticket-guard-workspace-db -f compose.yml -f mongo/compose.local.yml --profile mongo up -d --no-deps --wait mongo
docker compose --env-file .env -p ticket-guard-workspace-db -f compose.yml --profile mongo exec -T mongo mongosh --quiet --norc /opt/mongo/setup-reader.js
docker compose --env-file .env -p ticket-guard-workspace-db -f compose.yml --profile mongo exec -T -e MONGO_VERIFY_ROLE=reader mongo mongosh --quiet --norc /opt/mongo/verify.js
```

첫 명령은 같은 볼륨을 유지하고 환경 변수·스크립트 마운트를 반영한다.
조회 계정이 없을 때만 생성한다. 이미 있으면 비밀번호와 `read` 하나의 권한을
검증하며, 다르면 기존 계정을 수정하지 않고 실패한다. 기존 writer/root를
변경하거나 복구하는 명령은 아니다. 관리자 인증이 안 되면 중단하고 기존 DB
관리자에게 확인한다. `down -v`, 볼륨 초기화, 인증 해제는 사용하지 않는다.

### 컴퍼스와 AWS

QA에서 시스템 DB를 조회할 때도 이미 생성한 대시보드 reader를 사용할 수 있다.
별도 계정을 수동으로 만들 필요 없이 QA URI를 같은 조회 계정으로 설정하고,
루트의 선택적 `compose.qa-db-access.yml`로 DB 네트워크를 연결한다.
원본 DB reader·출처 값·파일 조합·접속 검사 명령은
[QA 실제 DB 연결](../docs/mongodb.md#qa-실제-db-연결)을 따른다. QA 파일은 수정하지 않는다.

컴퍼스 주소는 `mongodb://127.0.0.1:<MONGO_HOST_PORT>/`다.
고급 연결 옵션에서 조회 계정의 사용자명·비밀번호를 입력하고 인증 DB를
`MONGO_DATABASE`로 지정한다. writer도 같은 인증 DB이며 root만 `admin`이다.
원본 DB `27020/ticketguard_raw`와 다른 서버다. 로컬 포트는
`mongo/compose.local.yml`을 붙인 경우에만 열리며 기본값은 `27017`이다.
다른 PC에서 이 PC의 DB를 조회하려면 그 PC의 `localhost`가 아니라 SSH 터널 등
별도의 접근 경로가 필요하다.

단일 EC2의 Docker Compose도 같은 초기화 코드를 사용한다. 비밀값은 배포 환경에서
주입하고 새 저장소라면 초기 계정을 생성한다. 기존 디스크라면 위 기존 DB 절차를
사용한다. DB 프로젝트 이름을 변경하면 URI의 호스트와 네트워크도 함께 바꾼다.
DB 포트를 인터넷에 공개하지 않는다. 원격 Compass는 승인된 SSH 터널/VPC 경로로
연결한다. 현재 웹·Kafka 실행 구성은 개발용이며 AWS 운영 설정, 인증서·TLS,
여러 EC2 간 네트워크 및 실제 AWS 배포는 별도 검증이 필요하다.
팀 내부망에는 기존 `mongo/compose.lan.yml`을 선택적으로 사용할 수 있다.
같은 PC·팀 내부망·AWS 주소의 차이는 [DB 접속 경로](../docs/mongodb.md#같은-pc--팀-내부망--aws)를 따른다.
이 문서의 로컬 명령 성공을 AWS 검증 완료로 간주하지 않는다.

참고: [MongoDB 공식 이미지의 최초 초기화 규칙](https://hub.docker.com/_/mongo),
[MongoDB 계정 생성](https://www.mongodb.com/docs/manual/reference/method/db.createUser/).

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
