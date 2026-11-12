#!/usr/bin/env bash
# [홍석환] 시스템 MongoDB 실행 전 설정 검사
# 필수 계정·DB 환경변수를 확인하고 공식 MongoDB 실행 절차로 연결한다.
set -euo pipefail
for name in MONGO_INITDB_ROOT_USERNAME MONGO_INITDB_ROOT_PASSWORD MONGO_WRITER_USERNAME MONGO_WRITER_PASSWORD MONGO_INITDB_DATABASE; do
  value="${!name:-}"
  if [[ -z "$value" || "$value" == CHANGE_ME* ]]; then
    echo "MongoDB configuration required: $name (see docs/mongodb.md)" >&2
    exit 1
  fi
done
if [[ -n "${MONGO_ADMIN_READER_USERNAME:-}${MONGO_ADMIN_READER_PASSWORD:-}" ]]; then
  for name in MONGO_ADMIN_READER_USERNAME MONGO_ADMIN_READER_PASSWORD; do
    value="${!name:-}"
    if [[ -z "$value" || "$value" == CHANGE_ME* ]]; then
      echo "MongoDB configuration required: $name (see admin_dashboard/README.md)" >&2
      exit 1
    fi
  done
  if [[ "$MONGO_ADMIN_READER_USERNAME" == "$MONGO_INITDB_ROOT_USERNAME" || "$MONGO_ADMIN_READER_USERNAME" == "$MONGO_WRITER_USERNAME" ]]; then
    echo 'MongoDB reader must have a separate username.' >&2
    exit 1
  fi
fi
if [[ "$MONGO_INITDB_ROOT_USERNAME" == "$MONGO_WRITER_USERNAME" || "$MONGO_INITDB_ROOT_PASSWORD" == "$MONGO_WRITER_PASSWORD" ]]; then
  echo 'MongoDB administrator and writer must have distinct usernames and passwords.' >&2
  exit 1
fi
if [[ ! "$MONGO_INITDB_DATABASE" =~ ^[a-zA-Z][a-zA-Z0-9_-]*$ || "$MONGO_INITDB_DATABASE" =~ ^(admin|local|config)$ ]]; then
  echo 'MongoDB application database name is invalid or reserved.' >&2
  exit 1
fi
exec /usr/local/bin/docker-entrypoint.sh "$@"
