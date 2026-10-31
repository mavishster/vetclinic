FROM python:3.12-slim

# Таймаут и повторы pip — чтобы медленный интернет не ломал сборку.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

# Системные библиотеки для печатных форм в PDF (WeasyPrint) и шрифт с кириллицей.
RUN apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=5 \
       libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Этап 0 — образ для разработки (с инструментами проверок).
# Отдельный образ для сервера клиники появится на этапе 4.
# Кэш pip между сборками: скачанное не скачивается заново — ни при повторной сборке
# после обрыва связи, ни при добавлении новой библиотеки (докачивается только она).
COPY requirements.txt requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-dev.txt

COPY . .

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"]
