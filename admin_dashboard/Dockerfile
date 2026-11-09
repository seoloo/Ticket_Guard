FROM python:3.13.15-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /admin_dashboard
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

# 팀 게이트웨이 내부 전용 · 호스트 포트 공개 금지
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "ticket_guard_admin.app:create_admin_dashboard_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
