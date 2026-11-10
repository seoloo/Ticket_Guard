# Ticket Guard · 티켓가드

> 브랜치별 문서는 아래 표에서 시작합니다. 이 README는 프로젝트 전체 소개이며 `main`에서만 수정합니다.

| 브랜치 | 담당 영역 | README |
|---|---|---|
| `develop` | 예매 웹 (Django) | `web/README.md` · 작성 예정 |
| `db` | 이벤트 파이프라인 · DB (Kafka · Spark · MongoDB) | `pipeline/README.md` · 작성 예정 |
| `qa` | 자동화 QA · QA 대시보드 | [qa/README.md](qa/README.md) |

공연 예매 웹과 실시간 이벤트 처리 파이프라인 프로젝트. **현재 구현 범위: Django 웹 + 실제 Kafka 이벤트 발행 + MongoDB 실행 환경**입니다. Spark 원본 적재 코드와 비적재 점검을 추가했습니다. 실제 적재·복구 실험은 미실행입니다. [Spark 문서](docs/spark.md)를 확인하세요. 자세한 구성·스키마·실행 명령은 [Kafka 연결 문서](docs/kafka.md)를 확인하세요.

## 실행

Docker Desktop에서 Linux containers를 실행한 뒤 PowerShell에서:

```powershell
cd C:\workspace\Ticket_Guard
docker compose --env-file .env up -d --build
docker compose --env-file .env ps
```

접속: http://localhost:8000

| 개발용 계정 | 비밀번호 |
|---|---|
| ticketguard | ticketguard-demo |
| guest | ticketguard-demo |

두 계정은 예매 내역과 입장 권한이 분리되고 공연 재고는 공유됩니다. 실제 계정 체계가 아닌 개발용 로그인입니다. 외부에 배포하지 마세요.

신규 환경에서 `.env`가 없을 때만 `.env.example`을 `.env`로 복사하고 수정한 뒤 `docker compose --env-file .env up -d`로 재생성합니다. `.env`는 Git에서 제외됩니다. `.env.example`의 비밀번호는 공개된 데모 값입니다.

```powershell
Copy-Item .env.example .env
docker compose --env-file .env up -d
docker compose --env-file .env logs --tail 50 web
```

`compose.yml`은 기존 파일명 그대로 유지했습니다. Python **3.13.15**, Django **5.2.18**, Pillow **12.0.0**을 사용합니다. 호스트에 Python을 설치할 필요가 없습니다. 기본 Compose는 Kafka와 토픽 초기화를 함께 실행합니다. MongoDB는 별도 mongo 프로필로 추가했습니다. 같은 이름을 쓰는 이전 폴더 자원과 충돌하지 않도록 MongoDB 명령에는 `-p ticket-guard-workspace-db`를 반드시 사용합니다. 실행·초기화·검증은 [MongoDB 문서](docs/mongodb.md)를 따릅니다. Spark는 별도 `ticket-guard-workspace-pipeline` 프로젝트와 spark 프로필로 빌드·점검합니다. 실제 적재 명령은 [Spark 문서](docs/spark.md)를 먼저 확인하세요. 기존 `.env`를 복사 명령으로 덮어쓰지 마세요.

### QA 대시보드 접속 (관리자)

관리자 로그인과 QA 대시보드(`/qa/`)는 팀 입구 `compose.gateway.yml`과 QA DB `qa/compose.qa-db.yml`을 함께 붙여 실행할 때만 켜집니다. `docker compose --env-file .env up -d`만으로 띄우면 관리자 로그인이 꺼져 있어 "아이디 또는 비밀번호를 확인해 주세요"가 표시됩니다.

1. 기존 `.env`에 두 묶음을 직접 추가합니다. `.env`는 Git에서 제외되므로 pull로 갱신되지 않습니다.
   - 관리자 계정: `.env.example`의 `DEMO_ADMIN_USERNAME` · `DEMO_ADMIN_PASSWORD` 두 줄
   - QA DB 계정: `QA_MONGO_*` 여섯 줄 · 형식은 [qa/README.md](qa/README.md)
2. 세 파일을 붙여 실행합니다. 이후 `ps` · `logs` · `down`에도 같은 `-f`를 붙입니다.

```powershell
docker compose --env-file .env -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml up -d --build
docker compose --env-file .env -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml ps
```

3. http://localhost:8000/login/ 에서 관리자 계정으로 로그인하면 QA 대시보드로 이동합니다.

| 증상 | 원인 | 확인 명령 |
|---|---|---|
| 관리자 로그인 실패 | `.env` 관리자 두 줄 누락 · `compose.gateway.yml` 누락 | `docker compose --env-file .env -f compose.yml -f compose.gateway.yml exec web printenv DEMO_ADMIN_USERNAME` · 출력 없으면 누락 |
| 로그인 후 `/qa/` 502 | QA 대시보드 미기동 · `qa/compose.qa-db.yml` 누락 · `QA_MONGO_*` 누락 | `docker compose --env-file .env -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml logs --tail 50 qa-dashboard qa-mongo` |
| `/qa/` 접속 시 로그인 화면으로 이동 | 고객 계정 또는 로그아웃 상태 · 관리자 전용이라 정상 차단 | 관리자 계정으로 다시 로그인 |

## 사용 흐름

로그인 → 공연 검색/필터 → 공연 상세 → 대기열(약 12초) → 보안문자 → 지정석/자유석 선택 → 예매 확정 → 완료/내역.

- 지정석: A~J × 1~10, 최대 4석. 자유석: 잔여 수량 이내 1~4명.
- 선택만으로 재고를 점유하지 않습니다. 확정 요청에서 서버가 가격·재고·입장 권한을 확인합니다.
- 보안문자 정답은 서버 메모리에만 존재하고 PNG로 표시합니다. 오답 5회 시 대기열부터 다시 진행합니다.
- 현재 탭을 유지하며 새로고침할 수 있습니다. 상단 메뉴로 나가면 취소 확인을 제공합니다. 닫힌 탭은 마지막 heartbeat부터 60초 후 권한이 만료됩니다.
- 다른 탭에서 같은 계정으로 예매를 시작하면 기존 탭을 유지합니다. BroadcastChannel로 복제 탭 식별자 중복을 줄이지만 실제 다중 브라우저의 세션·접속 제어는 후속 서버 설계 대상입니다.
- 확정 결과 재요청은 같은 예매를 반환합니다. 미확정의 오래된 sequence는 거부합니다.
- UI의 시안 날짜는 표시용 고정 데이터이며 기본적으로 예매 가능합니다. 서버의 개발용 오픈 시간 설정으로 시작 전 상태를 재현합니다.
- 실제 결제, 소셜 로그인, 회원가입, 추가 인증, 봇 판정은 없습니다.

## 개발용 시나리오

페이지 아래 **개발 시나리오**를 펼치세요. 기본적으로 DEBUG에서만 활성화됩니다. `SHOW_SCENARIOS=0`이면 패널·조작 API·로그 조회가 비활성화됩니다.

| 화면 | 재현 방법 |
|---|---|
| 공연 상세 | 30초 뒤 오픈 / 지금 오픈 |
| 대기열 | 즉시 입장, 연결 끊김, 입장 만료 |
| 보안문자 | 오답 4회 상태 후 틀린 답 제출 → 5회 실패; 검증 통신 오류는 다음 제출을 클라이언트에서 실패시켜 오답 불변 확인 |
| 지정석 | 좌석 선택 → 선택 좌석 먼저 판매 → 확정 → 재선택 안내 |
| 자유석 | 2명 이상 선택 → 잔여 수량 1명 → 확정 → 인원 변경 안내 |
| 선택 공통 | 동일 확정 요청 2회 / 오래된 요청 재현 |
| 공통 | 내 이벤트 확인: 현재 로그인 사용자 이벤트만 최근 100개, 화면에는 마지막 15개 |

재고 시나리오는 다른 사용자와 공유되는 모의 재고를 변경합니다. '오래된 요청'은 높은 sequence를 잘못된 선택으로 먼저 접수한 뒤 같은 sequence를 재전송하여 거부를 확인합니다. 실제 네트워크 응답 역전은 자동 테스트/후속 통합 테스트로 구분해야 합니다.

## 테스트

```powershell
docker compose --env-file .env exec -e EVENT_PUBLISHER=mock -T web python manage.py check
docker compose --env-file .env exec -e EVENT_PUBLISHER=mock -T web python manage.py test web -v 2
```

시스템 검사와 핵심 회귀 테스트를 제공합니다. DB가 없는 `SimpleTestCase`로 서비스 원자성·중복 요청·오답·접근 제한·CSRF·이벤트 검증을 확인합니다. GitHub Actions도 같은 Python 이미지로 실행합니다. 워크플로 파일을 만들었지만 원격 실행은 push 후 확인해야 합니다.

개발 서버는 `--noreload` 단일 프로세스입니다. Python 코드 변경 후:

```powershell
docker compose --env-file .env restart web
```

CSS·JS·템플릿 변경은 브라우저 새로고침으로 확인합니다. 의존성 변경 시 `docker compose --env-file .env up -d --build`로 재빌드합니다.

## 모의 저장소의 한계와 초기화

- 예매·재고·대기열·보안문자·오픈시간·이벤트는 모두 서버 프로세스 메모리입니다.
- **서버 재시작 시 위 데이터가 전부 초기화됩니다.** 완료된 예매도 재시작 뒤에는 조회할 수 없습니다.
- 초기화 명령은 `docker compose --env-file .env restart web`입니다. 디스크나 실제 DB의 데이터를 삭제하지 않습니다.
- 프로세스 내부 RLock으로 확정을 직렬화합니다. 여러 프로세스·컨테이너 사이 정합성을 보장하지 않습니다.
- Django 기본 DB 인증 대신 개발 계정 검증과 서명 쿠키 세션을 사용합니다. 관계형 DB/SQLite는 추가하지 않았습니다.
- 서명 쿠키는 암호화되지 않으며 사용자 식별자만 넣습니다. 로그아웃된 쿠키의 서버 측 폐기나 실서비스 인증을 보장하지 않습니다. 실제 인증과 공유 세션은 2단계 이후 교체해야 합니다.
- 브라우저 이벤트의 이탈 수집은 best effort입니다. 브라우저 종료 시 유실될 수 있습니다.
- 개발 로그 뷰어는 메모리에 최근 1,000건을 보관합니다. Kafka 전달 완료는 별도 callback/receipt로 구분하며, receipt는 최대 2,000건/15분입니다. Kafka 데이터는 named volume에 유지됩니다. 프로세스 종료 전 미전달 이벤트의 영속 재시도와 MongoDB TTL은 아직 구현하지 않았습니다.

## 구조

```text
config/                 Django 설정, URL, ASGI
web/services.py         예매 서비스, MockRepository, 모의 공연 데이터
web/events.py           EventPublisher 계약, MockEventPublisher, 이벤트 생성
web/views.py            요청 검증·화면 렌더링·API
web/tests.py            서비스·HTTP 회귀 테스트
templates/              화면과 공통 컴포넌트
static/                 CSS, JavaScript, 공연 이미지
docs/architecture.md    필수 후속 데이터 파이프라인 설계
```

## DB별 포트 번호

### 1. DB 구성 현황

모든 Docker 실행 설정은 **저장소 루트 `.env` 하나**에서 관리합니다.
예시는 루트 `.env.example`입니다. 기존 `raw_consumer/.env`는 보관 파일이며 아래
명령에서는 읽지 않습니다. 실제 환경 파일과 `.env.backup-*`는 Git에서 제외합니다.

| 구분 | 용도 / 기본 DB | 프로젝트 / 서비스 | 내부 포트 | 같은 PC 공개 포트 |
|---|---|---|---|---|
| 시스템 | 정제·격리·집계 / `ticketguard` | `ticket-guard-workspace-db` / `mongo` | `27017` | `MONGO_HOST_PORT`, 기본 `27017` · 예: `27018` |
| 원본 | Kafka 원본 보존 / `ticketguard_raw` | `ticket-guard-raw` / `mongo-raw` | `27020` | `27020` |
| QA 자체 | 계획·정답표·실행 결과 / `ticketguard_qa` | `ticket-guard` / `qa-mongo` | `27017` | `QA_MONGO_HOST_PORT`, 기본 `27021` |

PC 포트는 각각 `mongo/compose.local.yml`, `compose.raw.local.yml`,
`qa/compose.qa-db.local.yml`을 추가할 때만 `127.0.0.1`에 공개됩니다.
시스템 DB는 관리자 앱 전용 저장소가 아니라 파이프라인 데이터를 조회하는 대상입니다.
현재 예매·재고 서비스는 메모리 저장소이므로 DB에 영속 저장된다고 가정하지 않습니다.

| 계정 설정 | 생성 위치 / 권한 | 용도 |
|---|---|---|
| `MONGO_ROOT_*` | `admin` / 관리자 | 시스템 DB 관리 |
| `MONGO_WRITER_*` | `MONGO_DATABASE` / `readWrite` | Spark, 기본 관리자 조회·Compass |
| `RAW_MONGO_ROOT_*` | `admin` / 관리자 | 원본 DB 관리 |
| `RAW_MONGO_WRITER_*` | `RAW_MONGO_DATABASE` / `readWrite` | 원본 적재·Compass |
| `QA_MONGO_ROOT_*` | `admin` / 관리자 | QA DB 관리 |
| `QA_MONGO_USERNAME/PASSWORD` | `QA_MONGO_DATABASE` / `readWrite` | QA 자체 데이터 저장·조회 |

별도 reader인 `MONGO_ADMIN_READER_*`, `RAW_MONGO_READER_*`는 **선택 사항**입니다.
기본 writer 설치에서는 두 값을 모두 비우고 reader 검사를 실행하지 않습니다.
계정 생성은 **빈 볼륨의 최초 실행 때만** 적용됩니다. 환경 파일 변경·컨테이너
재시작만으로 기존 DB 계정이나 비밀번호가 바뀌지는 않습니다.

### 2. 최초 DB 설정 명령

Windows PowerShell의 같은 창에서 저장소 루트를 작업 위치로 사용합니다.
각 명령 직후 `$LASTEXITCODE`가 `0`인지 확인하고 오류가 나면 다음 단계로 넘어가지 않습니다.

**환경 파일 준비**

Docker Desktop의 Linux containers 엔진을 실행합니다.

```powershell
cd C:\workspace\Ticket_Guard
docker version
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Server 정보까지 출력되어야 합니다. 기존 환경 파일은 덮어쓰지 않습니다.
루트 `.env`에서 `CHANGE_ME` 값을 교체하고 아래 항목을 준비합니다.

- 시스템: `MONGO_ROOT_*`, `MONGO_WRITER_*`, `MONGO_DATABASE`, `MONGO_HOST_PORT`
- 원본: `RAW_MONGO_ROOT_*`, `RAW_MONGO_WRITER_*`, `RAW_MONGO_DATABASE`, `RAW_SOURCE_ID`
- 토픽: `KAFKA_EVENTS_TOPIC`과 `RAW_KAFKA_TOPIC` 일치
- 네트워크: 기본 `RAW_KAFKA_NETWORK=ticket-guard_default`
- QA 자체 DB: `QA_MONGO_ROOT_*`, `QA_MONGO_USERNAME`, `QA_MONGO_PASSWORD`, `QA_MONGO_DATABASE`
- 웹 관리자: `DEMO_ADMIN_USERNAME`, `DEMO_ADMIN_PASSWORD`
- 관리자 조회: `TICKET_GUARD_ADMIN_MONGO_URI`, `TICKET_GUARD_ADMIN_MONGO_NETWORK`

기본 관리자 URI에는 기존 writer 계정을 지정합니다. URI는 계정을 새로 만들지 않습니다.

```text
mongodb://<URL인코딩한_writer사용자명>:<URL인코딩한_writer비밀번호>@ticket-guard-workspace-db-mongo-1:27017/<MONGO_DATABASE>?authSource=<MONGO_DATABASE>
```

꺾쇠를 실제 값으로 교체합니다. 계정 생성 변수에는 원래 비밀번호를, URI에는
URL 인코딩한 값을 사용합니다. 각 DB의 root와 writer 사용자명은 달라야 합니다.
QA DB URI는 Compose가 구성하므로 QA 비밀번호는 현재 안내대로 영문·숫자를 사용합니다.
동일한 키가 PowerShell 환경 변수에 있으면 `.env`보다 우선합니다.

**명령에 사용할 파일 조합 선언**

```powershell
$systemDbArgs = @(
    "--env-file", ".env",
    "-p", "ticket-guard-workspace-db",
    "-f", "compose.yml",
    "-f", "mongo/compose.local.yml",
    "--profile", "mongo"
)
$rawArgs = @(
    "--env-file", ".env",
    "-f", "compose.raw.yml",
    "-f", "compose.raw.local.yml"
)
$teamArgs = @(
    "--env-file", ".env",
    "-f", "compose.yml",
    "-f", "compose.gateway.yml",
    "-f", "qa/compose.qa-db.yml",
    "-f", "qa/compose.qa-db.local.yml"
)
$sparkArgs = @(
    "--env-file", ".env",
    "-p", "ticket-guard-workspace-pipeline",
    "-f", "compose.yml",
    "--profile", "spark"
)
docker compose @systemDbArgs config --quiet
docker compose @rawArgs config --quiet
docker compose @teamArgs config --quiet
```

출력 없이 종료 코드가 `0`이면 문법 검사를 통과했습니다. 기존 DB 인증까지
검사한 것은 아닙니다. 비밀값 노출을 피하려면 전체 `config` 대신 `config --quiet`를 사용합니다.

**시스템 DB 실행·writer 검사**

```powershell
docker compose @systemDbArgs up -d --wait mongo
docker compose @systemDbArgs exec -T -e MONGO_VERIFY_ROLE=writer mongo mongosh --quiet --norc /opt/mongo/verify.js
```

`writer: authentication, ping, roles, collection, _id index OK`이면 성공입니다.
최초 설치의 `documents=0`은 정상입니다. 실패하면
`docker compose @systemDbArgs logs --tail 50 mongo`를 확인합니다.

**원본 DB 실행·writer 검사**

```powershell
docker compose @rawArgs up -d --no-deps --wait mongo-raw
docker compose @rawArgs exec -T mongo-raw mongosh --quiet --norc --port 27020 /opt/raw/verify.js
```

`raw_events`와 종류별 컬렉션 9개의 건수·인덱스가 출력되고 종료 코드가 `0`이면
성공입니다. 기본 설치에는 reader가 필요하지 않습니다. 실패하면
`docker compose @rawArgs logs --tail 50 mongo-raw`를 확인합니다.

**웹·Kafka·QA·대시보드 실행**

```powershell
docker compose @teamArgs build web qa-dashboard admin-dashboard
docker compose @rawArgs build raw-consumer
docker compose @teamArgs up -d --wait
docker compose @teamArgs ps -a
docker compose @teamArgs exec -T gateway nginx -t
```

QA 이미지의 Chromium 설치에는 시간이 걸릴 수 있습니다. `kafka-init`은
`Exited (0)`이면 정상이고 나머지는 실행 상태를 확인합니다. nginx는
`test is successful`을 확인합니다. 오류가 나면 아래 로그를 봅니다.

```powershell
docker compose @teamArgs logs --tail 50 kafka kafka-init web qa-mongo qa-dashboard admin-dashboard gateway
```

**원본 적재기 실행·실제 데이터 확인**

```powershell
docker compose @rawArgs up -d raw-consumer
docker compose @rawArgs ps -a
docker compose @rawArgs logs --since 2m raw-consumer
```

`raw_consumer started`는 DB 연결 후 시작한 기록입니다. 브라우저에서
`http://127.0.0.1:8000`에 접속해 로그인·검색·공연 선택 등을 수행합니다.
`batch_saved`와 원본 컬렉션 문서 증가를 함께 확인합니다. 과거 `failed`와 최신
`started`가 함께 있으면 시각과 현재 상태를 구분합니다. 새 이벤트가 없으면
저장 로그가 없을 수 있습니다.

**선택: 시스템 DB 정제·집계 데이터**

```powershell
docker compose @sparkArgs build spark
docker compose @sparkArgs up -d --no-deps spark
docker compose @sparkArgs logs --tail 50 spark
```

Spark는 원본 적재기와 별도로 Kafka를 처리합니다. `clean_events`,
`quarantine_events`, `event_metrics`는 파이프라인이 실제 처리한 뒤 확인합니다.

### 3. MongoDB Compass 접속

고급 연결 옵션의 인증 탭에서 루트 `.env`의 값을 입력합니다.

| DB | 같은 PC 주소 | 사용자명 | 비밀번호 | 인증 DB |
|---|---|---|---|---|
| 시스템 | `127.0.0.1:<MONGO_HOST_PORT>` | `MONGO_WRITER_USERNAME` | `MONGO_WRITER_PASSWORD` | `MONGO_DATABASE`, 기본 `ticketguard` |
| 원본 | `127.0.0.1:27020` | `RAW_MONGO_WRITER_USERNAME` | `RAW_MONGO_WRITER_PASSWORD` | `RAW_MONGO_DATABASE`, 기본 `ticketguard_raw` |
| QA 자체 | `127.0.0.1:<QA_MONGO_HOST_PORT>` | `QA_MONGO_USERNAME` | `QA_MONGO_PASSWORD` | `QA_MONGO_DATABASE`, 기본 `ticketguard_qa` |

root 계정의 인증 DB는 `admin`입니다. 원본 `http_events`, `auth_events`,
`behavior_events` 등에서 Documents를 새로고침하고 아래 조건을 사용합니다.

```javascript
// Filter (실제 토픽으로 지정)
{topic: "ticketguard.events.v1"}
// Sort
{ingestedAt: -1}
```

시스템 DB의 `raw_events`는 원본 적재기의 목적지가 아닙니다. 원본 적재기는 별도
`ticketguard_raw`의 종류별 컬렉션에 저장합니다. QA DB는 시험 전에는 기록이 없을 수 있습니다.
Docker 내부에서는 서비스·컨테이너 호스트와 내부 포트를 사용합니다.
다른 PC의 `localhost`는 그 PC 자신입니다. 시스템 DB의 팀 내부망 공개에는
선택적 `mongo/compose.lan.yml`과 서버 LAN IP를 사용합니다. 원본 원격 조회와
AWS는 SSH 터널·VPC 등 허용된 접근 경로를 준비하고 DB를 인터넷에 공개하지 않습니다.

### 4. 선택: 별도 읽기 계정과 QA 외부 DB 검증

QA 자체 DB 저장은 기본 실행에 포함됩니다. QA가 시스템·원본 DB를 읽어 검증하는
기능은 별도이며 QA 전용 원본 DB를 만드는 것이 아닙니다. 이 기능에 필요한
reader 계정·URI·네트워크가 없다면 다음 명령을 실행하지 않습니다.

`MONGO_ADMIN_READER_*`, `RAW_MONGO_READER_*`를 각각 둘 다 설정하면 빈 DB에서
자동 생성합니다. 기존 볼륨에는 유효한 관리자 인증으로 `/opt/mongo/setup-reader.js`,
`/opt/raw/setup-reader.js`를 실행하며 기존 비밀번호·권한을 임의로 바꾸지 않습니다.
설정·검사 방법은 [DB 연결 문서](docs/mongodb.md)를 참고합니다.

루트 `.env`의 `TICKET_GUARD_QA_SYSTEM_MONGO_URI`,
`TICKET_GUARD_QA_SYSTEM_RAW_MONGO_URI`는 해당 읽기 계정을 지정합니다.
`TICKET_GUARD_QA_SYSTEM_RAW_SOURCE_ID`는 같은 파일의 `RAW_SOURCE_ID`와 일치시킵니다.

```powershell
$qaDbArgs = $teamArgs + @(
    "-f", "qa/compose.qa-live.yml",
    "-f", "compose.qa-db-access.yml"
)
docker compose @qaDbArgs config --quiet
docker compose @qaDbArgs run --rm --no-deps --entrypoint python qa-dashboard /opt/ticketguard/verify-qa-connections.py
```

두 DB 모두 `authentication, read-only role and query OK`여야 합니다.
일치하는 출처 문서가 없다면 빈 DB와 출처 설정 불일치를 별도로 확인합니다.
성공 후 `docker compose @qaDbArgs up -d --no-deps qa-dashboard`로 반영합니다.
기본 `$teamArgs`에는 검사 파일이 마운트되지 않으므로 이 검사 명령도 생략합니다.

### 5. 재시작·초기화·문제 해결

새 PowerShell 창에서는 인수 배열부터 다시 선언합니다. 환경 파일 통합만으로
DB를 재생성할 필요는 없습니다. 일반 재시작은 기존 계정·데이터를 유지합니다.

```powershell
docker compose @systemDbArgs restart mongo
docker compose @rawArgs restart mongo-raw
docker compose @teamArgs restart
docker compose @rawArgs up -d raw-consumer
```

환경 변수 변경을 반영할 때는 필요한 서비스만 `up -d --no-deps <서비스>`로 갱신합니다.
단순 `restart`는 환경 변수를 갱신하지 않습니다. 컨테이너는 실행 인스턴스,
이미지는 실행 재료, 볼륨은 DB·Kafka 저장 데이터입니다. 이미지 삭제·재빌드만으로
볼륨의 계정·데이터가 초기화되지 않습니다.

**데이터까지 버리고 최초 설치를 다시 검증할 때만** 아래를 직접 실행합니다.
지정한 TicketGuard 프로젝트의 DB·QA 기록·Kafka 데이터·Spark 체크포인트가 삭제됩니다.

```powershell
docker compose @sparkArgs down --volumes --remove-orphans
docker compose @rawArgs down --volumes --remove-orphans
# 선택적 QA 연결을 사용했다면 해당 조합을 먼저 종료
# docker compose @qaDbArgs down --volumes --remove-orphans
docker compose @teamArgs --profile mongo down --volumes --remove-orphans
docker compose @systemDbArgs down --volumes --remove-orphans
```

일반 실행에 이 삭제 명령은 필요하지 않습니다.

| 증상 | 확인 사항 |
|---|---|
| required variable | 루트 `.env`의 해당 키·값·저장 여부와 `--env-file .env` |
| 인증 실패 | 계정·비밀번호·인증 DB 일치. `.env`만 바꿔도 기존 계정은 그대로임 |
| 연결 거부 | DB 실행, PC 공개 포트와 접속한 컴퓨터의 주소 |
| unhealthy·재시작 반복 | DB 로그의 필수 설정 누락·placeholder·인증 실패 |
| ServerSelectionTimeoutError | 원본 DB 존재·준비 상태, 내부 `mongo-raw:27020`, 공유 네트워크 |
| 검사 파일 없음 | 선택적 `compose.qa-db-access.yml`을 포함했는지 확인. 기본 설치에서는 검사 생략 |
| 관리자 DB 조회 실패 | 관리자 URI의 실제 생성 계정·DB·authSource·DB 네트워크 |

이 세션에서 writer 인증·Compass·원본 적재는 사용자 확인했습니다.
환경 파일 통합·작업본 복원은 값 보존과 Compose 문법만 확인하며 실제 서비스를
재설치하지 않습니다. 실제 AWS 배포·운영 보안·여러 서버 연결은 미검증입니다.

## 개발 환경과 운영 환경

현재 Compose는 로컬 개발 전용이며 127.0.0.1에만 포트를 노출합니다. 운영에서는 Django runserver와 모의 저장소를 사용하면 안 됩니다. 별도 운영 설정, WSGI/ASGI 서버, TLS, 정적 파일 배포, 실제 인증·공유 상태 저장소, 권한·모니터링 구성이 필요합니다. DEBUG=0일 때 안전한 SECRET_KEY가 없으면 기동을 거부합니다. HTTPS용 secure cookie를 켭니다. 이 설정만으로 운영 배포가 준비되었다는 의미는 아닙니다.

## GitHub

기존 remote `https://github.com/seoloo/Ticket_Guard.git`을 유지합니다. 원격 push와 PR 생성은 수행하지 않습니다. 팀원은 저장소를 clone한 뒤 같은 Compose 명령으로 실행할 수 있습니다. 소스·이미지 자산은 공유되지만 실행 중 메모리 데이터는 공유되지 않습니다.

## 필수 후속 작업

1. 완료: Python 3.13.15 기반 실제 Kafka 발행·Consumer 검증. [구현·검증 내역](docs/kafka.md).
2. Kafka 소비 → PySpark Structured Streaming 검증/정규화/집계.
3. MongoDB 예매·재고 저장과 이벤트 적재, TTL/인덱스.
4. checkpoint와 장애 재처리, 전체 Docker 통합 검증, 다중 노드 별도 검증.

상세 기준은 [후속 아키텍처](docs/architecture.md)를 참고하세요.

