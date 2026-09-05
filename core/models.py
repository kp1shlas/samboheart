from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class ParentProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE,
        related_name='parent_profile',
        verbose_name='Пользователь'
    )
    phone = models.CharField('Телефон', max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    class Meta:
        verbose_name = 'Профиль родителя'
        verbose_name_plural = 'Профили родителей'


class TeacherProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE,
        related_name='teacher_profile',
        verbose_name='Пользователь'
    )
    specialization = models.CharField('Специализация', max_length=100, blank=True)
    phone = models.CharField('Телефон', max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    class Meta:
        verbose_name = 'Профиль преподавателя'
        verbose_name_plural = 'Профили преподавателей'


class Child(models.Model):
    parent = models.ForeignKey(
        ParentProfile,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='children',
        verbose_name='Родитель'
    )
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='child_profile',
        verbose_name='Аккаунт ребёнка'
    )
    full_name = models.CharField('ФИО', max_length=200)
    birth_date = models.DateField('Дата рождения', null=True, blank=True)
    is_active = models.BooleanField('Активен', default=True)

    def __str__(self):
        return self.full_name

    class Meta:
        verbose_name = 'Ребёнок'
        verbose_name_plural = 'Дети'


class Group(models.Model):
    name = models.CharField('Название', max_length=200)
    teacher = models.ForeignKey(
        TeacherProfile, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='groups',
        verbose_name='Преподаватель'
    )
    max_capacity = models.PositiveIntegerField('Максимум детей', default=20)
    price_per_lesson = models.DecimalField(
        'Цена за 1 занятие', max_digits=10, decimal_places=2, default=0,
        help_text='Фиксированная цена, скидки не применяются'
    )
    lessons_per_month = models.PositiveIntegerField(
        'Занятий в месяц', default=8,
        help_text='Количество занятий в месяц (8 или 12)'
    )
    price_monthly = models.DecimalField(
        'Абонемент на месяц', max_digits=10, decimal_places=2, default=0,
        help_text='Цена абонемента на месяц (может быть со скидкой)'
    )
    is_active = models.BooleanField('Активна', default=True)
    description = models.TextField('Описание', blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Группа'
        verbose_name_plural = 'Группы'


class ChildEnrollment(models.Model):
    child = models.ForeignKey(
        Child, on_delete=models.CASCADE,
        related_name='enrollments',
        verbose_name='Ребёнок'
    )
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE,
        related_name='enrollments',
        verbose_name='Группа'
    )
    remaining_lessons = models.IntegerField('Остаток занятий', default=0)
    is_active = models.BooleanField('Активна', default=True)
    enrolled_at = models.DateField('Дата записи', auto_now_add=True)

    @property
    def is_free(self):
        """Проверяет, является ли запись бесплатной (скидка 100%)"""
        today = timezone.now().date()
        return self.discounts.filter(
            is_active=True,
            discount_type='free',
            valid_from__lte=today,
            valid_until__gte=today
        ).exists()

    def __str__(self):
        return f'{self.child.full_name} → {self.group.name}'

    class Meta:
        verbose_name = 'Запись в группу'
        verbose_name_plural = 'Записи в группы'
        unique_together = ['child', 'group']


class ChildDiscount(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ('percent', 'Процент'),
        ('fixed', 'Фиксированная сумма'),
        ('free', 'Бесплатно'),
    ]

    enrollments = models.ManyToManyField(
        ChildEnrollment,
        related_name='discounts',
        verbose_name='Записи в группы',
        help_text='Выберите одного или нескольких детей'
    )
    discount_type = models.CharField(
        'Тип скидки', max_length=20,
        choices=DISCOUNT_TYPE_CHOICES,
        default='percent'
    )
    discount_value = models.DecimalField(
        'Значение скидки', max_digits=10, decimal_places=2,
        help_text='Для процента: 50 = 50%. Для фиксированной: 500 = 500₽'
    )
    reason = models.CharField(
        'Причина', max_length=200,
        help_text='Например: Многодетная семья, Минспорт'
    )
    valid_from = models.DateField('Действует с')
    valid_until = models.DateField('Действует до')
    is_active = models.BooleanField('Активна', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        enrollments_count = self.enrollments.count()
        return f'{self.get_discount_type_display()} ({enrollments_count} детей) — {self.reason}'

    class Meta:
        verbose_name = 'Скидка'
        verbose_name_plural = 'Скидки'
        ordering = ['-created_at']


class ScheduleSlot(models.Model):
    DAY_CHOICES = [(i, day) for i, day in enumerate([
        'Понедельник', 'Вторник', 'Среда', 'Четверг',
        'Пятница', 'Суббота', 'Воскресенье'
    ])]

    group = models.ForeignKey(
        Group, on_delete=models.CASCADE,
        related_name='schedule_slots',
        verbose_name='Группа'
    )
    day_of_week = models.PositiveSmallIntegerField(
        'День недели', choices=DAY_CHOICES
    )
    start_time = models.TimeField('Время начала')
    duration_minutes = models.PositiveIntegerField(
        'Длительность (мин)', default=60
    )

    def __str__(self):
        return f'{self.group.name} — {self.get_day_of_week_display()} {self.start_time}'

    class Meta:
        verbose_name = 'Слот расписания'
        verbose_name_plural = 'Расписание'


class Lesson(models.Model):
    group = models.ForeignKey(
        Group, 
        on_delete=models.SET_NULL, # Если группу удалят, индивидуальное занятие останется
        null=True, 
        blank=True, # Разрешаем создавать занятие БЕЗ группы
        related_name='lessons',
        verbose_name='Группа'
    )
    date = models.DateField('Дата')
    start_time = models.TimeField('Время начала')
    is_cancelled = models.BooleanField('Отменено', default=False)
    cancel_reason = models.CharField('Причина отмены', max_length=300, blank=True)
    
    # НОВОЕ ПОЛЕ: Отдельные дети, для которых предназначено это занятие
    specific_children = models.ManyToManyField(
        Child, 
        blank=True,
        related_name='specific_lessons',
        verbose_name='Отдельные дети (дополнительно к группе)'
    )

    def __str__(self):
        group_name = self.group.name if self.group else "Индивидуальное"
        return f'{group_name} — {self.date} {self.start_time}'

    class Meta:
        verbose_name = 'Занятие'
        verbose_name_plural = 'Занятия'
        ordering = ['-date', 'start_time']


class Attendance(models.Model):
    STATUS_CHOICES = [
        ('present', 'Был'),
        ('absent', 'Не был'),
        ('excused', 'Пропуск по справке'),
    ]

    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE,
        related_name='attendance_records',
        verbose_name='Занятие'
    )
    child = models.ForeignKey(
        Child, on_delete=models.CASCADE,
        related_name='attendance_records',
        verbose_name='Ребёнок'
    )
    enrollment = models.ForeignKey(
        ChildEnrollment,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='attendance_records',
        verbose_name='Запись в группу'
    )
    status = models.CharField(
        'Статус', max_length=20,
        choices=STATUS_CHOICES, default='present'
    )
    was_deducted = models.BooleanField('Занятие списано', default=False)
    is_debt = models.BooleanField('В долг (был без оплаты)', default=False)

    def __str__(self):
        return f'{self.child.full_name} — {self.lesson.date}'

    class Meta:
        verbose_name = 'Посещаемость'
        verbose_name_plural = 'Посещаемость'
        unique_together = ['lesson', 'child']


class Certificate(models.Model):
    STATUS_CHOICES = [
        ('pending', 'На проверке'),
        ('approved', 'Одобрена'),
        ('rejected', 'Отклонена'),
    ]

    child = models.ForeignKey(
        Child, on_delete=models.CASCADE,
        related_name='certificates',
        verbose_name='Ребёнок'
    )
    file = models.FileField('Файл справки', upload_to='certificates/')
    date_from = models.DateField('Период с')
    date_to = models.DateField('Период по')
    status = models.CharField(
        'Статус', max_length=20,
        choices=STATUS_CHOICES, default='pending'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'Справка {self.child.full_name} ({self.date_from} — {self.date_to})'

    class Meta:
        verbose_name = 'Справка'
        verbose_name_plural = 'Справки'


class News(models.Model):
    title = models.CharField('Заголовок', max_length=300)
    content = models.TextField('Текст')
    image = models.ImageField(
        'Изображение', upload_to='news_images/',
        null=True, blank=True
    )
    author = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='Автор'
    )
    published_at = models.DateTimeField(null=True, blank=True)
    is_published = models.BooleanField('Опубликовано', default=False)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = 'Новость'
        verbose_name_plural = 'Новости'
        ordering = ['-published_at']


class Event(models.Model):
    title = models.CharField('Название', max_length=300)
    description = models.TextField('Описание', blank=True)
    image = models.ImageField(
        'Изображение', upload_to='event_images/',
        null=True, blank=True
    )
    date = models.DateField('Дата события')
    time = models.TimeField('Время', null=True, blank=True)
    location = models.CharField('Место', max_length=300, blank=True)
    is_published = models.BooleanField('Опубликовано', default=False)
    
    # Новые поля для регистрации
    is_registration_required = models.BooleanField(
        'Требуется регистрация', default=False
    )
    max_participants = models.PositiveIntegerField(
        'Максимум участников', null=True, blank=True,
        help_text='Оставьте пустым для неограниченного количества'
    )
    price = models.DecimalField(
        'Стоимость участия', max_digits=10, decimal_places=2,
        default=0, help_text='0 = бесплатно'
    )
    registration_deadline = models.DateTimeField(
        'Дедлайн регистрации', null=True, blank=True,
        help_text='После этой даты регистрация закрывается'
    )

    def __str__(self):
        return self.title

    @property
    def spots_available(self):
        """Сколько мест свободно"""
        if not self.max_participants:
            return None  # Неограниченно
        registered = self.registrations.filter(
            status__in=['registered', 'paid']
        ).count()
        return max(0, self.max_participants - registered)

    @property
    def is_registration_open(self):
        """Открыта ли регистрация"""
        if not self.is_registration_required:
            return False
        if self.registration_deadline:
            return timezone.now() < self.registration_deadline
        return True

    class Meta:
        verbose_name = 'Событие'
        verbose_name_plural = 'События'
        ordering = ['-date']

class EventRegistration(models.Model):
    STATUS_CHOICES = [
        ('registered', 'Зарегистрирован'),
        ('paid', 'Оплачено'),
        ('attended', 'Посетил'),
        ('cancelled', 'Отменено'),
    ]

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE,
        related_name='registrations',
        verbose_name='Событие'
    )
    child = models.ForeignKey(
        Child, on_delete=models.CASCADE,
        related_name='event_registrations',
        verbose_name='Ребёнок'
    )
    parent = models.ForeignKey(
        ParentProfile, on_delete=models.CASCADE,
        related_name='event_registrations',
        verbose_name='Родитель'
    )
    status = models.CharField(
        'Статус', max_length=20,
        choices=STATUS_CHOICES, default='registered'
    )
    registered_at = models.DateTimeField('Дата регистрации', auto_now_add=True)
    paid_at = models.DateTimeField('Дата оплаты', null=True, blank=True)
    notes = models.TextField('Примечания', blank=True)

    def __str__(self):
        return f'{self.child.full_name} → {self.event.title}'

    class Meta:
        verbose_name = 'Регистрация на событие'
        verbose_name_plural = 'Регистрации на события'
        unique_together = ['event', 'child']
        ordering = ['-registered_at']


class Payment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидает оплаты'),
        ('paid', 'Оплачен'),
        ('failed', 'Ошибка'),
        ('refunded', 'Возврат'),
    ]
    METHOD_CHOICES = [
        ('online', 'Онлайн'),
        ('cash', 'Наличные'),
    ]

    operation_id = models.CharField(
        'ID операции в банке', max_length=100, blank=True, null=True,
        help_text='ID платежа в Точка Банке'
    )

    parent = models.ForeignKey(
        ParentProfile, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payments',
        verbose_name='Родитель'
    )
    child = models.ForeignKey(
        Child, on_delete=models.CASCADE,
        related_name='payments',
        verbose_name='Ребёнок'
    )
    enrollment = models.ForeignKey(
        ChildEnrollment,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payments',
        verbose_name='Запись в группу'
    )
    amount = models.DecimalField('Сумма', max_digits=10, decimal_places=2)
    lessons_count = models.PositiveIntegerField('Количество занятий', default=1)
    status = models.CharField(
        'Статус', max_length=20,
        choices=STATUS_CHOICES, default='pending'
    )
    method = models.CharField(
        'Способ оплаты', max_length=20,
        choices=METHOD_CHOICES, default='online'
    )
    event_registration = models.ForeignKey(
        'EventRegistration',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payments',
        verbose_name='Регистрация на событие'
    )
    bank_payment_id = models.CharField(
        'ID платежа в банке', max_length=100, blank=True
    )
    note = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.child.full_name} — {self.amount}₽'

    class Meta:
        verbose_name = 'Платёж'
        verbose_name_plural = 'Платежи'
        ordering = ['-created_at']

class LoginHistory(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, 
        related_name='login_history',
        verbose_name='Пользователь'
    )
    ip_address = models.GenericIPAddressField('IP адрес', null=True, blank=True)
    timestamp = models.DateTimeField('Время входа', auto_now_add=True)

    class Meta:
        verbose_name = 'История входов'
        verbose_name_plural = 'Истории входов'
        ordering = ['-timestamp']

    def __str__(self):
        time_str = self.timestamp.strftime("%d.%m.%Y %H:%M")
        return f'{self.user.username} - {time_str}'