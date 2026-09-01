import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── Безопасность ──────────────────────────────────────
SECRET_KEY = os.getenv(
    'DJANGO_SECRET_KEY',
    'unsafe-dev-key-change-me'
)

DEBUG = os.getenv('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        'DJANGO_ALLOWED_HOSTS',
        '127.0.0.1,localhost'
    ).split(',')
    if host.strip()
]
if not DEBUG:
    CSRF_TRUSTED_ORIGINS = [
        f'https://{host}'
        for host in ALLOWED_HOSTS
        if host not in ['localhost', '127.0.0.1']
    ]

# ─── Приложения ────────────────────────────────────────
INSTALLED_APPS = [
    # Jazzmin ПЕРВЫМ (до django.contrib.admin)
    'jazzmin',

    # Django
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Сторонние
    'social_django',       # VK OAuth

    # Наши
    'core',
]

# ─── Middleware ─────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

# ─── Шаблоны ───────────────────────────────────────────
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],  # папка templates в корне
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Для social_auth (VK)
                'social_django.context_processors.backends',
                'social_django.context_processors.login_redirect',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ─── База данных (SQLite для разработки) ───────────────
DATABASES = {
    'default': {
        'ENGINE': os.getenv(
            'DB_ENGINE',
            'django.db.backends.sqlite3'
        ),
        'NAME': os.getenv(
            'DB_NAME',
            str(BASE_DIR / 'db.sqlite3')
        ),
        'USER': os.getenv('DB_USER', ''),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', ''),
        'PORT': os.getenv('DB_PORT', ''),
    }
}


# ─── Пароли ────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
]

# ─── Локализация ───────────────────────────────────────
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True

# ─── Статика и медиа ───────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_DIRS = [
    BASE_DIR / 'static',
] if (BASE_DIR / 'static').exists() else []

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ─── Авторизация ───────────────────────────────────────
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

AUTHENTICATION_BACKENDS = [
    'social_core.backends.vk.VKOAuth2',
    'django.contrib.auth.backends.ModelBackend',
]

# ─── Jazzmin ───────────────────────────────────────────
JAZZMIN_SETTINGS = {
    "site_title": "Сердце Самбо",
    "site_header": "Сердце Самбо",
    "site_brand": "🥋 Сердце Самбо",
    "welcome_sign": "Сердце Самбо — управление",
    "copyright": "Сердце Самбо, 2026",
    "topmenu_links": [
        {"name": "Главная", "url": "admin:index"},
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "order_with_respect_to": [
        "core.Group",
        "core.Child",
        "core.Lesson",
        "core.Attendance",
        "core.Certificate",
        "core.Payment",
        "core.News",
        "core.Event",
        "auth.User",
    ],
}

JAZZMIN_UI_TWEAKS = {
    "theme": "flatly",
    "dark_mode_theme": "darkly",
}

# ═══════════════════════════════════════════════════
# ВКонтакте OAuth
# ═══════════════════════════════════════════════════
import os
from dotenv import load_dotenv
load_dotenv()

SOCIAL_AUTH_VK_OAUTH2_KEY = os.getenv('VK_APP_ID', '')
SOCIAL_AUTH_VK_OAUTH2_SECRET = os.getenv('VK_APP_SECRET', '')
SOCIAL_AUTH_VK_OAUTH2_SCOPE = ['email']

# Pipeline для создания пользователя
SOCIAL_AUTH_PIPELINE = (
    'social_core.pipeline.social_auth.social_details',
    'social_core.pipeline.social_auth.social_uid',
    'social_core.pipeline.social_auth.auth_allowed',
    'social_core.pipeline.social_auth.social_user',
    'social_core.pipeline.user.get_username',
    'social_core.pipeline.social_auth.associate_by_email',
    'core.pipeline.create_user_with_profile',  # ← наша кастомная функция
    'social_core.pipeline.social_auth.associate_user',
    'social_core.pipeline.social_auth.load_extra_data',
    'social_core.pipeline.user.user_details',
)

SOCIAL_AUTH_LOGIN_REDIRECT_URL = '/dashboard/'
SOCIAL_AUTH_LOGIN_ERROR_URL = '/login/'
SOCIAL_AUTH_VK_OAUTH2_SCOPE = ['email']

# Ключи VK (будут добавлены позже)
SOCIAL_AUTH_VK_OAUTH2_KEY = os.getenv('VK_APP_ID', '')
SOCIAL_AUTH_VK_OAUTH2_SECRET = os.getenv('VK_APP_SECRET', '')

# ═══════════════════════════════════════════════════
# Production security
# ═══════════════════════════════════════════════════

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # HTTPS-редирект будет делать Nginx
    SECURE_SSL_REDIRECT = False