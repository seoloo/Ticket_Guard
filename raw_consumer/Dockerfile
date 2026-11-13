# [홍석환] 원본 Kafka 소비자 실행 이미지
# 전용 Python 의존성과 원본 적재 코드를 설치해 소비자 실행 환경을 구성한다.
FROM python:3.13.15-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER 65534:65534
CMD ["python", "main.py"]
