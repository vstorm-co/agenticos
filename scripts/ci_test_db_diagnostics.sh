#!/usr/bin/env bash
# Report storage only: never inspect container environment or application rows.
set -u
container=${1:?Postgres service container ID is required}
if [[ ${CI:-} != true ]]; then
  echo 'Database diagnostics require the disposable CI service.' >&2
  exit 1
fi

# A crashed database must not hide the filesystem measurements or the test result.
report() {
  if ! timeout --kill-after=2s 10s "$@"; then
    echo "Storage diagnostic unavailable: $1" >&2
  fi
}

report df -h .
report df -i .
report docker inspect --format '{{range .Mounts}}{{println .Type .Destination}}{{end}}' "$container"
report docker exec "$container" sh -c 'df -h "$PGDATA"; df -i "$PGDATA"; du -sh "$PGDATA"; du -sh "$PGDATA/pg_wal"'
report docker exec "$container" psql -U postgres -v ON_ERROR_STOP=1 -P pager=off \
  -c "SELECT datname, pg_size_pretty(pg_database_size(oid)) AS size FROM pg_database ORDER BY pg_database_size(oid) DESC LIMIT 20" \
  -c "SELECT pg_size_pretty(COALESCE(sum(size), 0)::bigint) AS wal_size FROM pg_ls_waldir()"
