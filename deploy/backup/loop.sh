#!/bin/sh
# Расписание: каждый день в BACKUP_TIME (по умолчанию 02:00) — резервная копия;
# по воскресеньям после неё — проверка восстановления. Сразу после запуска тоже
# делается копия, если сегодня её ещё не было (сервер могли выключить ночью).
. "$(dirname "$0")/common.sh"
at="${BACKUP_TIME:-02:00}"
mkdir -p "$BACKUP_DIR"
done_file="$BACKUP_DIR/.last-run"
run() {
    "$(dirname "$0")/backup.sh" || true
    if [ "$(date +%u)" = "7" ] || [ ! -f "$BACKUP_DIR/.restore-checked" ]; then
        "$(dirname "$0")/check-restore.sh" && touch "$BACKUP_DIR/.restore-checked" || true
    fi
    date +%Y-%m-%d > "$done_file"
}
echo "Резервное копирование: каждый день в $at, хранится $KEEP_DAYS дней, папка $BACKUP_DIR"
until pg_isready -q; do sleep 3; done
[ "$(cat "$done_file" 2>/dev/null)" = "$(date +%Y-%m-%d)" ] || run
while true; do
    if [ "$(date +%H:%M)" = "$at" ] && [ "$(cat "$done_file" 2>/dev/null)" != "$(date +%Y-%m-%d)" ]; then
        run
    fi
    sleep 30
done
