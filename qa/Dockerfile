FROM python:3.13.15-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TICKET_GUARD_QA_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium

# 브라우저 봇(봇 C 등) · Debian Chromium + 한글 글꼴(화면 캡처) · 코드보다 먼저 = 코드만 바뀌면 다시 받지 않음
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /qa
COPY . .
RUN python -m pip install --no-cache-dir -e ".[dashboard,browser]"

# 컨테이너 안쪽 8000 · 밖으로는 열지 않고 팀 입구(nginx)만 접속 · AGENTS.md 4장
EXPOSE 8000
CMD ["ticket-guard-qa", "dashboard"]
