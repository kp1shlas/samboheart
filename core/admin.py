from django.contrib import admin
from django.utils import timezone
from datetime import datetime
from .models import (
    ParentProfile, TeacherProfile, Child, Group,
    Lesson, Attendance, Certificate, ScheduleSlot,
    News, Event, Payment, ChildEnrollment, ChildDiscount, EventRegistration
)


# ═══════════════════════════════════════════════════════
# ПРОФИЛИ
# ═══════════════════════════════════════════════════════

@admin.register(ParentProfile)
class ParentProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'phone', 'get_children_count']
    search_fields = ['user__last_name', 'user__email', 'phone']

    @admin.display(description='Детей')
    def get_children_count(self, obj):
        return obj.children.count()


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'specialization', 'phone']
    search_fields = ['user__last_name', 'user__email']


# ═══════════════════════════════════════════════════════
# ДЕТИ И ЗАПИСИ В ГРУППЫ
# ═══════════════════════════════════════════════════════

class ChildEnrollmentInline(admin.TabularInline):
    model = ChildEnrollment
    extra = 1
    fields = ['group', 'remaining_lessons', 'is_active', 'enrolled_at']
    readonly_fields = ['enrolled_at']
    verbose_name = 'Запись в группу'
    verbose_name_plural = 'Записи в группы'


@admin.register(Child)
class ChildAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'parent', 'birth_date', 'is_active']
    list_filter = ['is_active']
    search_fields = ['full_name', 'user__username', 'parent__user__username']
    raw_id_fields = ['parent', 'user']
    actions = ['import_from_excel', 'export_to_excel']

    @admin.action(description='📥 Импорт детей из Excel')
    def import_from_excel(self, request, queryset):
        from django.shortcuts import render, redirect
        from django.http import HttpResponseRedirect, HttpResponse
        from django.urls import reverse
        from .services.import_children import import_children_from_excel, create_excel_template
        
        # Если GET — показываем форму загрузки
        if request.method != 'POST':
            # Создаём шаблон для скачивания
            template = create_excel_template()
            
            response = HttpResponse(
                template.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = 'attachment; filename="children_template.xlsx"'
            
            # Сохраняем в сессии флаг, что нужно показать форму после скачивания
            request.session['show_import_form'] = True
            return response
        
        # Если POST — обрабатываем загруженный файл
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            self.message_user(request, 'Файл не выбран', level='error')
            return HttpResponseRedirect(request.get_full_path())
        
        # Импортируем
        result = import_children_from_excel(excel_file)
        
        # Формируем сообщение
        messages_list = []
        if result['success'] > 0:
            messages_list.append(f'✅ Создано детей: {result["success"]}')
        if result['skipped'] > 0:
            messages_list.append(f'⏭️ Пропущено: {result["skipped"]}')
        if result['errors']:
            messages_list.append(f'❌ Ошибок: {len(result["errors"])}')
        
        self.message_user(request, ' | '.join(messages_list))
        
        # Показываем детали
        if result['children']:
            details = []
            for child in result['children'][:5]:
                details.append(f"{child['full_name']} (логин: {child['username']}, пароль: {child['password']})")
            
            if len(result['children']) > 5:
                details.append(f"... и ещё {len(result['children']) - 5}")
            
            self.message_user(request, '📋 Созданные аккаунты: ' + '; '.join(details))
        
        if result['errors']:
            self.message_user(request, '⚠️ Ошибки: ' + '; '.join(result['errors'][:10]), level='warning')
        
        return HttpResponseRedirect(request.get_full_path())

    @admin.action(description='📤 Экспорт детей в Excel')
    def export_to_excel(self, request, queryset):
        import openpyxl
        from django.http import HttpResponse
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Дети'
        
        # Заголовки
        headers = ['ФИО', 'Дата рождения', 'Логин', 'Группы', 'Родитель']
        ws.append(headers)
        
        # Данные
        for child in queryset:
            groups = ', '.join([e.group.name for e in child.enrollments.all()])
            parent_username = child.parent.user.username if child.parent else ''
            
            ws.append([
                child.full_name,
                child.birth_date.strftime('%d.%m.%Y') if child.birth_date else '',
                child.user.username if child.user else '',
                groups,
                parent_username,
            ])
        
        # Настройка ширины
        ws.column_dimensions['A'].width = 30
        ws.column_dimensions['B'].width = 15
        ws.column_dimensions['C'].width = 20
        ws.column_dimensions['D'].width = 30
        ws.column_dimensions['E'].width = 20
        
        # Возвращаем файл
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="children_export.xlsx"'
        wb.save(response)
        
        return response

@admin.register(ChildEnrollment)
class ChildEnrollmentAdmin(admin.ModelAdmin):
    list_display = ['child', 'group', 'remaining_lessons', 'is_active', 'enrolled_at']
    list_filter = ['group', 'is_active']
    list_editable = ['remaining_lessons', 'is_active']
    search_fields = ['child__full_name']
    raw_id_fields = ['child', 'group']


# ═══════════════════════════════════════════════════════
# СКИДКИ
# ═══════════════════════════════════════════════════════

@admin.register(ChildDiscount)
class ChildDiscountAdmin(admin.ModelAdmin):
    list_display = ['discount_type', 'discount_value', 'reason',
                    'valid_from', 'valid_until', 'is_active', 'get_enrollments_count']
    list_filter = ['discount_type', 'is_active']
    list_editable = ['is_active']
    search_fields = ['enrollments__child__full_name', 'reason']
    filter_horizontal = ['enrollments']
    date_hierarchy = 'valid_from'

    @admin.display(description='Детей')
    def get_enrollments_count(self, obj):
        return obj.enrollments.count()


# ═══════════════════════════════════════════════════════
# ГРУППЫ И РАСПИСАНИЕ
# ═══════════════════════════════════════════════════════

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'teacher', 'price_per_lesson',
                    'price_abonement_4', 'max_capacity', 'is_active']
    list_filter = ['is_active', 'teacher']
    list_editable = ['is_active', 'price_per_lesson', 'price_abonement_4']
    search_fields = ['name']


@admin.register(ScheduleSlot)
class ScheduleSlotAdmin(admin.ModelAdmin):
    list_display = ['group', 'get_day_display', 'start_time', 'duration_minutes']
    list_filter = ['group', 'day_of_week']

    @admin.display(description='День недели')
    def get_day_display(self, obj):
        days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        return days[obj.day_of_week]


# ═══════════════════════════════════════════════════════
# ЗАНЯТИЯ И ПОСЕЩАЕМОСТЬ
# ═══════════════════════════════════════════════════════

@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ['group', 'date', 'start_time', 'is_cancelled', 'cancel_reason']
    list_filter = ['group', 'date', 'is_cancelled']
    list_editable = ['is_cancelled']
    date_hierarchy = 'date'
    actions = ['cancel_lessons', 'restore_lessons']

    @admin.action(description='🚫 Отменить выбранные занятия')
    def cancel_lessons(self, request, queryset):
        updated = queryset.update(
            is_cancelled=True,
            cancel_reason='По решению администрации'
        )
        self.message_user(request, f'Отменено занятий: {updated}.')

    @admin.action(description='✅ Восстановить выбранные занятия')
    def restore_lessons(self, request, queryset):
        updated = queryset.update(is_cancelled=False, cancel_reason='')
        self.message_user(request, f'Восстановлено занятий: {updated}.')


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ['child', 'lesson', 'status', 'was_deducted', 'is_debt']
    list_filter = ['status', 'is_debt', 'lesson__date']
    list_editable = ['status']
    search_fields = ['child__full_name']
    raw_id_fields = ['lesson', 'child']


# ═══════════════════════════════════════════════════════
# СПРАВКИ
# ═══════════════════════════════════════════════════════

@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ['child', 'date_from', 'date_to', 'status', 'uploaded_at']
    list_filter = ['status']
    search_fields = ['child__full_name']
    raw_id_fields = ['child']
    readonly_fields = ['uploaded_at', 'reviewed_at']
    actions = ['approve', 'reject']

    @admin.action(description='✅ Одобрить выбранные')
    def approve(self, request, queryset):
        from .services.certificates import approve_certificate

        total_returned = 0
        for cert in queryset:
            cert.status = 'approved'
            cert.reviewed_at = timezone.now()
            cert.save()
            total_returned += approve_certificate(cert)

        msg = f'Одобрено справок: {queryset.count()}.'
        if total_returned > 0:
            msg += f' Возвращено занятий: {total_returned}.'
        self.message_user(request, msg)

    @admin.action(description='❌ Отклонить выбранные')
    def reject(self, request, queryset):
        from .services.certificates import reject_certificate

        total_deducted = 0
        for cert in queryset:
            cert.status = 'rejected'
            cert.reviewed_at = timezone.now()
            cert.save()
            total_deducted += reject_certificate(cert)

        msg = f'Отклонено справок: {queryset.count()}.'
        if total_deducted > 0:
            msg += f' Списано занятий: {total_deducted}.'
        self.message_user(request, msg)


# ═══════════════════════════════════════════════════════
# НОВОСТИ И СОБЫТИЯ
# ═══════════════════════════════════════════════════════

@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ['title', 'author', 'published_at', 'is_published']
    list_filter = ['is_published', 'published_at']
    list_editable = ['is_published']
    search_fields = ['title', 'content']
    date_hierarchy = 'published_at'
    actions = ['publish_news', 'unpublish_news']

    @admin.action(description='📢 Опубликовать выбранные')
    def publish_news(self, request, queryset):
        updated = queryset.update(is_published=True, published_at=timezone.now())
        self.message_user(request, f'Опубликовано новостей: {updated}.')

    @admin.action(description='🔒 Снять с публикации')
    def unpublish_news(self, request, queryset):
        updated = queryset.update(is_published=False)
        self.message_user(request, f'Снято с публикации: {updated}.')


class EventRegistrationInline(admin.TabularInline):
    model = EventRegistration
    extra = 0
    fields = ['child', 'parent', 'status', 'registered_at', 'paid_at']
    readonly_fields = ['registered_at', 'paid_at']
    raw_id_fields = ['child', 'parent']


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'date', 'time', 'location',
        'is_registration_required', 'get_participants', 'is_published'
    ]
    list_filter = ['is_published', 'date', 'is_registration_required']
    list_editable = ['is_published', 'is_registration_required']
    search_fields = ['title', 'description']
    date_hierarchy = 'date'
    inlines = [EventRegistrationInline]
    
    fieldsets = (
        ('Основное', {
            'fields': ('title', 'description', 'image', 'is_published')
        }),
        ('Дата и место', {
            'fields': ('date', 'time', 'location')
        }),
        ('Регистрация', {
            'fields': (
                'is_registration_required',
                'max_participants',
                'price',
                'registration_deadline'
            ),
            'classes': ('collapse',)
        }),
    )

    @admin.display(description='Участники')
    def get_participants(self, obj):
        if not obj.is_registration_required:
            return '—'
        count = obj.registrations.filter(
            status__in=['registered', 'paid']
        ).count()
        if obj.max_participants:
            return f'{count}/{obj.max_participants}'
        return f'{count}'

class EventRegistrationInline(admin.TabularInline):
    model = EventRegistration
    extra = 0
    fields = ['child', 'parent', 'status', 'registered_at', 'paid_at']
    readonly_fields = ['registered_at', 'paid_at']
    raw_id_fields = ['child', 'parent']

@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = [
        'child', 'event', 'status', 'registered_at', 'paid_at'
    ]
    list_filter = ['status', 'event']
    list_editable = ['status']
    search_fields = ['child__full_name', 'event__title']
    raw_id_fields = ['event', 'child', 'parent']
    date_hierarchy = 'registered_at'
    actions = ['mark_as_paid', 'mark_as_attended']

    @admin.action(description='💰 Отметить как оплаченные')
    def mark_as_paid(self, request, queryset):
        updated = queryset.update(status='paid', paid_at=timezone.now())
        self.message_user(request, f'Отмечено как оплаченные: {updated}.')

    @admin.action(description='✅ Отметить как посетившие')
    def mark_as_attended(self, request, queryset):
        updated = queryset.update(status='attended')
        self.message_user(request, f'Отмечено как посетившие: {updated}.')

# ═══════════════════════════════════════════════════════
# ПЛАТЕЖИ
# ═══════════════════════════════════════════════════════

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['child', 'get_group', 'amount', 'lessons_count',
                    'method', 'status', 'paid_at']
    list_filter = ['status', 'method', 'paid_at']
    search_fields = ['child__full_name', 'parent__user__last_name']
    raw_id_fields = ['parent', 'child', 'enrollment']
    date_hierarchy = 'paid_at'

    @admin.display(description='Группа')
    def get_group(self, obj):
        if obj.enrollment:
            return obj.enrollment.group.name
        return '—'
