# Частые команды. Всё выполняется внутри контейнеров — на компьютере нужен только Docker.

.PHONY: up down logs shell migrate migrations superuser test lint check ping-worker

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
