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
docker compose up -d --build
docker compose ps
```

접속: http://localhost:8000

| 개발용 계정 | 비밀번호 |
|---|---|
| ticketguard | ticketguard-demo |
| guest | ticketguard-demo |

두 계정은 예매 내역과 입장 권한이 분리되고 공연 재고는 공유됩니다. 실제 계정 체계가 아닌 개발용 로그인입니다. 외부에 배포하지 마세요.

신규 환경에서 `.env`가 없을 때만 `.env.example`을 `.env`로 복사하고 수정한 뒤 `docker compose up -d`로 재생성합니다. `.env`는 Git에서 제외됩니다. `.env.example`의 비밀번호는 공개된 데모 값입니다.

```powershell
Copy-Item .env.example .env
docker compose up -d
docker compose logs --tail 50 web
```

`compose.yml`은 기존 파일명 그대로 유지했습니다. Python **3.13.15**, Django **5.2.18**, Pillow **12.0.0**을 사용합니다. 호스트에 Python을 설치할 필요가 없습니다. 기본 Compose는 Kafka와 토픽 초기화를 함께 실행합니다. MongoDB는 별도 mongo 프로필로 추가했습니다. 같은 이름을 쓰는 이전 폴더 자원과 충돌하지 않도록 MongoDB 명령에는 `-p ticket-guard-workspace-db`를 반드시 사용합니다. 실행·초기화·검증은 [MongoDB 문서](docs/mongodb.md)를 따릅니다. Spark는 별도 `ticket-guard-workspace-pipeline` 프로젝트와 spark 프로필로 빌드·점검합니다. 실제 적재 명령은 [Spark 문서](docs/spark.md)를 먼저 확인하세요. 기존 `.env`를 복사 명령으로 덮어쓰지 마세요.

### QA 대시보드 실행 (관리자 · Live Run 포함)

관리자 로그인과 QA 대시보드(`/qa/`)는 팀 입구 `compose.gateway.yml`과 QA 파일 두 개(`qa/compose.qa-db.yml` · `qa/compose.qa-live.yml`)를 함께 붙여 실행할 때만 켜집니다. `docker compose up -d`만으로 띄우면 관리자 로그인이 꺼져 있어 "아이디 또는 비밀번호를 확인해 주세요"가 표시됩니다. 모든 명령은 저장소 맨 위 폴더에서 실행합니다.

| 파일 | 역할 |
|---|---|
| `compose.gateway.yml` | 팀 입구(127.0.0.1:8000) · 관리자 로그인 · QA 대시보드 · DB 관리자 앱 |
| `qa/compose.qa-db.yml` | QA DB(MongoDB QA 전용 인스턴스) · Run 기록 · Ground Truth · 봇 설정 |
| `qa/compose.qa-live.yml` | Live Run 설정 · Run 전 시험 데이터 초기화(좌석 · 진행 중 예매) · Kafka 읽기 |

**1. `.env` 준비 (처음 한 번)**

`.env`가 없으면 `.env.example`을 `.env`로 복사합니다. `.env`는 Git에서 제외되므로 pull로 갱신되지 않습니다. 이미 `.env`가 있으면 덮어쓰지 말고 아래 줄 중 없는 것만 추가합니다.

```powershell
Copy-Item .env.example .env
```

| 묶음 | 줄 | 없으면 |
|---|---|---|
| 관리자 계정 | `DEMO_ADMIN_USERNAME` · `DEMO_ADMIN_PASSWORD` (`.env.example`에 있음) | 관리자 로그인 실패 |
| 시스템 MongoDB 계정 | `MONGO_ROOT_*` · `MONGO_WRITER_*` 네 줄 · `CHANGE_ME_…`를 영문 · 숫자 값으로 교체 | 2단계 MongoDB 시작 실패 |
| QA DB 계정 | `QA_MONGO_*` 여섯 줄 (아래 예시) | `Set QA_MONGO_… in .env` 오류로 실행 중단 |
| Live Run 시험 계정 · 초기화 | `QA_TEST_ACCOUNT_*` · `QA_CAPTCHA_FIXED_ANSWER` · `QA_RESET_ENABLED` 네 줄 (아래 예시) | Live Run "시험 계정 부족" · "초기화 건너뜀" |

```text
QA_MONGO_DATABASE=ticketguard_qa
QA_MONGO_ROOT_USERNAME=qa_admin
QA_MONGO_ROOT_PASSWORD=영문숫자비밀번호1
QA_MONGO_USERNAME=qa_writer
QA_MONGO_PASSWORD=영문숫자비밀번호2
QA_MONGO_HOST_PORT=27021

QA_TEST_ACCOUNT_COUNT=500
QA_TEST_ACCOUNT_PASSWORD=영문숫자비밀번호3
QA_CAPTCHA_FIXED_ANSWER=QA123
QA_RESET_ENABLED=1
```

- 비밀번호는 영문 · 숫자만 씁니다. 관리자 계정과 QA 계정은 이름 · 비밀번호를 다르게 합니다.
- `QA_MONGO_*`는 QA DB를 처음 띄울 때(빈 볼륨) 계정이 만들어집니다. 나중에 바꾸면 볼륨을 새로 만들어야 하므로 처음에 정해 두고 바꾸지 않습니다.
- `QA_TEST_ACCOUNT_COUNT`는 Live Run 가상 사용자(VU) 수 이상으로 둡니다. 시험 계정 · 고정 보안문자 · 초기화는 예매 웹 `DJANGO_DEBUG=1`(기본 compose)에서만 켜지는 시험 환경 장치입니다.

**2. 시스템 MongoDB 먼저 시작 (처음 한 번 · PC를 다시 켠 뒤)**

팀 입구의 DB 관리자 앱이 시스템 MongoDB 네트워크(`ticket-guard-workspace-db_mongo-backend`)에 붙습니다. MongoDB를 먼저 띄우지 않으면 3단계가 `network … declared as external, but could not be found`로 실패합니다.

```powershell
docker compose -p ticket-guard-workspace-db -f compose.yml -f mongo/compose.local.yml --profile mongo up -d --no-deps mongo
```

**3. 전체 실행 (처음 · 예매 웹 등 다른 서비스가 꺼져 있을 때)**

```powershell
docker compose -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml -f qa/compose.qa-live.yml up -d --build
```

**4. QA 대시보드만 다시 빌드 (QA 코드를 받거나 고친 뒤)**

QA 대시보드는 코드를 이미지 안에 복사해서 실행합니다. `git pull`로 QA 코드가 바뀌면 다시 빌드해야 반영됩니다. `--no-deps`는 예매 웹 · Kafka를 다시 만들지 않아 예매 웹 메모리 데이터가 유지됩니다. 3단계로 다른 서비스가 이미 떠 있을 때 사용합니다.

```powershell
docker compose -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml -f qa/compose.qa-live.yml up -d --build --no-deps qa-dashboard
```

**5. 접속**

http://localhost:8000/login/ 에서 관리자 계정으로 로그인하면 QA 대시보드로 이동합니다. `ps` · `logs` · `down`에도 3단계와 같은 `-f` 네 개를 붙입니다. `down -v`는 QA DB 볼륨까지 지우므로 사용하지 않습니다.

| 증상 | 원인 | 확인 · 해결 |
|---|---|---|
| `network ticket-guard-workspace-db_mongo-backend … could not be found` | 시스템 MongoDB 미기동 | 2단계 실행 후 3단계 다시 실행 |
| `Set QA_MONGO_… in .env` | `.env` QA DB 여섯 줄 누락 | 1단계 예시 추가 |
| 관리자 로그인 실패 | `.env` 관리자 두 줄 누락 · `compose.gateway.yml` 누락 | `docker compose -f compose.yml -f compose.gateway.yml exec web printenv DEMO_ADMIN_USERNAME` · 출력 없으면 누락 |
| 로그인 후 `/qa/` 502 | QA 대시보드 미기동 · QA 파일 누락 · `QA_MONGO_*` 누락 | `docker compose -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml -f qa/compose.qa-live.yml logs --tail 50 qa-dashboard qa-mongo` |
| `/qa/` 접속 시 로그인 화면으로 이동 | 고객 계정 또는 로그아웃 상태 · 관리자 전용이라 정상 차단 | 관리자 계정으로 다시 로그인 |
| Live Run "시험 계정 부족" | `QA_TEST_ACCOUNT_*` 누락 · VU 수보다 계정 수가 적음 | 1단계 네 줄 확인 · `QA_TEST_ACCOUNT_COUNT` 늘린 뒤 3단계 다시 실행 |
| Live Run 진행 기록 "초기화 건너뜀 · 관리자 계정 미설정" | `qa/compose.qa-live.yml` 누락 · `QA_RESET_ENABLED=0` | 3단계 또는 4단계 명령의 `-f` 네 개 확인 |
| Live Run 결과가 전부 "매진" | 초기화 꺼진 상태에서 이전 Run이 좌석을 모두 판매 | 위 초기화 설정 확인 · 당장은 `docker restart ticket-guard-web-1` |
| 브라우저 봇(봇 C · D) 세션 `browser · 실행 환경 없음` | QA 대시보드 이미지가 Chromium 추가 전 버전 | 4단계로 다시 빌드 |

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
docker compose exec -e EVENT_PUBLISHER=mock -T web python manage.py check
docker compose exec -e EVENT_PUBLISHER=mock -T web python manage.py test web -v 2
```

시스템 검사와 핵심 회귀 테스트를 제공합니다. DB가 없는 `SimpleTestCase`로 서비스 원자성·중복 요청·오답·접근 제한·CSRF·이벤트 검증을 확인합니다. GitHub Actions도 같은 Python 이미지로 실행합니다. 워크플로 파일을 만들었지만 원격 실행은 push 후 확인해야 합니다.

개발 서버는 `--noreload` 단일 프로세스입니다. Python 코드 변경 후:

```powershell
docker compose restart web
```

CSS·JS·템플릿 변경은 브라우저 새로고침으로 확인합니다. 의존성 변경 시 `docker compose up -d --build`로 재빌드합니다.

## 모의 저장소의 한계와 초기화

- 예매·재고·대기열·보안문자·오픈시간·이벤트는 모두 서버 프로세스 메모리입니다.
- **서버 재시작 시 위 데이터가 전부 초기화됩니다.** 완료된 예매도 재시작 뒤에는 조회할 수 없습니다.
- 초기화 명령은 `docker compose restart web`입니다. 디스크나 실제 DB의 데이터를 삭제하지 않습니다.
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
원본데이터 보존용(raw): 27020
대시보드 데이터보관용: 27017
QA봇 대시보드 데이터 보관용(MongoDB · QA 전용 인스턴스): 27021 · `qa/compose.qa-db.local.yml`을 붙일 때만

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

