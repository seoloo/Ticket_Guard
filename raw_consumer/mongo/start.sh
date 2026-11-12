#!/usr/bin/env bash
# [홍석환] 원본 MongoDB 실행 전 설정 검사
# 필수 계정·DB 환경변수를 확인한 뒤 공식 MongoDB 실행 절차를 시작한다.
set -euo pipefail
for name in MONGO_INITDB_ROOT_USERNAME MONGO_INITDB_ROOT_PASSWORD MONGO_INITDB_DATABASE RAW_MONGO_WRITER_USERNAME RAW_MONGO_WRITER_PASSWORD RAW_MONGO_READER_USERNAME RAW_MONGO_READER_PASSWORD; do
  value="${!name:-}"
  if [[ -z "$value" || "$value" == CHANGE_ME* ]]; then
    echo "Raw MongoDB configuration required: $name (see raw_consumer/README.md)" >&2
    exit 1
  fi
done
if [[ "$MONGO_INITDB_ROOT_USERNAME" == "$RAW_MONGO_WRITER_USERNAME" || "$MONGO_INITDB_ROOT_USERNAME" == "$RAW_MONGO_READER_USERNAME" || "$RAW_MONGO_WRITER_USERNAME" == "$RAW_MONGO_READER_USERNAME" ]]; then
  echo 'Raw MongoDB root, writer and reader usernames must differ.' >&2
  exit 1
fi
if [[ ! "$MONGO_INITDB_DATABASE" =~ ^[a-zA-Z][a-zA-Z0-9_-]*$ || "$MONGO_INITDB_DATABASE" =~ ^(admin|local|config)$ ]]; then
  echo 'Raw MongoDB application database name is invalid or reserved.' >&2
  exit 1
fi
exec /usr/local/bin/docker-entrypoint.sh "$@"
