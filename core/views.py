import os
import uuid
from decimal import Decimal
from datetime import timedelta
from datetime import time as datetime_time
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Count, Exists, OuterRef
from django.db.models.functions import TruncMonth
from django.db.models import Exists, OuterRef
from django.http import HttpResponseForbidden
from datetime import time

from .models import (
    ParentProfile, TeacherProfile, Child, Group,
    Lesson, Attendance, Certificate, ScheduleSlot,
    News, Event, Payment, ChildEnrollment, ChildDiscount, EventRegistration
)
from .services.tochka import TochkaPaymentService
from .services.pricing import calculate_discounted_price
from .services.debts import settle_debts_on_payment
from .services.certificates import approve_certificate, reject_certificate


# ═══════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════

def get_parent_profile(user):
    # Если это ребёнок — не создаём parent_profile
    if hasattr(user, 'child_profile'):
        return None
    profile, _ = ParentProfile.objects.get_or_create(user=user)
    return profile

def get_teacher_profile(user):
    profile, _ = TeacherProfile.objects.get_or_create(user=user)
    return profile


def owner_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return HttpResponseForbidden('Доступ только для владельца')
        return view_func(request, *args, **kwargs)
    return wrapper


def get_user_role(user):
    """Определяет роль пользователя с приоритетом child > parent"""
    if not user.is_authenticated:
        return 'guest'
    if user.is_superuser:
        return 'owner'
    if user.is_staff:
        return 'admin'
    if hasattr(user, 'teacher_profile'):
        return 'teacher'
    # ВАЖНО: проверяем child_profile ПЕРЕД parent_profile
    if hasattr(user, 'child_profile'):
        return 'child'
    if hasattr(user, 'parent_profile'):
        return 'parent'
    return 'guest'


# ═══════════════════════════════════════════════════════
# АУТЕНТИФИКАЦИЯ
# ═══════════════════════════════════════════════════════

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        if not username or not password:
            messages.error(request, 'Заполните логин и пароль.')
            return render(request, 'login.html', {'vk_enabled': False})

        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(
                request,
                f'Добро пожаловать, {user.first_name or user.username}!'
            )
            return redirect('dashboard')
        else:
            messages.error(request, 'Неверный логин или пароль.')

    # Определяем, включён ли VK
    from django.conf import settings
    vk_enabled = bool(getattr(settings, 'SOCIAL_AUTH_VK_OAUTH2_KEY', ''))

    return render(request, 'login.html', {'vk_enabled': vk_enabled})


def register_view(request):
    """Универсальная регистрация: родитель или ребёнок"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        role = request.POST.get('role', 'parent')
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password2 = request.POST.get('password2', '')

        errors = []
        if not username:
            errors.append('Введите логин.')
        if not password:
            errors.append('Введите пароль.')
        if password != password2:
            errors.append('Пароли не совпадают.')
        if len(password) < 5:
            errors.append('Пароль должен быть не менее 5 символов.')

        from django.contrib.auth.models import User
        if User.objects.filter(username=username).exists():
            errors.append('Пользователь с таким логином уже существует.')

        if email and User.objects.filter(email=email).exists():
            errors.append('Пользователь с таким email уже существует.')

        if role == 'parent':
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            if not first_name:
                errors.append('Введите имя.')
            if not last_name:
                errors.append('Введите фамилию.')

        elif role == 'child':
            full_name = request.POST.get('full_name', '').strip()
            birth_date = request.POST.get('birth_date', '')
            if not full_name:
                errors.append('Введите ФИО.')

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'register.html', {'role': role})

        # Создаём пользователя
        if role == 'parent':
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            ParentProfile.objects.get_or_create(user=user)
        else:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=full_name.split()[0] if full_name.split() else '',
                last_name=' '.join(full_name.split()[1:]) if len(full_name.split()) > 1 else '',
            )
            Child.objects.create(
                parent=None,
                user=user,
                full_name=full_name,
                birth_date=birth_date if birth_date else None,
                is_active=True,
            )

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(
            request,
            'Регистрация успешна! Добро пожаловать в Сердце Самбо.'
        )
        return redirect('welcome')

    return render(request, 'register.html', {'role': 'parent'})


def logout_view(request):
    logout(request)
    messages.info(request, 'Вы вышли из системы.')
    return redirect('home')


# ═══════════════════════════════════════════════════════
# ДАШБОРДЫ И РОЛИ
# ═══════════════════════════════════════════════════════

def home_view(request):
    """
    Главная страница:
    - Авторизованные пользователи → редирект в свой дашборд
    - Неавторизованные (гости) → страница тарифов
    """
    # Если пользователь авторизован — отправляем в его дашборд
    if request.user.is_authenticated:
        role = get_user_role(request.user)
        
        if role == 'owner':
            return redirect('owner_dashboard')
        elif role == 'teacher':
            return redirect('teacher_dashboard')
        elif role == 'parent':
            return redirect('parent_dashboard')
        elif role == 'child':
            return redirect('child_dashboard')
        
        return redirect('dashboard')
    
    # Неавторизованные — показываем страницу тарифов
    return render(request, 'pricing.html')


@login_required
def dashboard(request):
    """Умный редирект по ролям"""
    role = get_user_role(request.user)

    if role == 'owner':
        return redirect('owner_dashboard')
    if role == 'teacher':
        return redirect('teacher_dashboard')
    if role == 'parent':
        return redirect('parent_dashboard')
    if role == 'child':
        return redirect('child_dashboard')

    return redirect('home')


def welcome_view(request):
    """Страница после регистрации"""
    if not request.user.is_authenticated:
        return redirect('login')

    # Для ребёнка
    if hasattr(request.user, 'child_profile'):
        child = request.user.child_profile
        has_groups = child.enrollments.filter(is_active=True).exists()
        if has_groups:
            return redirect('dashboard')
        return render(request, 'welcome.html')

    # Для родителя
    try:
        profile = request.user.parent_profile
        has_children = profile.children.filter(is_active=True).exists()
    except Exception:
        has_children = False

    if has_children:
        return redirect('dashboard')

    return render(request, 'welcome.html')


# ═══════════════════════════════════════════════════════
# РОДИТЕЛЬ
# ═══════════════════════════════════════════════════════
@login_required
def parent_dashboard(request):

    if hasattr(request.user, 'child_profile'):
        return redirect('child_dashboard')
    
    profile = get_parent_profile(request.user)
    children = profile.children.filter(
        is_active=True
    ).prefetch_related('enrollments__group', 'enrollments__discounts')

    today = timezone.now().date()
    month_ahead = today + timedelta(days=30)

    # Все группы детей
    group_ids = []
    for child in children:
        for enrollment in child.enrollments.filter(is_active=True):
            group_ids.append(enrollment.group.id)

    cancelled_notifications = []
    if group_ids:
        cancelled_notifications = (
            Lesson.objects
            .filter(
                group__id__in=group_ids,
                is_cancelled=True,
                date__gte=today,
                date__lte=month_ahead,
            )
            .select_related('group')
            .distinct()
            .order_by('date')
        )

    # 🔥 НОВОЕ: Ближайшие занятия всех детей родителя (на 7 дней)
    upcoming_lessons = []
    if group_ids:
        week_ahead = today + timedelta(days=7)
        lessons_qs = (
            Lesson.objects
            .filter(
                group__id__in=group_ids,
                is_cancelled=False,
                date__gte=today,
                date__lte=week_ahead,
            )
            .select_related('group', 'group__teacher')
            .order_by('date', 'start_time')
        )
        
        # Для каждого занятия определяем, кто из детей ходит
        for lesson in lessons_qs:
            # Находим детей родителя в этой группе
            children_in_group = [
                c for c in children
                if any(
                    e.group_id == lesson.group_id and e.is_active
                    for e in c.enrollments.all()
                )
            ]
            
            upcoming_lessons.append({
                'lesson': lesson,
                'children': children_in_group,
            })

    return render(request, 'parent_dashboard.html', {
        'children': children,
        'cancelled_notifications': cancelled_notifications,
        'upcoming_lessons': upcoming_lessons,
    })

@login_required
def child_detail(request, child_id):
    profile = get_parent_profile(request.user)
    child = get_object_or_404(Child, id=child_id, parent=profile)

    enrollments = child.enrollments.filter(
        is_active=True
    ).select_related('group')

    attendance_records = (
        Attendance.objects
        .filter(child=child)
        .select_related('lesson', 'enrollment__group')
        .order_by('-lesson__date')[:50]
    )

    today = timezone.now().date()
    month_ahead = today + timedelta(days=30)

    group_ids = enrollments.values_list('group_id', flat=True)
    cancelled_lessons = []
    if group_ids:
        cancelled_lessons = (
            Lesson.objects
            .filter(
                group_id__in=group_ids,
                is_cancelled=True,
                date__gte=today,
                date__lte=month_ahead,
            )
            .select_related('group')
            .order_by('date')
        )

    # Ближайшие занятия для каждой группы
    enrollments_with_prices = []
    for enrollment in enrollments:
        group = enrollment.group
        
        # Разовое занятие — фиксированная цена (без скидки)
        single_price = calculate_discounted_price(
            enrollment, group.price_per_lesson, is_single_lesson=True
        )
        
        # Абонемент на месяц — может быть со скидкой
        monthly_price = calculate_discounted_price(
            enrollment, group.price_monthly, is_single_lesson=False
        )
        
        saving = (group.price_per_lesson * group.lessons_per_month) - monthly_price['discounted_price']
        is_free = enrollment.is_free

        # Ближайшие 3 занятия этой группы
        upcoming_lessons = (
            Lesson.objects
            .filter(
                group=group,
                date__gte=today,
                is_cancelled=False,
            )
            .order_by('date', 'start_time')[:3]
        )

        enrollments_with_prices.append({
            'enrollment': enrollment,
            'single_price': single_price,
            'monthly_price': monthly_price,
            'saving': saving if saving > 0 else 0,
            'is_free': is_free,
            'lessons_per_month': group.lessons_per_month,
            'upcoming_lessons': upcoming_lessons,
        })

     
    today = timezone.now().date()
    
    # Проверяем, есть ли у записи посещаемости активная бесплатная скидка
    free_discount_exists = ChildDiscount.objects.filter(
        enrollments=OuterRef('enrollment_id'),
        is_active=True,
        discount_type='free',
        valid_from__lte=today,
        valid_until__gte=today,
    )

    debts_count = Attendance.objects.filter(
        child=child, 
        is_debt=True,
        enrollment__isnull=False
    ).annotate(
        has_free=Exists(free_discount_exists)
    ).filter(
        has_free=False # Игнорируем старые долги, если сейчас действует бесплатная скидка
    ).count()

    return render(request, 'child_detail.html', {
        'child': child,
        'enrollments_with_prices': enrollments_with_prices,
        'attendance_records': attendance_records,
        'cancelled_lessons': cancelled_lessons,
        'debts_count': debts_count,
    })


@login_required
def child_dashboard(request):
    """ЛК ребёнка — видит то же, что родитель"""
    try:
        child = request.user.child_profile
    except Exception:
        return redirect('home')

    # Рендерим тот же шаблон child_detail
    enrollments = child.enrollments.filter(
        is_active=True
    ).select_related('group')

    attendance_records = (
        Attendance.objects
        .filter(child=child)
        .select_related('lesson', 'enrollment__group')
        .order_by('-lesson__date')[:50]
    )

    today = timezone.now().date()
    month_ahead = today + timedelta(days=30)

    group_ids = enrollments.values_list('group_id', flat=True)
    cancelled_lessons = []
    if group_ids:
        cancelled_lessons = (
            Lesson.objects
            .filter(
                group_id__in=group_ids,
                is_cancelled=True,
                date__gte=today,
                date__lte=month_ahead,
            )
            .select_related('group')
            .order_by('date')
        )

    # Ближайшие занятия для каждой группы
    enrollments_with_prices = []
    for enrollment in enrollments:
        group = enrollment.group
        
        # Разовое занятие — фиксированная цена (без скидки)
        single_price = calculate_discounted_price(
            enrollment, group.price_per_lesson, is_single_lesson=True
        )
        
        # Абонемент на месяц — может быть со скидкой
        monthly_price = calculate_discounted_price(
            enrollment, group.price_monthly, is_single_lesson=False
        )
        
        saving = (group.price_per_lesson * group.lessons_per_month) - monthly_price['discounted_price']
        is_free = enrollment.is_free

        # Ближайшие 3 занятия этой группы
        upcoming_lessons = (
            Lesson.objects
            .filter(
                group=group,
                date__gte=today,
                is_cancelled=False,
            )
            .order_by('date', 'start_time')[:3]
        )

        enrollments_with_prices.append({
            'enrollment': enrollment,
            'single_price': single_price,
            'monthly_price': monthly_price,
            'saving': saving if saving > 0 else 0,
            'is_free': is_free,
            'lessons_per_month': group.lessons_per_month,
            'upcoming_lessons': upcoming_lessons,
        })

     
    today = timezone.now().date()
    
    # Проверяем, есть ли у записи посещаемости активная бесплатная скидка
    free_discount_exists = ChildDiscount.objects.filter(
        enrollments=OuterRef('enrollment_id'),
        is_active=True,
        discount_type='free',
        valid_from__lte=today,
        valid_until__gte=today,
    )

    debts_count = Attendance.objects.filter(
        child=child, 
        is_debt=True,
        enrollment__isnull=False
    ).annotate(
        has_free=Exists(free_discount_exists)
    ).filter(
        has_free=False # Игнорируем старые долги, если сейчас действует бесплатная скидка
    ).count()

    return render(request, 'child_detail.html', {
        'child': child,
        'enrollments_with_prices': enrollments_with_prices,
        'attendance_records': attendance_records,
        'cancelled_lessons': cancelled_lessons,
        'debts_count': debts_count,
        'is_child_view': True,
    })

# ═══════════════════════════════════════════════════════
# ОПЛАТА
# ═══════════════════════════════════════════════════════

@login_required
def pay_view(request):
    """Старая страница оплаты — редирект в дашборд"""
    return redirect('parent_dashboard')


@login_required
def pay_for_enrollment(request, enrollment_id, tariff_code):
    """Оплата за конкретную запись в группу (для родителя или ребёнка)"""
    
    enrollment = get_object_or_404(
        ChildEnrollment,
        id=enrollment_id,
        is_active=True,
    )
    child = enrollment.child
    group = enrollment.group
    
        # Получаем запись
    enrollment = get_object_or_404(
        ChildEnrollment,
        id=enrollment_id,
        is_active=True,
    )
    child = enrollment.child

    # Определяем профиль плательщика
    profile = None

    # Это родитель?
    if hasattr(request.user, 'parent_profile'):
        if child.parent == request.user.parent_profile:
            profile = request.user.parent_profile

    # Это сам ребёнок?
    if profile is None and hasattr(request.user, 'child_profile'):
        if request.user.child_profile == child:
            # 🔥 ИСПРАВЛЕНИЕ: если у ребёнка нет родителя, оставляем parent=None
            if child.parent:
                profile = child.parent
            else:
                profile = None  # Платёж будет без родителя

    if profile is None and not hasattr(request.user, 'child_profile'):
        messages.error(request, 'Нет доступа к оплате.')
        return redirect('dashboard')
    
    # Определяем тариф
    if tariff_code == 'single':
        base_price = group.price_per_lesson
        lessons_count = 1
        description = f'Разовое занятие для {child.full_name} ({group.name})'
    elif tariff_code == 'monthly':
        base_price = group.price_monthly
        lessons_count = group.lessons_per_month
        description = f'Абонемент на месяц для {child.full_name} ({group.name}, {group.lessons_per_month} занятий)'
    else:
        messages.error(request, 'Неверный тариф.')
        return redirect('child_detail', child_id=child.id)
    
    price_info = calculate_discounted_price(enrollment, base_price)
    amount = price_info['discounted_price']
    
    if amount <= 0:
        messages.info(
            request,
            f'Занятие для {child.full_name} в группе {group.name} бесплатное.'
        )
        return redirect('child_detail', child_id=child.id)
    
    order_id = str(uuid.uuid4())[:8]
    payment = Payment.objects.create(
        parent=profile,
        child=child,
        enrollment=enrollment,
        amount=amount,
        lessons_count=lessons_count,
        status='pending',
        method='online',
        note=description,
    )
    
    service = TochkaPaymentService()
    result = service.create_payment_link(
        amount=amount,
        description=description,
        order_id=order_id,
    )
    
    if not result['success']:
        payment.status = 'failed'
        payment.save()
        messages.error(
            request, f'Ошибка создания платежа: {result["error"]}'
        )
        return redirect('child_detail', child_id=child.id)
    
    payment.bank_payment_id = result.get('payment_id', '')
    payment.save()
    request.session['pending_payment_id'] = payment.id
    
    return redirect(result['url'])


@login_required
def payment_mock_success(request):
    payment_id = request.session.get('pending_payment_id')
    if not payment_id:
        messages.error(request, 'Платёж не найден.')
        return redirect('parent_dashboard')

    payment = get_object_or_404(Payment, id=payment_id)

    if hasattr(request.user, 'parent_profile'):
        if payment.parent != request.user.parent_profile:
            messages.error(request, 'Нет доступа к этому платежу.')
            return redirect('parent_dashboard')

    if payment.status == 'paid':
        messages.info(request, 'Платёж уже был оплачен.')
        return redirect('parent_dashboard')

    payment.status = 'paid'
    payment.paid_at = timezone.now()
    payment.save()

    # Проверяем, это платёж за занятия или за мероприятие
    if payment.event_registration:
        # Оплата за участие в мероприятии
        registration = payment.event_registration
        registration.status = 'paid'
        registration.paid_at = timezone.now()
        registration.save()
        
        messages.success(
            request,
            f'Оплата {payment.amount} ₽ прошла успешно! '
            f'{registration.child.full_name} будет участвовать в '
            f'«{registration.event.title}».'
        )
    else:
        # Оплата за занятия (старая логика)
        result = settle_debts_on_payment(payment)
        debts_msg = ''
        if result['debts_settled'] > 0:
            debts_msg = f' Погашено занятий в долг: {result["debts_settled"]}.'
        
        messages.success(
            request,
            f'Оплата {payment.amount} ₽ прошла успешно! '
            f'Зачислено занятий: {payment.lessons_count}.{debts_msg}'
        )

    if 'pending_payment_id' in request.session:
        del request.session['pending_payment_id']

    return redirect('parent_dashboard')


@login_required
def payment_success(request):
    """Возврат пользователя после оплаты"""
    payment_id = request.session.get('pending_payment_id')

    if not payment_id:
        messages.error(request, 'Платёж не найден.')
        return redirect('parent_dashboard')

    payment = get_object_or_404(Payment, id=payment_id)

    if hasattr(request.user, 'parent_profile'):
        if payment.parent != request.user.parent_profile:
            messages.error(request, 'Нет доступа к этому платежу.')
            return redirect('parent_dashboard')

    service = TochkaPaymentService()

    # В боевом режиме не доверяем просто возврату пользователя.
    # Оплата должна подтверждаться webhook'ом банка.
    if service.mode == 'production':
        if payment.status == 'paid':
            messages.success(request, 'Оплата подтверждена банком.')
        else:
            messages.info(
                request,
                'Платёж получен. Как только банк подтвердит оплату, '
                'занятия будут зачислены автоматически.'
            )

        if 'pending_payment_id' in request.session:
            del request.session['pending_payment_id']

        return redirect('parent_dashboard')

    # Для локального режима и песочницы подтверждаем сразу
    if payment.status == 'paid':
        messages.info(request, 'Платёж уже был оплачен.')
        return redirect('parent_dashboard')

    payment.status = 'paid'
    payment.paid_at = timezone.now()
    payment.save()

    if payment.event_registration:
        registration = payment.event_registration
        registration.status = 'paid'
        registration.paid_at = timezone.now()
        registration.save()

        messages.success(
            request,
            f'Оплата {payment.amount} ₽ прошла успешно!'
        )
    else:
        result = settle_debts_on_payment(payment)
        debts_msg = ''

        if result['debts_settled'] > 0:
            debts_msg = f' Погашено занятий в долг: {result["debts_settled"]}.'

        messages.success(
            request,
            f'Оплата {payment.amount} ₽ прошла успешно! '
            f'Зачислено занятий: {payment.lessons_count}.{debts_msg}'
        )

    if 'pending_payment_id' in request.session:
        del request.session['pending_payment_id']

    return redirect('parent_dashboard')


@login_required
def payment_cancel(request):
    payment_id = request.session.get('pending_payment_id')
    if payment_id:
        payment = Payment.objects.filter(id=payment_id).first()
        if payment and payment.status == 'pending':
            payment.status = 'failed'
            payment.save()
        if 'pending_payment_id' in request.session:
            del request.session['pending_payment_id']

    messages.warning(request, 'Оплата была отменена.')
    return redirect('parent_dashboard')
@login_required
def payment_mock_view(request):
    """Страница тестовой оплаты (mock-режим)"""
    payment_id = request.session.get('pending_payment_id')
    if not payment_id:
        messages.error(request, 'Платёж не найден.')
        return redirect('parent_dashboard')

    payment = get_object_or_404(Payment, id=payment_id)

    # Проверка прав
    if hasattr(request.user, 'parent_profile'):
        if payment.parent != request.user.parent_profile:
            messages.error(request, 'Нет доступа к этому платежу.')
            return redirect('parent_dashboard')

    return render(request, 'payment_mock.html', {'payment': payment})


@login_required
def payment_mock_confirm(request):
    """Подтверждение тестовой оплаты"""
    payment_id = request.session.get('pending_payment_id')
    if not payment_id:
        messages.error(request, 'Платёж не найден.')
        return redirect('parent_dashboard')

    payment = get_object_or_404(Payment, id=payment_id)

    if hasattr(request.user, 'parent_profile'):
        if payment.parent != request.user.parent_profile:
            messages.error(request, 'Нет доступа к этому платежу.')
            return redirect('parent_dashboard')

    if payment.status == 'paid':
        messages.info(request, 'Платёж уже был оплачен.')
        return redirect('parent_dashboard')

    # Подтверждаем оплату
    payment.status = 'paid'
    payment.paid_at = timezone.now()
    payment.save()

    # Обрабатываем в зависимости от типа платежа
    if payment.event_registration:
        registration = payment.event_registration
        registration.status = 'paid'
        registration.paid_at = timezone.now()
        registration.save()
        messages.success(
            request,
            f'✅ Тестовая оплата {payment.amount} ₽ прошла! '
            f'{registration.child.full_name} зарегистрирован на '
            f'«{registration.event.title}».'
        )
    else:
        result = settle_debts_on_payment(payment)
        debts_msg = ''
        if result['debts_settled'] > 0:
            debts_msg = f' Погашено в долг: {result["debts_settled"]}.'
        messages.success(
            request,
            f'✅ Тестовая оплата {payment.amount} ₽ прошла! '
            f'Зачислено занятий: {payment.lessons_count}.{debts_msg}'
        )

    if 'pending_payment_id' in request.session:
        del request.session['pending_payment_id']

    return redirect('parent_dashboard')

@login_required
def payment_history(request):
    """История платежей — для родителя и ребёнка"""
    
    # Определяем, кто смотрит историю
    is_child = hasattr(request.user, 'child_profile')
    
    # Фильтры из GET-параметров
    status = request.GET.get('status', 'all')
    period = request.GET.get('period', 'all')
    
    # Базовый запрос — зависит от роли
    if is_child:
        # Для ребёнка — показываем платежи его child_profile
        child = request.user.child_profile
        payments = (
            Payment.objects
            .filter(child=child)
            .select_related('child', 'enrollment__group', 'event_registration__event', 'parent')
            .order_by('-created_at')
        )
    else:
        # Для родителя — показываем платежи по parent_profile
        profile = get_parent_profile(request.user)
        payments = (
            Payment.objects
            .filter(parent=profile)
            .select_related('child', 'enrollment__group', 'event_registration__event')
            .order_by('-created_at')
        )
    
    # Фильтр по статусу
    if status != 'all':
        payments = payments.filter(status=status)
    
    # Фильтр по периоду
    today = timezone.now().date()
    if period == 'month':
        first_of_month = today.replace(day=1)
        payments = payments.filter(created_at__date__gte=first_of_month)
    elif period == '3months':
        three_months_ago = today - timedelta(days=90)
        payments = payments.filter(created_at__date__gte=three_months_ago)
    elif period == 'year':
        first_of_year = today.replace(month=1, day=1)
        payments = payments.filter(created_at__date__gte=first_of_year)
    
    # Статистика — тоже зависит от роли
    if is_child:
        child = request.user.child_profile
        all_payments = Payment.objects.filter(child=child)
    else:
        profile = get_parent_profile(request.user)
        all_payments = Payment.objects.filter(parent=profile)
    
    total_paid = all_payments.filter(status='paid').aggregate(
        total=Sum('amount')
    )['total'] or 0
    total_count = all_payments.filter(status='paid').count()
    
    # Общая сумма за выбранный период
    period_total = payments.filter(status='paid').aggregate(
        total=Sum('amount')
    )['total'] or 0
    
    return render(request, 'payment_history.html', {
        'payments': payments,
        'total_paid': total_paid,
        'total_count': total_count,
        'period_total': period_total,
        'current_status': status,
        'current_period': period,
        'is_child': is_child,
    })
# ═══════════════════════════════════════════════════════
# ПРЕПОДАВАТЕЛЬ
# ═══════════════════════════════════════════════════════

@login_required
def teacher_dashboard(request):
    profile = get_teacher_profile(request.user)
    groups = Group.objects.filter(teacher=profile, is_active=True)
    news = News.objects.filter(is_published=True)[:5]

    return render(request, 'teacher_dashboard.html', {
        'groups': groups,
        'news': news,
    })


@login_required
def group_lessons(request, group_id):
    profile = get_teacher_profile(request.user)
    group = get_object_or_404(Group, id=group_id, teacher=profile)

    today = timezone.now().date()

    upcoming_lessons = (
        Lesson.objects
        .filter(group=group, date__gte=today)
        .order_by('date', 'start_time')[:20]
    )
    past_lessons = (
        Lesson.objects
        .filter(group=group, date__lt=today)
        .order_by('-date', '-start_time')[:10]
    )

    return render(request, 'group_lessons.html', {
        'group': group,
        'upcoming_lessons': upcoming_lessons,
        'past_lessons': past_lessons,
        'today': today,
    })


@login_required
def attendance_sheet(request, group_id):
    return redirect('group_lessons', group_id=group_id)


@login_required
def attendance_sheet_for_lesson(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)

    profile = get_teacher_profile(request.user)
    if lesson.group.teacher != profile:
        messages.error(request, 'Нет доступа к этому занятию.')
        return redirect('teacher_dashboard')

    children = Child.objects.filter(
        enrollments__group=lesson.group,
        enrollments__is_active=True,
        is_active=True,
    ).distinct()

    existing = {
        a.child_id: a.status
        for a in Attendance.objects.filter(lesson=lesson)
    }

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_attendance':
            for child in children:
                status = request.POST.get(
                    f'status_{child.id}', 'present'
                )
                should_deduct = (status == 'absent')

                # Находим запись ребёнка в этой группе
                enrollment = ChildEnrollment.objects.filter(
                    child=child, group=lesson.group, is_active=True
                ).first()

                # Если был с 0 занятий → долг
                is_debt = False
                if status == 'present' and enrollment and enrollment.remaining_lessons <= 0:
                    if not enrollment.is_free:
                        is_debt = True

                attendance, created = Attendance.objects.get_or_create(
                    lesson=lesson,
                    child=child,
                    defaults={
                        'status': status,
                        'was_deducted': should_deduct,
                        'is_debt': is_debt,
                        'enrollment': enrollment,
                    }
                )

                if not created:
                    old_deducted = attendance.was_deducted
                    attendance.status = status
                    attendance.was_deducted = should_deduct
                    attendance.is_debt = is_debt
                    attendance.enrollment = enrollment
                    attendance.save()

                    if enrollment:
                        if should_deduct and not old_deducted:
                            enrollment.remaining_lessons = max(
                                0, enrollment.remaining_lessons - 1
                            )
                            enrollment.save()
                        elif not should_deduct and old_deducted:
                            enrollment.remaining_lessons += 1
                            enrollment.save()
                else:
                    if enrollment and should_deduct:
                        enrollment.remaining_lessons = max(
                            0, enrollment.remaining_lessons - 1
                        )
                        enrollment.save()

            messages.success(request, 'Посещаемость сохранена.')
            return redirect('group_lessons', group_id=lesson.group.id)

        if action == 'cancel_lesson':
            reason = request.POST.get('cancel_reason', '').strip()
            if not reason:
                messages.error(request, 'Укажите причину отмены.')
                return redirect(
                    'attendance_sheet_for_lesson', lesson_id=lesson.id
                )
            lesson.is_cancelled = True
            lesson.cancel_reason = reason
            lesson.save()
            messages.success(
                request, f'Занятие отменено. Причина: {reason}'
            )
            return redirect('group_lessons', group_id=lesson.group.id)

        if action == 'restore_lesson':
            lesson.is_cancelled = False
            lesson.cancel_reason = ''
            lesson.save()
            messages.success(request, 'Занятие восстановлено.')
            return redirect('group_lessons', group_id=lesson.group.id)

    return render(request, 'attendance_sheet.html', {
        'group': lesson.group,
        'children': children,
        'lesson': lesson,
        'existing': existing,
    })


# ═══════════════════════════════════════════════════════
# ВЛАДЕЛЕЦ
# ═══════════════════════════════════════════════════════

@owner_required
def owner_dashboard(request):
    today = timezone.now().date()

    total_children = Child.objects.filter(is_active=True).count()
    pending_certificates = Certificate.objects.filter(
        status='pending'
    ).count()

    # Подзапрос для бесплатных скидок
    free_discount_exists = ChildDiscount.objects.filter(
        enrollments=OuterRef('pk'),
        is_active=True,
        discount_type='free',
        valid_from__lte=today,
        valid_until__gte=today,
    )

    debtors = (
        ChildEnrollment.objects
        .filter(
            is_active=True,
            remaining_lessons__lte=0,
            child__is_active=True,
        )
        .annotate(has_free=Exists(free_discount_exists))
        .filter(has_free=False)
        .select_related('child', 'group')
    )

    first_of_month = today.replace(day=1)
    monthly_income = (
        Payment.objects
        .filter(status='paid', paid_at__date__gte=first_of_month)
        .aggregate(total=Sum('amount'))['total'] or Decimal('0')
    )

    last_month_end = first_of_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    last_month_income = (
        Payment.objects
        .filter(
            status='paid',
            paid_at__date__gte=last_month_start,
            paid_at__date__lte=last_month_end,
        )
        .aggregate(total=Sum('amount'))['total'] or Decimal('0')
    )

    all_time_income = (
        Payment.objects
        .filter(status='paid')
        .aggregate(total=Sum('amount'))['total'] or Decimal('0')
    )

    return render(request, 'owner/dashboard.html', {
        'total_children': total_children,
        'pending_certificates': pending_certificates,
        'debtors': debtors,
        'monthly_income': monthly_income,
        'last_month_income': last_month_income,
        'all_time_income': all_time_income,
    })


@owner_required
def owner_report(request):
    today = timezone.now().date()
    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    all_payments = Payment.objects.filter(
        status='paid', paid_at__isnull=False
    ).order_by('-paid_at')

    monthly = all_payments.filter(paid_at__date__gte=month_start)
    monthly_total = monthly.aggregate(t=Sum('amount'))['t'] or 0
    monthly_cash_total = (
        monthly.filter(method='cash').aggregate(t=Sum('amount'))['t'] or 0
    )
    monthly_online_total = (
        monthly.filter(method='online').aggregate(t=Sum('amount'))['t'] or 0
    )

    last_month = all_payments.filter(
        paid_at__date__gte=last_month_start,
        paid_at__date__lte=last_month_end,
    )
    last_month_total = last_month.aggregate(t=Sum('amount'))['t'] or 0

    all_time_total = all_payments.aggregate(t=Sum('amount'))['t'] or 0

    monthly_breakdown = (
        all_payments
        .annotate(month=TruncMonth('paid_at'))
        .values('month')
        .annotate(total=Sum('amount'), count=Count('id'))
        .order_by('-month')
    )

    free_discount_exists = ChildDiscount.objects.filter(
        enrollments=OuterRef('pk'),
        is_active=True,
        discount_type='free',
        valid_from__lte=today,
        valid_until__gte=today,
    )

    debtors = (
        ChildEnrollment.objects
        .filter(
            is_active=True,
            remaining_lessons__lte=0,
            child__is_active=True,
        )
        .annotate(has_free=Exists(free_discount_exists))
        .filter(has_free=False)
        .select_related('child__parent__user', 'group')
    )

    almost_debtors = (
        ChildEnrollment.objects
        .filter(
            is_active=True,
            remaining_lessons__lte=2,
            remaining_lessons__gt=0,
            child__is_active=True,
        )
        .select_related('child__parent__user', 'group')
    )

    return render(request, 'owner/report.html', {
        'monthly_total': monthly_total,
        'monthly_cash_total': monthly_cash_total,
        'monthly_online_total': monthly_online_total,
        'monthly_count': monthly.count(),
        'last_month_total': last_month_total,
        'last_month_count': last_month.count(),
        'last_month_start': last_month_start,
        'all_time_total': all_time_total,
        'all_time_count': all_payments.count(),
        'monthly_breakdown': monthly_breakdown,
        'debtors': debtors,
        'almost_debtors': almost_debtors,
        'recent_payments': all_payments[:20],
        'month_start': month_start,
    })


@owner_required
def owner_cash_payment(request):
    if request.method == 'POST':
        enrollment_id = request.POST.get('enrollment')
        tariff = request.POST.get('tariff')
        note = request.POST.get('note', '')

        enrollment = get_object_or_404(
            ChildEnrollment, id=enrollment_id, is_active=True
        )
        child = enrollment.child
        group = enrollment.group
        parent = child.parent

        

        if tariff == '1':
            amount = group.price_per_lesson
            lessons_count = 1
        elif tariff == '4':
            amount = group.price_abonement_4
            lessons_count = 4
        else:
            messages.error(request, 'Неверный тариф.')
            return redirect('owner_cash_payment')

        # Применяем скидку
        price_info = calculate_discounted_price(enrollment, amount)
        amount = price_info['discounted_price']

        payment = Payment.objects.create(
            parent=parent,
            child=child,
            enrollment=enrollment,
            amount=amount,
            lessons_count=lessons_count,
            status='paid',
            method='cash',
            note=note,
            paid_at=timezone.now(),
        )

        result = settle_debts_on_payment(payment)
        debts_msg = ''
        if result['debts_settled'] > 0:
            debts_msg = f' Погашено в долг: {result["debts_settled"]}.'

        messages.success(
            request,
            f'Оплата {amount} ₽ ({lessons_count} зан.) '
            f'за {child.full_name} зафиксирована.{debts_msg}'
        )
        return redirect('owner_cash_payment')

    enrollments = (
        ChildEnrollment.objects
        .filter(is_active=True, child__is_active=True)
        .select_related('child__parent__user', 'group')
    )
    recent_payments = (
        Payment.objects
        .filter(method='cash', status='paid')
        .order_by('-paid_at')[:20]
    )
    return render(request, 'owner/cash_payment.html', {
        'enrollments': enrollments,
        'recent_payments': recent_payments,
    })


@owner_required
def owner_certificates(request):
    if request.method == 'POST':
        certificate_id = request.POST.get('certificate_id')
        action = request.POST.get('action')

        certificate = get_object_or_404(Certificate, id=certificate_id)

        if action == 'approve':
            certificate.status = 'approved'
            certificate.reviewed_at = timezone.now()
            certificate.save()
            returned = approve_certificate(certificate)
            messages.success(
                request,
                f'Справка одобрена. Возвращено занятий: {returned}.'
            )
        elif action == 'reject':
            certificate.status = 'rejected'
            certificate.reviewed_at = timezone.now()
            certificate.save()
            rejected = reject_certificate(certificate)
            messages.success(
                request,
                f'Справка отклонена. Списано занятий: {rejected}.'
            )

        return redirect('owner_certificates')

    certificates = Certificate.objects.all().select_related(
        'child__parent__user'
    ).order_by('-uploaded_at')

    return render(request, 'owner/certificates.html', {
        'certificates': certificates,
    })


@owner_required
def owner_groups(request):
    groups = Group.objects.all().select_related('teacher')
    return render(request, 'owner/groups.html', {'groups': groups})


@owner_required
def owner_add_group(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        price_per_lesson = request.POST.get('price_per_lesson', 0)
        lessons_per_month = request.POST.get('lessons_per_month', 8)
        price_monthly = request.POST.get('price_monthly', 0)
        max_capacity = request.POST.get('max_capacity', 20)
        description = request.POST.get('description', '')
        teacher_id = request.POST.get('teacher')

        if not name:
            messages.error(request, 'Введите название группы.')
            teachers = TeacherProfile.objects.all()
            return render(request, 'owner/add_group.html', {
                'teachers': teachers,
            })

        group = Group.objects.create(
            name=name,
            price_per_lesson=(
                Decimal(price_per_lesson) if price_per_lesson else 0
            ),
            lessons_per_month=int(lessons_per_month) if lessons_per_month else 8,
            price_monthly=(
                Decimal(price_monthly) if price_monthly else 0
            ),
            max_capacity=int(max_capacity) if max_capacity else 20,
            description=description,
            is_active=True,
        )

        if teacher_id:
            try:
                group.teacher = TeacherProfile.objects.get(id=teacher_id)
                group.save()
            except TeacherProfile.DoesNotExist:
                pass

        # Обработка расписания
        days = request.POST.getlist('schedule_day')
        times = request.POST.getlist('schedule_time')
        durations = request.POST.getlist('schedule_duration')

        slots_created = 0
        for day, time_str, duration_str in zip(days, times, durations):
            if day and time_str:
                try:
                    hour, minute = map(int, time_str.split(':'))
                    start_time_obj = time(hour, minute)
                    duration = int(duration_str) if duration_str else 60
                    
                    ScheduleSlot.objects.create(
                        group=group,
                        day_of_week=int(day),
                        start_time=start_time_obj,
                        duration_minutes=duration,
                    )
                    slots_created += 1
                except (ValueError, TypeError):
                    continue

        messages.success(
            request,
            f'Группа «{name}» создана. '
            f'Добавлено слотов расписания: {slots_created}.'
        )
        return redirect('owner_groups')

    teachers = TeacherProfile.objects.all()
    return render(request, 'owner/add_group.html', {
        'teachers': teachers,
    })

@owner_required
def owner_generate_lessons(request):
    """Генерация занятий на 2 недели вперёд"""
    if request.method != 'POST':
        return redirect('owner_groups')

    from django.core.management import call_command
    from io import StringIO

    out = StringIO()
    try:
        call_command('generate_lessons', '--days=14', stdout=out)
        output = out.getvalue()
        
        # Парсим количество созданных занятий
        lines = output.split('\n')
        created = 0
        for line in lines:
            if 'Всего создано занятий:' in line:
                try:
                    created = int(line.split(':')[-1].strip())
                except ValueError:
                    pass
        
        messages.success(
            request,
            f'✅ Занятия сгенерированы на 2 недели вперёд! '
            f'Создано занятий: {created}.'
        )
    except Exception as e:
        messages.error(request, f'Ошибка генерации: {e}')

    return redirect('owner_groups')

# ═══════════════════════════════════════════════════════
# НОВОСТИ И СОБЫТИЯ
# ═══════════════════════════════════════════════════════

def news_list(request):
    news = News.objects.filter(is_published=True).order_by('-published_at')
    return render(request, 'news_list.html', {'news': news})


def news_detail(request, pk):
    item = get_object_or_404(News, pk=pk, is_published=True)
    return render(request, 'news_detail.html', {'news': item})


def events_list(request):
    today = timezone.now().date()
    upcoming = (
        Event.objects
        .filter(is_published=True, date__gte=today)
        .order_by('date')
    )
    past = (
        Event.objects
        .filter(is_published=True, date__lt=today)
        .order_by('-date')[:10]
    )
    return render(request, 'events_list.html', {
        'events': upcoming,
        'past_events': past,
    })


def event_detail(request, pk):
    event = get_object_or_404(Event, pk=pk, is_published=True)
    return render(request, 'event_detail.html', {'event': event})

@login_required
def event_register(request, event_id):
    """Регистрация на мероприятие"""
    event = get_object_or_404(Event, id=event_id, is_published=True)
    
    # Проверяем, требуется ли регистрация
    if not event.is_registration_required:
        messages.error(request, 'Для этого события регистрация не требуется.')
        return redirect('event_detail', pk=event.id)
    
    # Проверяем, открыта ли регистрация
    if not event.is_registration_open:
        messages.error(request, 'Регистрация на это событие закрыта.')
        return redirect('event_detail', pk=event.id)
    
    # Проверяем лимит мест
    if event.spots_available is not None and event.spots_available <= 0:
        messages.error(request, 'К сожалению, все места заняты.')
        return redirect('event_detail', pk=event.id)
    
    # Получаем родителя
    try:
        parent = request.user.parent_profile
    except:
        messages.error(request, 'Только родители могут регистрировать детей.')
        return redirect('event_detail', pk=event.id)
    
    # Получаем детей родителя
    children = parent.children.filter(is_active=True)
    
    if request.method == 'POST':
        child_id = request.POST.get('child_id')
        
        if not child_id:
            messages.error(request, 'Выберите ребёнка.')
            return render(request, 'event_register.html', {
                'event': event,
                'children': children,
            })
        
        child = get_object_or_404(Child, id=child_id, parent=parent)
        
        # Проверяем, не зарегистрирован ли уже
        existing = EventRegistration.objects.filter(
            event=event, child=child
        ).exclude(status='cancelled').first()
        
        if existing:
            messages.warning(
                request,
                f'{child.full_name} уже зарегистрирован(а) на это событие.'
            )
            return redirect('event_detail', pk=event.id)
        
        # Создаём регистрацию
        registration = EventRegistration.objects.create(
            event=event,
            child=child,
            parent=parent,
            status='registered',
        )
        
        # Если бесплатно — сразу отмечаем как оплачено
        if event.price == 0:
            registration.status = 'paid'
            registration.paid_at = timezone.now()
            registration.save()
            messages.success(
                request,
                f'{child.full_name} успешно зарегистрирован(а) на {event.title}!'
            )
        else:
            messages.success(
                request,
                f'{child.full_name} зарегистрирован(а). '
                f'Необходимо оплатить участие: {event.price} ₽.'
            )
        
        return redirect('event_detail', pk=event.id)
    
    return render(request, 'event_register.html', {
        'event': event,
        'children': children,
    })


@login_required
def event_cancel_registration(request, registration_id):
    """Отмена регистрации"""
    registration = get_object_or_404(EventRegistration, id=registration_id)
    
    # Проверяем права
    try:
        parent = request.user.parent_profile
    except:
        return HttpResponseForbidden()
    
    if registration.parent != parent:
        return HttpResponseForbidden()
    
    # Отменяем
    registration.status = 'cancelled'
    registration.save()
    
    messages.success(
        request,
        f'Регистрация {registration.child.full_name} на '
        f'{registration.event.title} отменена.'
    )
    
    return redirect('event_detail', pk=registration.event.id)

@login_required
def event_pay(request, registration_id):
    """Оплата участия в мероприятии"""
    registration = get_object_or_404(
        EventRegistration,
        id=registration_id,
        status='registered'
    )
    
    # Проверяем права
    try:
        parent = request.user.parent_profile
    except:
        return HttpResponseForbidden()
    
    if registration.parent != parent:
        return HttpResponseForbidden()
    
    event = registration.event
    child = registration.child
    
    if event.price <= 0:
        messages.info(request, 'Это мероприятие бесплатное.')
        return redirect('event_detail', pk=event.id)
    
    # Создаём платёж
    order_id = str(uuid.uuid4())[:8]
    payment = Payment.objects.create(
        parent=parent,
        child=child,
        amount=event.price,
        lessons_count=0,  # Это не занятия, а участие в событии
        status='pending',
        method='online',
        note=f'Участие в мероприятии: {event.title}',
        event_registration=registration,
    )
    
    # Создаём платёжную ссылку через Точку
    service = TochkaPaymentService()
    result = service.create_payment_link(
        amount=event.price,
        description=f'Участие в "{event.title}" для {child.full_name}',
        order_id=order_id,
    )
    
    if not result['success']:
        payment.status = 'failed'
        payment.save()
        messages.error(
            request, f'Ошибка создания платежа: {result["error"]}'
        )
        return redirect('event_detail', pk=event.id)
    
    payment.bank_payment_id = result['payment_id']
    payment.save()
    request.session['pending_payment_id'] = payment.id
    
    return redirect(result['url'])

import json
import logging
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils import timezone
from core.models import Payment

logger = logging.getLogger(__name__)

@csrf_exempt
def tochka_webhook(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # Логирование для отладки (в продакшене поможет увидеть реальный формат)
    logger.info(f"Tochka Webhook received. Headers: {dict(request.headers)}")
    
    try:
        payload = json.loads(request.body.decode('utf-8'))
        logger.info(f"Tochka Webhook Payload: {payload}")
    except Exception as e:
        logger.error(f"Invalid JSON in Tochka webhook: {e}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Точка Банк обычно присылает 'id' как ID операции, или 'payment_id'
    payment_id = (
        payload.get('id') or
        payload.get('payment_id') or
        payload.get('operation_id') or
        (payload.get('payment') and payload['payment'].get('id'))
    )
    
    # Приводим к строке для надежного сравнения
    if payment_id:
        payment_id = str(payment_id)
        
    status = payload.get('status')

    if not payment_id:
        logger.warning(f"No payment_id found in payload: {payload}")
        return JsonResponse({'error': 'payment_id is required'}, status=400)

    # Ищем платеж по bank_payment_id
    payment = Payment.objects.filter(bank_payment_id=payment_id).first()

    if not payment:
        logger.warning(f"Payment not found for bank_payment_id: {payment_id}")
        return JsonResponse({'error': 'Payment not found'}, status=404)

    # Статусы Точки: APPROVED, REJECTED, CANCELLED и т.д.
    if status in ['APPROVED', 'SUCCESS', 'paid', 'success', 'completed']:
        if payment.status != 'paid':
            payment.status = 'paid'
            payment.paid_at = timezone.now()
            payment.save()
            logger.info(f"Payment {payment.id} marked as paid.")

            if payment.event_registration:
                registration = payment.event_registration
                registration.status = 'paid'
                registration.paid_at = timezone.now()
                registration.save()
            else:
                from core.services.debts import settle_debts_on_payment
                settle_debts_on_payment(payment)

    elif status in ['REJECTED', 'CANCELLED', 'failed', 'cancelled', 'canceled']:
        if payment.status == 'pending':
            payment.status = 'failed'
            payment.save()
            logger.info(f"Payment {payment.id} marked as failed.")

    return JsonResponse({'ok': True})

@login_required
def change_password(request):
    """Смена пароля пользователя"""
    if request.method == 'POST':
        old_password = request.POST.get('old_password', '')
        new_password1 = request.POST.get('new_password1', '')
        new_password2 = request.POST.get('new_password2', '')

        # Проверка старого пароля
        if not request.user.check_password(old_password):
            messages.error(request, '❌ Неверный текущий пароль.')
            return render(request, 'change_password.html')

        # Проверка совпадения новых паролей
        if new_password1 != new_password2:
            messages.error(request, '❌ Новые пароли не совпадают.')
            return render(request, 'change_password.html')

        # Проверка длины
        if len(new_password1) < 5:
            messages.error(request, '❌ Пароль должен быть не менее 5 символов.')
            return render(request, 'change_password.html')

        # Проверка, что новый пароль отличается от старого
        if old_password == new_password1:
            messages.error(request, '❌ Новый пароль должен отличаться от старого.')
            return render(request, 'change_password.html')

        # Меняем пароль
        request.user.set_password(new_password1)
        request.user.save()

        # Обновляем сессию, чтобы пользователь не вышел из системы
        update_session_auth_hash(request, request.user)

        messages.success(request, '✅ Пароль успешно изменён!')
        return redirect('dashboard')

    return render(request, 'change_password.html')

from core.models import Certificate

@login_required
def child_upload_certificate(request):
    """Загрузка справки ребёнком"""
    if not hasattr(request.user, 'child_profile'):
        messages.error(request, 'Доступ только для детей.')
        return redirect('home')
    
    child = request.user.child_profile
    
    if request.method == 'POST':
        file = request.FILES.get('file')
        date_from = request.POST.get('date_from')
        date_to = request.POST.get('date_to')
        reason = request.POST.get('reason', '')
        
        if not file:
            messages.error(request, 'Выберите файл справки.')
            return redirect('child_upload_certificate')
        
        if not date_from or not date_to:
            messages.error(request, 'Укажите период действия справки.')
            return redirect('child_upload_certificate')
        
        # Проверка расширения
        allowed_ext = ['.pdf', '.jpg', '.jpeg', '.png', '.heic']
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in allowed_ext:
            messages.error(
                request,
                f'Недопустимый формат файла. Разрешены: {", ".join(allowed_ext)}'
            )
            return redirect('child_upload_certificate')
        
        # Проверка размера (не более 10 МБ)
        if file.size > 10 * 1024 * 1024:
            messages.error(request, 'Файл слишком большой. Максимум 10 МБ.')
            return redirect('child_upload_certificate')
        
        Certificate.objects.create(
            child=child,
            file=file,
            date_from=date_from,
            date_to=date_to,
            reason=reason,
            status='pending',
        )
        
        messages.success(
            request,
            '✅ Справка загружена! Владелец проверит её в ближайшее время.'
        )
        return redirect('child_dashboard')
    
    # Список уже загруженных справок
    certificates = Certificate.objects.filter(child=child).order_by('-uploaded_at')
    
    return render(request, 'child_upload_certificate.html', {
        'child': child,
        'certificates': certificates,
    })

@login_required
def parent_upload_certificate(request):
    """Загрузка справки родителем с выбором ребёнка"""
    # Проверяем, что это родитель
    if not hasattr(request.user, 'parent_profile'):
        messages.error(request, 'Доступ только для родителей.')
        return redirect('dashboard')
    
    profile = request.user.parent_profile
    children = profile.children.filter(is_active=True)
    
    if not children.exists():
        messages.warning(request, 'У вас нет детей для загрузки справки.')
        return redirect('parent_dashboard')
    
    if request.method == 'POST':
        child_id = request.POST.get('child_id')
        file = request.FILES.get('file')
        date_from = request.POST.get('date_from')
        date_to = request.POST.get('date_to')
        reason = request.POST.get('reason', '')
        
        if not child_id:
            messages.error(request, 'Выберите ребёнка.')
            return render(request, 'parent_upload_certificate.html', {
                'children': children,
            })
        
        child = get_object_or_404(Child, id=child_id, parent=profile)
        
        if not file:
            messages.error(request, 'Выберите файл справки.')
            return render(request, 'parent_upload_certificate.html', {
                'children': children,
            })
        
        if not date_from or not date_to:
            messages.error(request, 'Укажите период действия справки.')
            return render(request, 'parent_upload_certificate.html', {
                'children': children,
            })
        
        # Проверка расширения
        allowed_ext = ['.pdf', '.jpg', '.jpeg', '.png', '.heic']
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in allowed_ext:
            messages.error(
                request,
                f'Недопустимый формат файла. Разрешены: {", ".join(allowed_ext)}'
            )
            return render(request, 'parent_upload_certificate.html', {
                'children': children,
            })
        
        # Проверка размера (не более 10 МБ)
        if file.size > 10 * 1024 * 1024:
            messages.error(request, 'Файл слишком большой. Максимум 10 МБ.')
            return render(request, 'parent_upload_certificate.html', {
                'children': children,
            })
        
        Certificate.objects.create(
            child=child,
            file=file,
            date_from=date_from,
            date_to=date_to,
            reason=reason,
            status='pending',
        )
        
        messages.success(
            request,
            f'✅ Справка для {child.full_name} загружена! '
            f'Владелец проверит её в ближайшее время.'
        )
        return redirect('child_detail', child_id=child.id)
    
    # Список уже загруженных справок для всех детей
    certificates = Certificate.objects.filter(
        child__parent=profile
    ).select_related('child').order_by('-uploaded_at')
    
    return render(request, 'parent_upload_certificate.html', {
        'children': children,
        'certificates': certificates,
    })
# ═══════════════════════════════════════════════════════
# ИМПОРТ ДЕТЕЙ ИЗ EXCEL
# ═══════════════════════════════════════════════════════

@owner_required
def owner_import_children(request):
    """Страница импорта детей из Excel-файла"""
    from .services.import_children import import_children_from_excel, create_excel_template
    
    context = {
        'result': None,
    }
    
    # Скачивание шаблона
    if request.GET.get('download_template'):
        from django.http import HttpResponse
        template = create_excel_template()
        response = HttpResponse(
            template.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="children_template.xlsx"'
        return response
    
    # Обработка загруженного файла
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']
        
        # Проверка расширения
        if not excel_file.name.endswith(('.xlsx', '.xls')):
            messages.error(request, '❌ Файл должен быть в формате .xlsx или .xls')
        else:
            result = import_children_from_excel(excel_file)
            context['result'] = result
            
            # Сообщения
            if result['success'] > 0:
                messages.success(
                    request,
                    f'✅ Создано детей: {result["success"]}'
                )
            
            if result['skipped'] > 0:
                messages.warning(
                    request,
                    f'⏭️ Пропущено: {result["skipped"]}'
                )
            
            if result['errors']:
                for error in result['errors'][:10]:
                    messages.error(request, f'⚠️ {error}')
                if len(result['errors']) > 10:
                    messages.error(
                        request,
                        f'... и ещё {len(result["errors"]) - 10} ошибок'
                    )
            
            # Сохраняем пароли в CSV
            if result['children']:
                import csv
                import os
                from django.conf import settings
                
                timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
                filename = f'imported_children_{timestamp}.csv'
                filepath = os.path.join(settings.BASE_DIR, 'media', filename)
                
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                
                with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f, delimiter=';')
                    writer.writerow(['ФИО', 'Логин', 'Пароль'])
                    for child in result['children']:
                        writer.writerow([
                            child['full_name'],
                            child['username'],
                            child['password']
                        ])
                
                messages.info(
                    request,
                    f'💾 Пароли сохранены: media/{filename}'
                )
    
    return render(request, 'owner/import_children.html', context)

# ═══════════════════════════════════════════════════════
# ПУБЛИЧНАЯ СТРАНИЦА С ТАРИФАМИ (для Точка Банка)
# ═══════════════════════════════════════════════════════

def pricing_view(request):
    """Страница с тарифами и ценами (публичная)"""
    return render(request, 'pricing.html')
