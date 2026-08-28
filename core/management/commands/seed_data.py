from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from datetime import time, date
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

from core.models import (
    TeacherProfile, ParentProfile, Group, Child, ChildEnrollment,
    ChildDiscount, ScheduleSlot, News, Event, Lesson
)


class Command(BaseCommand):
    help = 'Заполнить базу тестовыми данными с разными типами скидок'

    def handle(self, *args, **options):
        # ═══════════════════════════════════════════════════
        # 1. ПРЕПОДАВАТЕЛИ
        # ═══════════════════════════════════════════════════
        u1, created = User.objects.get_or_create(
            username='ivanov',
            defaults={
                'first_name': 'Иван',
                'last_name': 'Иванов',
                'email': 'ivanov@serdce-sambo.ru',
            }
        )
        if created:
            u1.set_password('12345')
            u1.save()
        t1, _ = TeacherProfile.objects.get_or_create(
            user=u1, defaults={'specialization': 'Самбо'}
        )

        u2, created = User.objects.get_or_create(
            username='petrov',
            defaults={
                'first_name': 'Пётр',
                'last_name': 'Петров',
                'email': 'petrov@serdce-sambo.ru',
            }
        )
        if created:
            u2.set_password('12345')
            u2.save()
        t2, _ = TeacherProfile.objects.get_or_create(
            user=u2, defaults={'specialization': 'Дзюдо'}
        )

        self.stdout.write('✅ Преподаватели созданы')

        # ═══════════════════════════════════════════════════
        # 2. ГРУППЫ
        # ═══════════════════════════════════════════════════
        g1, _ = Group.objects.get_or_create(
            name='Самбо 7–9 лет',
            defaults={
                'teacher': t1,
                'price_per_lesson': Decimal('500'),
                'price_abonement_4': Decimal('1800'),
                'max_capacity': 15,
                'description': 'Группа для начинающих',
            }
        )
        g2, _ = Group.objects.get_or_create(
            name='Самбо 10–12 лет',
            defaults={
                'teacher': t2,
                'price_per_lesson': Decimal('600'),
                'price_abonement_4': Decimal('2200'),
                'max_capacity': 15,
                'description': 'Группа для продолжающих',
            }
        )

        self.stdout.write('✅ Группы созданы')

        # ═══════════════════════════════════════════════════
        # 3. РАСПИСАНИЕ
        # ═══════════════════════════════════════════════════
        ScheduleSlot.objects.get_or_create(
            group=g1, day_of_week=0,
            defaults={'start_time': time(16, 0), 'duration_minutes': 60}
        )
        ScheduleSlot.objects.get_or_create(
            group=g1, day_of_week=2,
            defaults={'start_time': time(16, 0), 'duration_minutes': 60}
        )
        ScheduleSlot.objects.get_or_create(
            group=g2, day_of_week=1,
            defaults={'start_time': time(17, 0), 'duration_minutes': 90}
        )
        ScheduleSlot.objects.get_or_create(
            group=g2, day_of_week=4,
            defaults={'start_time': time(17, 0), 'duration_minutes': 90}
        )

        self.stdout.write('✅ Расписание создано')

        # ═══════════════════════════════════════════════════
        # 4. РОДИТЕЛЬ И ТРИ РЕБЁНКА С РАЗНЫМИ СКИДКАМИ
        # ═══════════════════════════════════════════════════
        pu, created = User.objects.get_or_create(
            username='parent1',
            defaults={
                'first_name': 'Мария',
                'last_name': 'Сидорова',
                'email': 'maria@example.com',
            }
        )
        if created:
            pu.set_password('12345')
            pu.save()
        pp, _ = ParentProfile.objects.get_or_create(user=pu)

        today = timezone.now().date()
        in_a_year = today + timedelta(days=365)
        a_month_ago = today - timedelta(days=30)

        # ─── Ребёнок 1: ПОЛНАЯ ЦЕНА (без скидки) ───
        child1, _ = Child.objects.get_or_create(
            full_name='Сидоров Алексей',
            parent=pp,
            defaults={'birth_date': '2017-05-15'}
        )
        enrollment1, _ = ChildEnrollment.objects.get_or_create(
            child=child1, group=g1,
            defaults={'remaining_lessons': 8}
        )
        # Скидка НЕ создаётся — полная цена
        self.stdout.write(
            '   👦 Сидоров Алексей → Самбо 7-9 лет '
            '(💰 полная цена)'
        )

        # ─── Ребёнок 2: ЧАСТИЧНАЯ СКИДКА 50% ───
        # (Многодетная семья)
        child2, _ = Child.objects.get_or_create(
            full_name='Сидорова Анна',
            parent=pp,
            defaults={'birth_date': '2014-03-22'}
        )
        enrollment2, _ = ChildEnrollment.objects.get_or_create(
            child=child2, group=g2,
            defaults={'remaining_lessons': 6}
        )
        ChildDiscount.objects.update_or_create(
            enrollment=enrollment2,
            discount_type='percent',
            defaults={
                'discount_value': Decimal('50'),
                'reason': 'Многодетная семья (3+ детей)',
                'valid_from': a_month_ago,
                'valid_until': in_a_year,
                'is_active': True,
            }
        )
        self.stdout.write(
            '   👧 Сидорова Анна → Самбо 10-12 лет '
            '(🏷️ скидка 50%, многодетная)'
        )

        # ─── Ребёнок 3: БЕСПЛАТНО (Минспорт) ───
        child3, _ = Child.objects.get_or_create(
            full_name='Кузнецов Дмитрий',
            parent=pp,
            defaults={'birth_date': '2015-08-10'}
        )
        # Записан в две группы
        enrollment3a, _ = ChildEnrollment.objects.get_or_create(
            child=child3, group=g1,
            defaults={'remaining_lessons': 0}
        )
        enrollment3b, _ = ChildEnrollment.objects.get_or_create(
            child=child3, group=g2,
            defaults={'remaining_lessons': 0}
        )
        # Бесплатная скидка на обе группы
        ChildDiscount.objects.update_or_create(
            enrollment=enrollment3a,
            discount_type='free',
            defaults={
                'discount_value': Decimal('100'),
                'reason': 'Минспорт — бесплатные занятия',
                'valid_from': a_month_ago,
                'valid_until': in_a_year,
                'is_active': True,
            }
        )
        ChildDiscount.objects.update_or_create(
            enrollment=enrollment3b,
            discount_type='free',
            defaults={
                'discount_value': Decimal('100'),
                'reason': 'Минспорт — бесплатные занятия',
                'valid_from': a_month_ago,
                'valid_until': in_a_year,
                'is_active': True,
            }
        )
        self.stdout.write(
            '   👦 Кузнецов Дмитрий → 2 группы '
            '(🎁 бесплатно, Минспорт)'
        )

        # ─── Ребёнок 4: ФИКСИРОВАННАЯ СКИДКА 200₽ ───
        # (Сотрудник спорткомплекса)
        child4, _ = Child.objects.get_or_create(
            full_name='Васильев Пётр',
            parent=pp,
            defaults={'birth_date': '2016-11-05'}
        )
        enrollment4, _ = ChildEnrollment.objects.get_or_create(
            child=child4, group=g1,
            defaults={'remaining_lessons': 3}
        )
        ChildDiscount.objects.update_or_create(
            enrollment=enrollment4,
            discount_type='fixed',
            defaults={
                'discount_value': Decimal('200'),
                'reason': 'Сотрудник спорткомплекса',
                'valid_from': a_month_ago,
                'valid_until': in_a_year,
                'is_active': True,
            }
        )
        self.stdout.write(
            '   👦 Васильев Пётр → Самбо 7-9 лет '
            '(🏷️ скидка 200₽, сотрудник)'
        )

        self.stdout.write('✅ Дети и скидки созданы')

        # ═══════════════════════════════════════════════════
        # 5. НОВОСТИ И СОБЫТИЯ
        # ═══════════════════════════════════════════════════
        news_items = [
            {
                'title': 'Открыт набор в группу самбо для детей 7–9 лет',
                'content': (
                    'Приглашаем детей на занятия самбо! '
                    'Первое занятие бесплатно. '
                    'Тренировки ведут опытные мастера спорта.'
                ),
            },
            {
                'title': 'Поздравляем наших чемпионов!',
                'content': (
                    'Наши воспитанники заняли призовые места '
                    'на региональных соревнованиях. '
                    'Поздравляем ребят и их тренера!'
                ),
            },
            {
                'title': 'Расписание летних сборов',
                'content': (
                    'Объявляем расписание летних тренировочных сборов. '
                    'Подробности у тренеров.'
                ),
            },
        ]

        for i, item in enumerate(news_items):
            News.objects.update_or_create(
                title=item['title'],
                defaults={
                    'content': item['content'],
                    'author': u1,
                    'is_published': True,
                    'published_at': timezone.now() - timedelta(days=i * 3),
                }
            )

        Event.objects.update_or_create(
            title='Открытый турнир «Сердце Самбо»',
            defaults={
                'description': (
                    'Приглашаем всех на открытый турнир по самбо! '
                    'Участники из разных городов, зрелищные поединки.'
                ),
                'date': (timezone.now() + timedelta(days=30)).date(),
                'time': time(10, 0),
                'location': 'Спортзал, ул. Спортивная, 1',
                'is_published': True,
            }
        )

        self.stdout.write('✅ Новости и события созданы')

        # ═══════════════════════════════════════════════════
        # 6. ЗАНЯТИЯ НА БЛИЖАЙШИЕ 14 ДНЕЙ
        # ═══════════════════════════════════════════════════
        slots = ScheduleSlot.objects.all()
        lessons_created = 0

        for day_offset in range(14):
            current_date = today + timedelta(days=day_offset)
            weekday = current_date.weekday()

            for slot in slots.filter(day_of_week=weekday):
                _, created = Lesson.objects.get_or_create(
                    group=slot.group,
                    date=current_date,
                    defaults={'start_time': slot.start_time}
                )
                if created:
                    lessons_created += 1

        self.stdout.write(f'✅ Создано занятий на 2 недели: {lessons_created}')

        # ═══════════════════════════════════════════════════
        # ИТОГ
        # ═══════════════════════════════════════════════════
        self.stdout.write(self.style.SUCCESS(
            '\n🎉 Тестовые данные загружены успешно!'
        ))
        self.stdout.write(self.style.SUCCESS(
            '\nАккаунты для входа (пароль: 12345):'
        ))
        self.stdout.write('  • ivanov   — преподаватель')
        self.stdout.write('  • petrov   — преподаватель')
        self.stdout.write('  • parent1  — родитель (4 детей со скидками)')
        self.stdout.write('  • admin    — владелец/админ')
        self.stdout.write(self.style.SUCCESS(
            '\n📊 Дети родителя:'
        ))
        self.stdout.write('  • Сидоров Алексей — полная цена (500₽)')
        self.stdout.write('  • Сидорова Анна — скидка 50% (250₽)')
        self.stdout.write('  • Кузнецов Дмитрий — БЕСПЛАТНО (Минспорт)')
        self.stdout.write('  • Васильев Пётр — скидка 200₽ (300₽)')