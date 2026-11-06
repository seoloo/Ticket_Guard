# 티켓가드 QA

티켓가드 시스템을 시험하는 자동화 QA 프로그램과 관리자용 QA 대시보드예요.
규칙은 [`AGENTS.md`](AGENTS.md), 구현 방법은 [`docs/implementation_guide.md`](docs/implementation_guide.md), 화면 명세는 [`docs/ui.md`](docs/ui.md)를 봐요.

## 실행

모든 명령은 **저장소 맨 위 폴더**(`Ticket_Guard/`)에서 실행해요.

### 처음 한 번

```bash
cp .env.example .env
```

Windows PowerShell이면 `Copy-Item .env.example .env`를 써요. `.env`가 없으면 관리자 계정이 꺼져서 QA 대시보드에 들어갈 수 없어요.

`.env`에 QA DB(PostgreSQL) 값을 추가해요. 비밀번호는 영문 · 숫자만 써요(접속 주소에 그대로 들어가요).

```text
QA_POSTGRES_DB=ticketguard_qa
QA_POSTGRES_USER=ticketguard_qa
QA_POSTGRES_PASSWORD=영문숫자비밀번호
QA_POSTGRES_HOST_PORT=15432
```

### 띄우기 · 코드 수정 반영

QA 대시보드는 코드를 이미지 안에 복사해서 돌아가요. 그래서 **화면이나 코드를 고친 뒤에는 내렸다가 다시 빌드해서 띄워야** 반영돼요.

```bash
docker compose -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml down
```

```bash
docker compose -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml up -d --build
```

- **`-f qa/compose.qa-db.yml`을 항상 같이 붙여요.** 빼고 띄우면 QA 대시보드가 PostgreSQL 대신 예전 SQLite 파일을 써서 최근 기록이 안 보여요.
- 내 PC의 DB 도구(DBeaver 등)로 QA DB를 볼 때만 `-f qa/compose.qa-db.local.yml`을 더 붙여요. `127.0.0.1:15432`로 열려요.

- 접속: `http://127.0.0.1:8000` → 관리자 계정(`.env`의 `DEMO_ADMIN_USERNAME` · `DEMO_ADMIN_PASSWORD`)으로 로그인 → `/qa/` QA 대시보드
- 밖으로 열리는 포트는 `127.0.0.1:8000`(팀 입구 nginx) 하나예요. `web` · `qa-dashboard`는 안쪽 네트워크로만 연결돼요.
- QA DB(`qa-postgres`)는 `qa-backend` 네트워크에서 `qa-dashboard`만 접속해요. 예매 웹 · Spark · 원본 적재는 접근하지 못해요.
- 브라우저에 예전 화면이 보이면 `Ctrl + F5`로 새로고침해요.

### 주의

- `down`은 컨테이너만 내려요. QA DB(Run 기록 · Ground Truth · 봇 프로필 버전)는 `qa-postgres-data` 볼륨에, 리포트 파일과 예전 SQLite 파일은 `qa-data` 볼륨에 남아요.
- 예전 SQLite 기록을 새 PostgreSQL로 옮길 때(처음 한 번 · 대상이 비어 있을 때만): `docker exec ticket-guard-qa-dashboard-1 ticket-guard-qa copy-database --source sqlite:////qa/qa_data/qa.db`
- **`docker compose down -v`는 쓰지 않아요.** `-v`는 볼륨까지 지워서 QA DB가 전부 사라져요.
- 예매 웹(Django)의 데이터는 메모리에만 있어서 `down`하면 초기화돼요.

## 테스트

```bash
cd qa
python -m pytest
```
