"""Настройки проекта.

Один файл настроек на все окружения: различия задаются переменными окружения
(см. .env.example в корне репозитория). Так проще (KISS), чем base/dev/prod.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Модули системы. Порядок совпадает с уровнями из docs/PROJECT_PLAN.md (раздел 4.2):
# ядро → основа → операции → надстройки.
PROJECT_APPS = [
    "core",
    "clients",
    "catalog",
    "staff",
    "scheduling",
    "medical",
    "billing",
    "inventory",
    "cash",
    "inpatient",
    "reminders",
    "sync",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "simple_history",
    "django_q",
    *PROJECT_APPS,
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.context.CurrentUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# Учётная запись сотрудника (ADR-022).
AUTH_USER_MODEL = "core.User"

# ПИН-код для подтверждения операций (ADR-014): после N неверных попыток — блокировка.
PIN_MAX_ATTEMPTS = 5
PIN_LOCK_MINUTES = 15

# Код узла: локальный сервер клиники, облако… Пишется в каждую запись и в номера документов
# (ADR-002, ADR-012). Латиница и цифры, коротко.
NODE_ID = os.environ.get("NODE_ID", "K1")
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "vetclinic"),
        "USER": os.environ.get("POSTGRES_USER", "vetclinic"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "vetclinic"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Язык и время (ADR-011: время всегда с часовым поясом).
LANGUAGE_CODE = "ru"
TIME_ZONE = os.environ.get("TIME_ZONE", "Europe/Moscow")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

# Максимальный размер прикрепляемого файла (сканы, снимки, PDF).
ATTACHMENT_MAX_MB = int(os.environ.get("ATTACHMENT_MAX_MB", "25"))

# Папка резервных копий: система читает из неё статус (backup.json, restore_check.json),
# который пишет контейнер backup (deploy/backup), и показывает его на главной.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))
# Копия старше этого срока — тревога на главной.
BACKUP_MAX_AGE_HOURS = int(os.environ.get("BACKUP_MAX_AGE_HOURS", "36"))

# Продажа в минус: счёт выполняется, даже если товара по учёту не хватает (решение клиники).
# Недостающее списывается с последней партии (её цена — себестоимость), остаток уходит
# в минус и закрывается следующим приходом (ADR-009).
ALLOW_NEGATIVE_STOCK = os.environ.get("ALLOW_NEGATIVE_STOCK", "1") == "1"

# Напоминания о профилактике — за сколько дней до срока попадать в список обзвона.
PREVENTION_REMIND_DAYS = int(os.environ.get("PREVENTION_REMIND_DAYS", "7"))
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Для собственных моделей ключи будут UUID (ADR-002, этап 1);
# это значение — только для сторонних приложений.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Права по ролям для каждого API (ADR-013). Открытые исключения объявляются явно.
    "DEFAULT_PERMISSION_CLASSES": [
        "core.api.permissions.ModelPermissions",
    ],
}

# Фоновые задачи (Django-Q2): очередь хранится в самой PostgreSQL — отдельный Redis не нужен.
# Задачи ставятся через core.tasks.run_in_background(), выполняет их сервис worker.
Q_CLUSTER = {
    "name": "vetclinic",
    "orm": "default",
    "workers": int(os.environ.get("TASK_WORKERS", "2")),
    "timeout": 300,  # задача дольше 5 минут прерывается
    "retry": 360,  # должно быть больше timeout
    "max_attempts": 3,
    "catch_up": False,  # пропущенные из-за выключения расписания не догоняются пачкой
    "label": "Фоновые задачи",
}
