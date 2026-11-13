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

`.env`에 QA DB(MongoDB QA 전용 인스턴스) 값을 추가해요. 관리자 계정과 QA 계정은 이름 · 비밀번호를 다르게 하고, 비밀번호는 영문 · 숫자만 써요(접속 주소에 그대로 들어가요).

```text
QA_MONGO_DATABASE=ticketguard_qa
QA_MONGO_ROOT_USERNAME=qa_admin
QA_MONGO_ROOT_PASSWORD=영문숫자비밀번호1
QA_MONGO_USERNAME=qa_writer
QA_MONGO_PASSWORD=영문숫자비밀번호2
QA_MONGO_HOST_PORT=27021
```

QA 계정은 QA DB를 처음 띄울 때(빈 볼륨) 한 번 만들어져요. 나중에 값을 바꾸면 볼륨을 새로 만들어야 해서, 처음에 정해 두고 바꾸지 않아요.

### 띄우기 · 코드 수정 반영

QA 대시보드는 코드를 이미지 안에 복사해서 돌아가요. 그래서 **화면이나 코드를 고친 뒤에는 내렸다가 다시 빌드해서 띄워야** 반영돼요.

Live Run 시험 계정 · 초기화(`.env` 네 줄)와 시스템 MongoDB 먼저 띄우기는 저장소 맨 위 [README](../README.md) "QA 대시보드 실행" 1 · 2단계를 따라요.

전체 실행 (처음 · 예매 웹 등이 꺼져 있을 때)

```bash
docker compose -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml -f qa/compose.qa-live.yml up -d --build
```

QA 대시보드만 다시 빌드 (QA 코드를 받거나 고친 뒤 · 예매 웹 데이터 유지)

```bash
docker compose -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml -f qa/compose.qa-live.yml up -d --build --no-deps qa-dashboard
```

내리기

```bash
docker compose -f compose.yml -f compose.gateway.yml -f qa/compose.qa-db.yml -f qa/compose.qa-live.yml down
```

- **`-f qa/compose.qa-db.yml`을 항상 같이 붙여요.** 빼고 띄우면 QA 대시보드가 QA DB 주소를 못 받아서 "QA DB = MongoDB" 오류로 시작하지 않아요.
- **`-f qa/compose.qa-live.yml`도 같이 붙여요.** 빼면 Live Run 전 시험 데이터 초기화가 꺼져서 좌석이 쌓이고, 결과가 전부 "매진"이 돼요.
- 내 PC의 Compass로 QA DB를 볼 때만 `-f qa/compose.qa-db.local.yml`을 더 붙여요. `127.0.0.1:27021`로 열리고, QA 계정(`QA_MONGO_USERNAME`)으로 접속해요.

- 접속: `http://127.0.0.1:8000` → 관리자 계정(`.env`의 `DEMO_ADMIN_USERNAME` · `DEMO_ADMIN_PASSWORD`)으로 로그인 → `/qa/` QA 대시보드
- 밖으로 열리는 포트는 `127.0.0.1:8000`(팀 입구 nginx) 하나예요. `web` · `qa-dashboard`는 안쪽 네트워크로만 연결돼요.
- QA DB(`qa-mongo`)는 `qa-backend` 네트워크에서 `qa-dashboard`만 접속해요. 예매 웹 · Spark · 원본 적재 · 시스템 MongoDB는 접근하지 못해요.
- 브라우저에 예전 화면이 보이면 `Ctrl + F5`로 새로고침해요.

### 주의

- `down`은 컨테이너만 내려요. QA DB(Run 기록 · Ground Truth · 봇 프로필 버전)는 `qa-mongo-data` 볼륨에, 리포트 파일은 `qa-data` 볼륨에 남아요.
- **`docker compose down -v`는 쓰지 않아요.** `-v`는 볼륨까지 지워서 QA DB가 전부 사라져요.
- 예매 웹(Django)의 데이터는 메모리에만 있어서 `down`하면 초기화돼요.

## 테스트

```bash
cd qa
python -m pytest
```
