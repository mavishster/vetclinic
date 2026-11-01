#!/bin/sh
# Проверка, что из последней копии можно восстановиться: разворачиваем её во временную
# базу, считаем клиентов и записи медкарты, удаляем временную базу. Рабочая база не трогается.
. "$(dirname "$0")/common.sh"
latest=$(ls -1t "$BACKUP_DIR"/vetclinic-*.dump 2>/dev/null | head -n1 || true)
if [ -z "$latest" ]; then
    set_status restore_check "{\"ok\": false, \"at\": \"$(now)\", \"error\": \"копий ещё нет\"}"
    exit 1
fi
check_db="vetclinic_restore_check"
dropdb --if-exists "$check_db"
createdb "$check_db"
if pg_restore --no-owner -d "$check_db" "$latest" >/dev/null 2>&1; then
    clients=$(psql -d "$check_db" -tAc "select count(*) from clients_client")
    visits=$(psql -d "$check_db" -tAc "select count(*) from medical_visit")
    dropdb "$check_db"
    set_status restore_check "{\"ok\": true, \"at\": \"$(now)\", \"file\": \"$(basename "$latest")\", \"clients\": $clients, \"visits\": $visits}"
    echo "Проверка восстановления пройдена: $(basename "$latest") — клиентов $clients, записей медкарты $visits"
else
    dropdb --if-exists "$check_db"
    set_status restore_check "{\"ok\": false, \"at\": \"$(now)\", \"file\": \"$(basename "$latest")\", \"error\": \"копия не восстанавливается\"}"
    echo "ОШИБКА: копия $(basename "$latest") не восстанавливается" >&2
    exit 1
fi
