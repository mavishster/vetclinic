#!/bin/sh
# Восстановление ИЗ КОПИИ В РАБОЧУЮ БАЗУ. Всё, что внесено после копии, пропадёт.
# Запускается через `make restore FILE=vetclinic-…dump` — он сам остановит сервер на время.
. "$(dirname "$0")/common.sh"
file="${1:?Укажите файл копии, например vetclinic-2026-11-01_0200.dump}"
case "$file" in /*) path="$file" ;; *) path="$BACKUP_DIR/$file" ;; esac
[ -f "$path" ] || { echo "Нет файла $path" >&2; exit 1; }
echo "Восстанавливаю базу из $(basename "$path")…"
pg_restore --clean --if-exists --no-owner -d "$PGDATABASE" "$path"
files="${path%.dump}-files.tar.gz"
if [ -f "$files" ]; then
    echo "Восстанавливаю файлы из $(basename "$files")…"
    find "$MEDIA_DIR" -mindepth 1 -delete
    tar -xzf "$files" -C "$MEDIA_DIR"
fi
echo "Готово."
