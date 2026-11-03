FROM python:3.13.15-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /qa
COPY . .
RUN python -m pip install --no-cache-dir -e ".[dashboard]"

# 8800 · 팀 대시보드 8000과 겹치지 않게 · AGENTS.md 4장
EXPOSE 8800
CMD ["ticket-guard-qa", "dashboard"]
