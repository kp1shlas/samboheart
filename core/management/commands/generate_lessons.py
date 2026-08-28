"""
Команда для автоматической генерации занятий
по расписанию групп на указанный период.

Использование:
    python manage.py generate_lessons              # на 7 дней вперёд
    python manage.py generate_lessons --days 14    # на 14 дней вперёд
    python manage.py generate_lessons --days 7 --force  # пересоздать
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from core.models import Group, ScheduleSlot, Lesson


class Command(BaseCommand):
    help = (
        'Генерирует занятия по расписанию групп на указанный период. '
        'Идемпотентна — не создаёт дубликаты.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='На сколько дней вперёд генерировать занятия (по умолчанию: 7)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Принудительно пересоздать занятия (по умолчанию: пропускать существующие)'
        )

    def handle(self, *args, **options):
        days = options['days']
        force = options['force']
        
        today = timezone.now().date()
        
        # Активные группы с расписанием
        groups = Group.objects.filter(is_active=True).prefetch_related('schedule_slots')
        
        if not groups.exists():
            self.stdout.write(self.style.WARNING('⚠️ Нет активных групп.'))
            return
        
        total_created = 0
        total_skipped = 0
        
        for group in groups:
            slots = group.schedule_slots.all()
            if not slots:
                continue
            
            group_created = 0
            
            for day_offset in range(days):
                current_date = today + timedelta(days=day_offset)
                weekday = current_date.weekday()
                
                # Слоты на этот день недели
                day_slots = slots.filter(day_of_week=weekday)
                
                for slot in day_slots:
                    if force:
                        # Принудительная пересоздание
                        lesson, created = Lesson.objects.update_or_create(
                            group=group,
                            date=current_date,
                            start_time=slot.start_time,
                            defaults={'is_cancelled': False}
                        )
                        if created:
                            group_created += 1
                            total_created += 1
                    else:
                        # Создание только если не существует
                        lesson, created = Lesson.objects.get_or_create(
                            group=group,
                            date=current_date,
                            defaults={'start_time': slot.start_time}
                        )
                        if created:
                            group_created += 1
                            total_created += 1
                        else:
                            total_skipped += 1
            
            if group_created > 0:
                self.stdout.write(
                    f'  ✅ {group.name}: создано занятий — {group_created}'
                )
        
        # Итог
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'🎉 Всего создано занятий: {total_created}'
        ))
        if total_skipped > 0:
            self.stdout.write(
                f'⏭️  Пропущено (уже существуют): {total_skipped}'
            )