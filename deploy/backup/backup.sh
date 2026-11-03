#!/bin/sh
# Резервная копия: база целиком (pg_dump) + НОВЫЕ файлы в хранилище копий.
#
# Файлы в системе не меняются (новый снимок — новый файл), поэтому каждый файл
# копируется в хранилище $BACKUP_DIR/files один раз. Для каждой копии сохраняется
# опись — список файлов на момент копии: по ней восстанавливается состояние любого дня.
# Удалённый в системе файл остаётся в хранилище, пока он есть хотя бы в одной описи
# (KEEP_DAYS дней), — на случай, если удалили по ошибке.
. "$(dirname "$0")/common.sh"
STORE="$BACKUP_DIR/files"
mkdir -p "$BACKUP_DIR" "$STORE"
name="vetclinic-$(date +%Y-%m-%d_%H%M)"
started="$(now)"

fail() {
    rm -f "$BACKUP_DIR/$name.dump.part" "$BACKUP_DIR/$name.files.part"
    set_status backup "{\"ok\": false, \"at\": \"$(now)\", \"error\": \"$1 — см. журнал контейнера backup\"}"
    echo "ОШИБКА резервного копирования: $1" >&2
    exit 1
}

# 1. База — целиком.
pg_dump -Fc -f "$BACKUP_DIR/$name.dump.part" || fail "не удалось сохранить базу"
mv "$BACKUP_DIR/$name.dump.part" "$BACKUP_DIR/$name.dump"

# 2. Файлы — только новые; опись — все файлы на этот момент.
new=0
if [ -d "$MEDIA_DIR" ]; then
    (cd "$MEDIA_DIR" && find . -type f | sed 's|^\./||' | sort) > "$BACKUP_DIR/$name.files.part" \
        || fail "не удалось составить опись файлов"
    while IFS= read -r file; do
        [ -f "$STORE/$file" ] && continue
        mkdir -p "$STORE/$(dirname "$file")"
        cp -p "$MEDIA_DIR/$file" "$STORE/$file.part" && mv "$STORE/$file.part" "$STORE/$file" \
            || fail "не удалось скопировать файл $file"
        new=$((new + 1))
    done < "$BACKUP_DIR/$name.files.part"
else
    : > "$BACKUP_DIR/$name.files.part"
fi
mv "$BACKUP_DIR/$name.files.part" "$BACKUP_DIR/$name.files"

# 3. Старые копии базы и описи — удалить; из хранилища — файлы, которых нет ни в одной описи.
find "$BACKUP_DIR" -maxdepth 1 -name 'vetclinic-*' -mtime "+$KEEP_DAYS" -delete
cat "$BACKUP_DIR"/vetclinic-*.files 2>/dev/null | sort -u > "$BACKUP_DIR/.keep"
removed=0
(cd "$STORE" && find . -type f ! -name '*.part' | sed 's|^\./||' | sort) | grep -Fxv -f "$BACKUP_DIR/.keep" \
    > "$BACKUP_DIR/.drop" || true
while IFS= read -r file; do
    rm -f "$STORE/$file" && removed=$((removed + 1))
done < "$BACKUP_DIR/.drop"
find "$STORE" -mindepth 1 -type d -empty -delete 2>/dev/null || true
rm -f "$BACKUP_DIR/.keep" "$BACKUP_DIR/.drop"

db_kb=$(du -k "$BACKUP_DIR/$name.dump" | cut -f1)
files=$(wc -l < "$BACKUP_DIR/$name.files" | tr -d ' ')
store_kb=$(du -sk "$STORE" | cut -f1)
set_status backup "{\"ok\": true, \"at\": \"$(now)\", \"started\": \"$started\", \"name\": \"$name\", \"db_kb\": $db_kb, \"files\": $files, \"new_files\": $new, \"removed_files\": $removed, \"store_kb\": $store_kb}"
echo "Резервная копия готова: $name — база ${db_kb} КБ; файлов $files, новых $new, из хранилища убрано $removed; хранилище ${store_kb} КБ"
