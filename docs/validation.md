<!--
[홍석환] 웹 구현 검증 기록
검증 환경과 수행한 검사, 확인 결과 및 남은 제한을 기록한다.
-->
# Phase 1 verification

Environment: Docker Desktop Linux container, official python:3.13.15-slim-trixie, Python 3.13.15, Django 5.2.18, Pillow 12.0.0. Existing compose.yml and GitHub remote retained.

## Executed

- `docker compose up -d --build`: actual image build and web container startup succeeded.
- `python manage.py check`: no issues.
- `python manage.py test web -v 2`: 20 tests passed in Docker; no SQL database created.
- Service tests cover reserved/general success, server price, 5 wrong captcha answers and reset, refresh count preservation, tab ownership, expiry/cancel/reentry, stock conflict, stale sequence, selection limits, unverified access, two competing users, open-time enforcement, event publisher failure isolation.
- HTTP tests cover login/CSRF, templates/search/direct access, actual PNG challenge without answer leakage in HTML, 100 seat buttons, history ownership, general template, client event validation/dedup/server identity, disabled developer endpoints, malformed requests.
- Real browser: demo login → discovery → detail → waiting queue, with functioning JavaScript and server API.
- Desktop and mobile visual checks: discovery, detail, queue; reserved/general selection, completion and history rendered with an isolated test-process fixture. Static fixture JavaScript was removed; these are layout checks, not a claim of full browser end-to-end interaction after verification.
- Mobile seat overflow was confined to the seat card's horizontal scroll area. Seats have 44px minimum height on mobile. Summary action is fixed at the bottom.

## Boundaries

No real CAPTCHA was automatically solved during browser QA. Server verification and the complete booking flow were exercised through automated service/HTTP tests. No full browser E2E assertion is made for captcha submission → seat interaction → completion. No physical device, screen-reader audit or cross-browser matrix was run.

Temporary static visual fixtures are removed after layout verification. Screenshots are review artifacts outside the source tree. Actual Kafka/Spark/MongoDB integration, distributed consistency, TTL, restart persistence and production readiness are not claimed. GitHub Actions was authored but has not run remotely; no push or PR was made.
