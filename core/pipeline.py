from django.contrib.auth.models import User
from .models import ParentProfile


def create_user_with_profile(strategy, details, backend, user=None, *args, **kwargs):
    """
    Создаёт пользователя и профиль родителя при первом входе через VK.
    Если пользователь с такой почтой уже есть — связывает аккаунты.
    """
    if user:
        return {'user': user}

    email = details.get('email')
    first_name = details.get('first_name', '')
    last_name = details.get('last_name', '')

    # Ищем по почте
    if email:
        try:
            existing_user = User.objects.get(email=email)
            return {'user': existing_user, 'is_new': False}
        except User.DoesNotExist:
            pass

    # Создаём нового пользователя
    vk_id = kwargs['response'].get('id', '0')
    username = f'vk_{vk_id}'

    # Проверяем уникальность username
    base_username = username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f'{base_username}_{counter}'
        counter += 1

    user = User.objects.create_user(
        username=username,
        email=email or '',
        password=User.objects.make_random_password(),
        first_name=first_name,
        last_name=last_name,
    )

    # Создаём профиль родителя (ребёнок через VK регистрироваться не будет)
    ParentProfile.objects.get_or_create(user=user)

    return {'user': user, 'is_new': True}