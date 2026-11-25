#!/bin/sh
# Сертификат для локальной сети клиники. Своего центра сертификации у клиники нет,
# поэтому делаем самоподписанный: он шифрует связь так же, браузер лишь один раз
# попросит подтвердить его на каждом рабочем месте.
#
# Сертификат лежит в томе и переживает обновления: иначе после каждого
# prod-update браузеры снова ругались бы на «новый» сертификат.
set -e

CERT_DIR=/certs
CERT="$CERT_DIR/server.crt"
KEY="$CERT_DIR/server.key"
HOST="${SERVER_NAME:-192.168.1.91}"

if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
    echo "Создаю сертификат для $HOST (10 лет)…"
    mkdir -p "$CERT_DIR"
    openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
        -keyout "$KEY" -out "$CERT" \
        -subj "/C=KG/L=Bishkek/O=VetClinic/CN=$HOST" \
        -addext "subjectAltName=IP:$HOST,DNS:$HOST,DNS:localhost" 2>/dev/null
    chmod 600 "$KEY"
    echo "Готово: $CERT"
fi

exec nginx -g 'daemon off;'
