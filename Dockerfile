# [홍석환] Django 웹 실행 이미지 구성
# Python 의존성과 웹 소스를 설치하고 컨테이너 실행 환경을 준비한다.
FROM python:3.13.15-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Django 프로젝트 생성 전에도 개발 컨테이너를 유지합니다.
CMD ["sleep", "infinity"]