# Два образа из одного файла:
#   dev  — для разработки (инструменты проверок, код монтируется с компьютера);
#   prod — для сервера клиники (только нужное для работы, код внутри образа, gunicorn).
FROM python:3.12-slim AS base

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

# --- Разработка ---------------------------------------------------------------------
FROM base AS dev
# Кэш pip между сборками: скачанное не скачивается заново — ни при повторной сборке
# после обрыва связи, ни при добавлении новой библиотеки (докачивается только она).
COPY requirements.txt requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-dev.txt
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"]

# --- Сервер клиники -----------------------------------------------------------------
FROM base AS prod
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
COPY . .
# Сервер работает не от root: при взломе процесс не получит права на весь контейнер.
RUN useradd --create-home --uid 1000 vetclinic \
    && mkdir -p /app/media /app/staticfiles /backups \
    && chown -R vetclinic /app/media /app/staticfiles
USER vetclinic
EXPOSE 8000
# Миграции → статика для админки → gunicorn (3 процесса хватает клинике на одном сервере).
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput -v0 && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120 --access-logfile -"]
