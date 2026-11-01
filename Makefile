# Частые команды. Всё выполняется внутри контейнеров — на компьютере нужен только Docker.

.PHONY: up down logs shell migrate migrations superuser test lint check ping-worker \
	prod-up prod-down prod-logs prod-admin prod-update backup backup-check restore secret

up:            ## Запустить систему
	@test -f .env || cp .env.example .env
	docker compose up --build -d
	@echo "Интерфейс: http://localhost:9000   Админка: http://localhost:8000/admin"

down:          ## Остановить
	docker compose down

logs:          ## Журналы всех сервисов
	docker compose logs -f

shell:         ## Консоль Django
	docker compose exec backend python manage.py shell

migrate:       ## Применить миграции
	docker compose exec backend python manage.py migrate

migrations:    ## Создать миграции после изменения моделей
	docker compose exec backend python manage.py makemigrations

superuser: migrate  ## Создать администратора (сначала применяются миграции)
	docker compose exec backend python manage.py createsuperuser

ping-worker:   ## Проверить фоновые задачи: результат — в админке, «Фоновые задачи → Successful tasks»
	docker compose exec backend python manage.py shell -c "from core.tasks import run_in_background; run_in_background('core.tasks.ping')"
	@echo "Задача отправлена. Через пару секунд она появится в админке: Фоновые задачи → Successful tasks"

test:          ## Тесты
	docker compose exec backend pytest

lint:          ## Стиль, типы, границы модулей
	docker compose exec backend sh -c "ruff check . && ruff format --check . && mypy && lint-imports"

check: lint test  ## Все проверки (то же, что в CI)
	docker compose exec backend python manage.py makemigrations --check --dry-run

# --- Сервер клиники (docker-compose.prod.yml, см. docs/INSTALL.md) -------------------
PROD = docker compose -f docker-compose.prod.yml

prod-up:       ## Сервер: собрать и запустить (первый раз — создаст .env из примера и остановится)
	@test -f .env || (cp .env.prod.example .env && echo "Создан .env — заполните его (пароль базы, make secret) и запустите make prod-up ещё раз" && false)
	$(PROD) up --build -d
	@echo "Система: http://localhost  (из клиники — http://имя-или-IP-сервера)"

prod-down:     ## Сервер: остановить (данные сохраняются)
	$(PROD) down

prod-logs:     ## Сервер: журналы
	$(PROD) logs -f --tail=200

prod-admin:    ## Сервер: создать администратора
	$(PROD) exec backend python manage.py createsuperuser

prod-update:   ## Сервер: обновить после git pull (копия → сборка → перезапуск)
	$(PROD) exec backup sh /scripts/backup.sh
	$(PROD) up --build -d

backup:        ## Сервер: сделать резервную копию сейчас
	$(PROD) exec backup sh /scripts/backup.sh

backup-check:  ## Сервер: проверить, что из последней копии можно восстановиться
	$(PROD) exec backup sh /scripts/check-restore.sh

restore:       ## Сервер: восстановить из копии (make restore FILE=vetclinic-2026-11-01_0200.dump)
	@test -n "$(FILE)" || (echo "Укажите файл: make restore FILE=vetclinic-…dump (список: ls backups)" && false)
	@echo "ВНИМАНИЕ: всё, что внесено после этой копии, пропадёт. Через 10 секунд начну (Ctrl+C — отмена)…" && sleep 10
	$(PROD) stop backend worker
	$(PROD) exec backup sh /scripts/restore.sh "$(FILE)"
	$(PROD) start backend worker

secret:        ## Сгенерировать ключ для DJANGO_SECRET_KEY
	@python3 -c "import secrets; print(secrets.token_urlsafe(50))" 2>/dev/null || docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(50))"
