"""Настройки проекта.

Один файл настроек на все окружения: различия задаются переменными окружения
(см. .env.example в корне репозитория). Так проще (KISS), чем base/dev/prod.
"""

import os
import sys
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", default=False)
# В рабочем режиме без настоящего ключа сервер не запускается: со стандартным ключом
# любой, кто читал код, смог бы подделать вход под любым сотрудником.
_TESTING = "pytest" in sys.modules
if not DEBUG and not _TESTING and (SECRET_KEY.startswith("dev-only") or len(SECRET_KEY) < 40):
    raise ImproperlyConfigured(
        "Задайте DJANGO_SECRET_KEY в .env: случайная строка не короче 40 символов."
    )
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
    "laboratory",
    "reminders",
    "sync",
    "vetmanager",
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
TIME_ZONE = os.environ.get("TIME_ZONE", "Asia/Bishkek")

# Валюта клиники — в суммах на экране, в печатных формах и сообщениях.
CURRENCY = os.environ.get("CURRENCY", "сом")
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

# Ключ для приёма результатов анализов от LabService (заголовок X-Lab-Token).
# Пусто — приём выключен.
LAB_API_TOKEN = os.environ.get("LAB_API_TOKEN", "")

# С какого числа нумеровать приёмы для анализатора. Выше номеров медкарт VetManager
# (~5 500 в ноябре 2026), чтобы на время перехода номера двух систем не совпадали.
# Внимание: VetManager дойдёт до 8000 примерно за 2–3 месяца — параллельная работа
# двух систем (SEND_TO=both в LabService) должна закончиться раньше.
VISIT_LAB_CODE_START = int(os.environ.get("VISIT_LAB_CODE_START", "8000"))
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


# --- Безопасность входа и сессий ------------------------------------------------------

AUTHENTICATION_BACKENDS = ["core.auth.ThrottledModelBackend"]
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "10"))  # подряд под одним логином
LOGIN_MAX_ATTEMPTS_PER_IP = int(
    os.environ.get("LOGIN_MAX_ATTEMPTS_PER_IP", "30")
)  # с одного адреса
LOGIN_LOCK_MINUTES = int(os.environ.get("LOGIN_LOCK_MINUTES", "15"))

# Общий кэш для всех процессов сервера (счётчики неверных входов).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": os.environ.get(
            "CACHE_DIR", os.path.join(tempfile.gettempdir(), "vetclinic-cache")
        ),
    }
}

# Сессия: 12 часов без активности — и нужно войти снова (общие компьютеры на ресепшене);
# пока сотрудник работает (или планшет ждёт документы), срок продлевается сам.
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_HOURS", "12")) * 3600
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# https в клинике: USE_HTTPS=1 — куки только по защищённому соединению, перенаправление
# с http, HSTS. Включается вместе с сертификатом (см. docs/INSTALL.md).
if env_bool("USE_HTTPS", default=False):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False

# В рабочем режиме API отдаёт только JSON — без отладочных HTML-страниц и форм DRF.
if not DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = ["rest_framework.renderers.JSONRenderer"]

# Перенос из VetManager: адрес клиники и ключ REST API (только чтение их данных).
VETMANAGER_URL = os.environ.get("VETMANAGER_URL", "")
VETMANAGER_API_KEY = os.environ.get("VETMANAGER_API_KEY", "")
