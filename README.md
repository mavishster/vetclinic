# Ветклиника — система управления

Локальная система для ветеринарной клиники с выгрузкой данных в облако.
План, архитектура и решения — [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md). Правила разработки — [`ENGINEERING.md`](ENGINEERING.md).

## Быстрый старт (macOS)

Нужно один раз:

1. Установить [Docker Desktop](https://www.docker.com/products/docker-desktop/) или [OrbStack](https://orbstack.dev/) и запустить его.
2. Установить git и make: `xcode-select --install`.

Запуск:

```bash
cd vetclinic
make up          # первый запуск занимает несколько минут: скачиваются образы
make superuser   # создать администратора (логин, email, пароль)
```

Открыть:

- интерфейс — http://localhost:9000 (на главной видно, работают ли сервер и база);
- админка Django — http://localhost:8000/admin;
- проверка состояния — http://localhost:8000/api/core/health/.

Остановить — `make down`. Данные базы сохраняются между запусками (том Docker `pgdata`).

## Команды

| Команда | Что делает |
|---|---|
| `make up` / `make down` | Запустить / остановить |
| `make logs` | Журналы всех сервисов |
| `make check` | Все проверки: стиль, типы, границы модулей, тесты, миграции |
| `make test` | Только тесты |
| `make migrations` / `make migrate` | Создать / применить миграции |
| `make shell` | Консоль Django |
| `make ping-worker` | Проверить фоновые задачи (результат — в админке, «Фоновые задачи») |

## Проверки перед коммитом

Один раз после клонирования:

```bash
brew install pre-commit   # или: pip install pre-commit
pre-commit install
```

Дальше стиль и форматирование проверяются при каждом `git commit`. Полные проверки — `make check` (их же запускает CI на GitHub).

## Структура

```
backend/     Django: config/ и модули core, clients, catalog, staff, scheduling,
             medical, billing, inventory, cash, sync; сервис worker выполняет
             фоновые задачи из того же кода
frontend/    Vue 3 + Quasar: src/modules/ — экраны по модулям
docs/        PROJECT_PLAN.md и записи о решениях (adr/)
```

## Сервер клиники

Сервер будет на Windows; способ запуска (Ubuntu в Hyper-V или Docker Desktop + WSL2) выбирается, когда станет известна редакция Windows и характеристики сервера (ADR-021). Инструкция появится на этапе 4.
