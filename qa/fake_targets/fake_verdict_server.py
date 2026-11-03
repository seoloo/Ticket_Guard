"""가짜 판정 서버 · 포트 8801 · 가짜 대상을 HTTP로 띄워 live 코드 경로 점검 · AGENTS.md 4장"""
from fastapi import FastAPI

from ticket_guard_qa.system_targets.fake_system import FIXED_SESSION_VERDICTS

FAKE_VERDICT_SERVER_PORT = 8801

app = FastAPI(title="가짜 판정 서버")


@app.get("/health/")
def check_health() -> dict[str, str]:
    return {"status": "ok", "mode": "fake-verdict"}


@app.get("/verdicts")
def list_session_verdicts() -> dict[str, str]:
    return {key: stage.value for key, stage in FIXED_SESSION_VERDICTS.items()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=FAKE_VERDICT_SERVER_PORT)
