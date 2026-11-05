#!/usr/bin/env bash
set -euo pipefail
for name in MONGO_INITDB_ROOT_USERNAME MONGO_INITDB_ROOT_PASSWORD MONGO_WRITER_USERNAME MONGO_WRITER_PASSWORD MONGO_INITDB_DATABASE; do
  value="${!name:-}"
  if [[ -z "$value" || "$value" == CHANGE_ME* ]]; then
    echo "MongoDB configuration required: $name (see docs/mongodb.md)" >&2
    exit 1
  fi
done
if [[ "$MONGO_INITDB_ROOT_USERNAME" == "$MONGO_WRITER_USERNAME" || "$MONGO_INITDB_ROOT_PASSWORD" == "$MONGO_WRITER_PASSWORD" ]]; then
  echo 'MongoDB administrator and writer must have distinct usernames and passwords.' >&2
  exit 1
fi
if [[ ! "$MONGO_INITDB_DATABASE" =~ ^[a-zA-Z][a-zA-Z0-9_-]*$ || "$MONGO_INITDB_DATABASE" =~ ^(admin|local|config)$ ]]; then
  echo 'MongoDB application database name is invalid or reserved.' >&2
  exit 1
fi
exec /usr/local/bin/docker-entrypoint.sh "$@"
