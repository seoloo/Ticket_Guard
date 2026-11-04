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

### 띄우기 · 코드 수정 반영

QA 대시보드는 코드를 이미지 안에 복사해서 돌아가요. 그래서 **화면이나 코드를 고친 뒤에는 내렸다가 다시 빌드해서 띄워야** 반영돼요.

```bash
docker compose down
```

```bash
docker compose -f compose.yml -f compose.gateway.yml up -d --build
```

- 접속: `http://127.0.0.1:8000` → 관리자 계정(`.env`의 `DEMO_ADMIN_USERNAME` · `DEMO_ADMIN_PASSWORD`)으로 로그인 → `/qa/` QA 대시보드
- 밖으로 열리는 포트는 `127.0.0.1:8000`(팀 입구 nginx) 하나예요. `web` · `qa-dashboard`는 안쪽 네트워크로만 연결돼요.
- 브라우저에 예전 화면이 보이면 `Ctrl + F5`로 새로고침해요.

### 주의

- `docker compose down`은 컨테이너만 내려요. QA DB(Run 기록 · Ground Truth · 봇 프로필 버전)는 `qa-data` 볼륨에 남아요.
- **`docker compose down -v`는 쓰지 않아요.** `-v`는 볼륨까지 지워서 QA DB가 전부 사라져요.
- 예매 웹(Django)의 데이터는 메모리에만 있어서 `down`하면 초기화돼요.

## 테스트

```bash
cd qa
python -m pytest
```
