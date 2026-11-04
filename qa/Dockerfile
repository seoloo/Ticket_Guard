FROM python:3.13.15-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /qa
COPY . .
RUN python -m pip install --no-cache-dir -e ".[dashboard]"

# 컨테이너 안쪽 8000 · 밖으로는 열지 않고 팀 입구(nginx)만 접속 · AGENTS.md 4장
EXPOSE 8000
CMD ["ticket-guard-qa", "dashboard"]
