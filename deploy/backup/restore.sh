#!/bin/sh
# Восстановление ИЗ КОПИИ В РАБОЧУЮ БАЗУ. Всё, что внесено после копии, пропадёт.
# Запускается через `make restore FILE=vetclinic-…dump` — он сам остановит сервер на время.
. "$(dirname "$0")/common.sh"
STORE="$BACKUP_DIR/files"
file="${1:?Укажите файл копии, например vetclinic-2026-11-01_0200.dump}"
case "$file" in /*) path="$file" ;; *) path="$BACKUP_DIR/$file" ;; esac
[ -f "$path" ] || { echo "Нет файла $path" >&2; exit 1; }
echo "Восстанавливаю базу из $(basename "$path")…"
pg_restore --clean --if-exists --no-owner -d "$PGDATABASE" "$path"

manifest="${path%.dump}.files"
legacy="${path%.dump}-files.tar.gz"
if [ -f "$manifest" ]; then
    # Файлы — из хранилища, ровно те, что были в системе на момент копии.
    echo "Восстанавливаю файлы по описи $(basename "$manifest")…"
    find "$MEDIA_DIR" -mindepth 1 -delete
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        mkdir -p "$MEDIA_DIR/$(dirname "$f")"
        cp -p "$STORE/$f" "$MEDIA_DIR/$f" || echo "Нет в хранилище: $f" >&2
    done < "$manifest"
elif [ -f "$legacy" ]; then
    # Копии старого формата — архив со всеми файлами.
    echo "Восстанавливаю файлы из архива $(basename "$legacy")…"
    find "$MEDIA_DIR" -mindepth 1 -delete
    tar -xzf "$legacy" -C "$MEDIA_DIR"
fi
echo "Готово."
