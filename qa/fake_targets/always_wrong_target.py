"""일부러 틀리는 대상 · 포트 8802 · 봇은 NORMAL · 사람은 HOLD · QA가 반드시 실패로 잡아야 함"""
from fastapi import FastAPI

from ticket_guard_qa.system_targets.fake_system import AlwaysWrongVerdictReader

ALWAYS_WRONG_TARGET_PORT = 8802

app = FastAPI(title="일부러 틀리는 대상")


@app.get("/health/")
def check_health() -> dict[str, str]:
    return {"status": "ok", "mode": "always-wrong"}


@app.get("/verdicts")
def list_session_verdicts() -> dict[str, str]:
    verdicts = AlwaysWrongVerdictReader().read_session_verdicts(run_id="always-wrong")
    return {key: stage.value for key, stage in verdicts.items()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=ALWAYS_WRONG_TARGET_PORT)
