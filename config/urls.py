from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # OAuth (ВКонтакте) отключён — URL убран, чтобы /oauth/... отдавал 404.
    # Приложение social_django оставлено в INSTALLED_APPS (таблицы в БД
    # нетронуты, миграции не требуются).
    path('', include('core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )