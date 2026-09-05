from django.apps import AppConfig
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Импорт внутри ready, чтобы избежать циклических зависимостей
        from .models import LoginHistory
        
        @receiver(user_logged_in)
        def log_user_login(sender, request, user, **kwargs):
            ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR'))
            # Если IP содержит несколько адресов (через прокси), берем первый
            if isinstance(ip, str) and ',' in ip:
                ip = ip.split(',')[0].strip()
            LoginHistory.objects.create(user=user, ip_address=ip)