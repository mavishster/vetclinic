#!/bin/sh
# Общие настройки резервного копирования (подключается из остальных скриптов).
set -eu
BACKUP_DIR="${BACKUP_DIR:-/backups}"
MEDIA_DIR="${MEDIA_DIR:-/media}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
export PGHOST="${PGHOST:-db}" PGUSER="${POSTGRES_USER:-vetclinic}" PGPASSWORD="${POSTGRES_PASSWORD:-}" \
       PGDATABASE="${POSTGRES_DB:-vetclinic}"

now() { date +"%Y-%m-%dT%H:%M:%S%z"; }

# Статус — маленькие JSON-файлы в папке копий (backup.json, restore_check.json);
# их читает система и показывает на главной. Пишем через временный файл — атомарно.
set_status() {
    _file="$1"; _json="$2"
    printf '%s\n' "$_json" > "$BACKUP_DIR/$_file.json.tmp"
    mv "$BACKUP_DIR/$_file.json.tmp" "$BACKUP_DIR/$_file.json"
}
