#!/bin/sh
# Резервная копия: база (pg_dump) + файлы (сканы, снимки). Старше KEEP_DAYS — удаляются.
. "$(dirname "$0")/common.sh"
mkdir -p "$BACKUP_DIR"
name="vetclinic-$(date +%Y-%m-%d_%H%M)"
started="$(now)"
if pg_dump -Fc -f "$BACKUP_DIR/$name.dump.part" \
   && mv "$BACKUP_DIR/$name.dump.part" "$BACKUP_DIR/$name.dump" \
   && tar -czf "$BACKUP_DIR/$name-files.tar.gz" -C "$MEDIA_DIR" .; then
    size=$(du -k "$BACKUP_DIR/$name.dump" | cut -f1)
    set_status backup "{\"ok\": true, \"at\": \"$(now)\", \"started\": \"$started\", \"name\": \"$name\", \"db_kb\": $size}"
    find "$BACKUP_DIR" -maxdepth 1 -name 'vetclinic-*' -mtime "+$KEEP_DAYS" -delete
    echo "Резервная копия готова: $name (база ${size} КБ)"
else
    rm -f "$BACKUP_DIR/$name.dump.part"
    set_status backup "{\"ok\": false, \"at\": \"$(now)\", \"error\": \"не удалось создать копию — см. журнал контейнера backup\"}"
    echo "ОШИБКА резервного копирования" >&2
    exit 1
fi
