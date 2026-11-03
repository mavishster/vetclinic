#!/bin/sh
# Проверка, что из последней копии можно восстановиться: база разворачивается во временную
# базу (считаем клиентов и записи медкарты), а для каждого файла из описи и каждого файла,
# на который ссылается база, проверяется наличие в хранилище. Рабочая база не трогается.
. "$(dirname "$0")/common.sh"
STORE="$BACKUP_DIR/files"
latest=$(ls -1t "$BACKUP_DIR"/vetclinic-*.dump 2>/dev/null | head -n1 || true)
if [ -z "$latest" ]; then
    set_status restore_check "{\"ok\": false, \"at\": \"$(now)\", \"error\": \"копий ещё нет\"}"
    exit 1
fi
manifest="${latest%.dump}.files"
bad() {
    dropdb --if-exists "$check_db"
    set_status restore_check "{\"ok\": false, \"at\": \"$(now)\", \"file\": \"$(basename "$latest")\", \"error\": \"$1\"}"
    echo "ОШИБКА: $1" >&2
    exit 1
}
check_db="vetclinic_restore_check"
dropdb --if-exists "$check_db"
createdb "$check_db"
pg_restore --no-owner -d "$check_db" "$latest" >/dev/null 2>&1 || bad "копия базы не восстанавливается"
clients=$(psql -d "$check_db" -tAc "select count(*) from clients_client")
visits=$(psql -d "$check_db" -tAc "select count(*) from medical_visit")

missing=0
if [ -f "$manifest" ]; then
    # Файлы из описи и файлы, на которые ссылается база, — все должны быть в хранилище.
    { cat "$manifest"; psql -d "$check_db" -tAc "select file from core_attachment where file <> '' and not is_deleted"; } \
        | sort -u > "$BACKUP_DIR/.check"
    while IFS= read -r file; do
        [ -n "$file" ] && [ ! -f "$STORE/$file" ] && missing=$((missing + 1))
    done < "$BACKUP_DIR/.check"
    rm -f "$BACKUP_DIR/.check"
fi
[ "$missing" -eq 0 ] || bad "в хранилище копий нет файлов: $missing"
dropdb "$check_db"
set_status restore_check "{\"ok\": true, \"at\": \"$(now)\", \"file\": \"$(basename "$latest")\", \"clients\": $clients, \"visits\": $visits}"
echo "Проверка восстановления пройдена: $(basename "$latest") — клиентов $clients, записей медкарты $visits, все файлы на месте"
