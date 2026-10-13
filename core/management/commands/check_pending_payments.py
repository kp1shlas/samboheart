"""
Резервная проверка зависших платежей через API Точки.
Запускается по cron раз в час.

Логика:
1. Проверяем ВСЕ pending платежи через API (независимо от возраста)
2. Если APPROVED -> paid (начисляем занятия)
3. Если не APPROVED -> смотрим возраст:
   - >24ч -> failed
   - <24ч -> оставляем pending (ждём оплаты)
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q

from core.models import Payment
from core.services.tochka import TochkaPaymentService
from core.services.debts import settle_debts_on_payment


class Command(BaseCommand):
    help = 'Проверяет зависшие pending-платежи через API банка'

    def add_arguments(self, parser):
        parser.add_argument(
            '--min-age', type=int, default=15,
            help='Минимальный возраст платежа для проверки (в минутах)'
        )
        parser.add_argument(
            '--expire-hours', type=int, default=24,
            help='Через сколько часов помечать как failed (если не оплачен)'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Только показать, не изменять данные'
        )

    def handle(self, *args, **options):
        min_age_minutes = options['min_age']
        expire_hours = options['expire_hours']
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('Режим DRY-RUN (без изменений)'))

        threshold_check = timezone.now() - timedelta(minutes=min_age_minutes)
        threshold_expire = timezone.now() - timedelta(hours=expire_hours)

        pending_count = Payment.objects.filter(
            status='pending',
            method='online',
        ).count()

        if pending_count == 0:
            self.stdout.write(self.style.SUCCESS('Нет pending платежей. Завершено.'))
            return

        self.stdout.write(self.style.WARNING(
            f'Найдено pending платежей: {pending_count}'
        ))

        candidates = Payment.objects.filter(
            status='pending',
            method='online',
            created_at__lt=threshold_check,
        ).exclude(
            Q(operation_id='') & Q(bank_payment_id='') & Q(order_id='')
        )

        candidates_count = candidates.count()

        if candidates_count == 0:
            self.stdout.write(self.style.SUCCESS(
                f'Все pending платежи свежие (< {min_age_minutes} мин). Проверка не нужна.'
            ))
            return

        self.stdout.write(self.style.WARNING(
            f'Кандидатов на проверку: {candidates_count}'
        ))

        service = TochkaPaymentService()
        fixed = 0
        expired = 0
        still_pending = 0
        api_errors = 0

        for payment in candidates:
            # ШАГ 1: Всегда проверяем через API (независимо от возраста)
            approved = False
            
            for pid in {payment.operation_id, payment.bank_payment_id, payment.order_id}:
                if not pid:
                    continue

                result = service.check_payment_status(pid)

                if not result.get('success'):
                    continue  # Пробуем следующий ID

                status = result.get('status')

                if status == 'UNKNOWN':
                    continue  # Пробуем следующий ID

                if status in ['APPROVED', 'SUCCESS', 'PAID', 'paid']:
                    # Платёж оплачен в Точке
                    if not dry_run:
                        payment.status = 'paid'
                        payment.paid_at = timezone.now()
                        payment.save()

                        if payment.event_registration:
                            payment.event_registration.status = 'paid'
                            payment.event_registration.paid_at = timezone.now()
                            payment.event_registration.save()
                        else:
                            settle_debts_on_payment(payment)

                    age_hours = (timezone.now() - payment.created_at).total_seconds() / 3600
                    self.stdout.write(self.style.SUCCESS(
                        f'  #{payment.id} ({payment.child.full_name}, {payment.amount}₽) '
                        f'-> paid (возраст {age_hours:.1f}ч)'
                    ))
                    fixed += 1
                    approved = True
                    break

                elif status in ['REJECTED', 'CANCELLED', 'FAILED', 'EXPIRED']:
                    # Платёж отклонён в Точке
                    if not dry_run:
                        payment.status = 'failed'
                        payment.save()

                    self.stdout.write(self.style.WARNING(
                        f'  #{payment.id} -> failed (статус в Точке: {status})'
                    ))
                    expired += 1
                    approved = True
                    break
            
            if approved:
                continue

            # ШАГ 2: Если API не дал ответ — смотрим возраст
            if payment.created_at < threshold_expire:
                # Платёж старше 24 часов и не оплачен -> failed
                if not dry_run:
                    payment.status = 'failed'
                    payment.save()

                age_hours = (timezone.now() - payment.created_at).total_seconds() / 3600
                self.stdout.write(self.style.WARNING(
                    f'  #{payment.id} ({payment.child.full_name}) '
                    f'просрочен ({age_hours:.1f}ч > {expire_hours}ч) -> failed'
                ))
                expired += 1
            else:
                # Платёж свежий, оставляем pending
                age_hours = (timezone.now() - payment.created_at).total_seconds() / 3600
                self.stdout.write(
                    f'  #{payment.id} ({payment.child.full_name}) '
                    f'ожидает оплаты ({age_hours:.1f}ч)'
                )
                still_pending += 1

        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS(
            f'ИТОГО: оплачено {fixed}, failed {expired}, '
            f'pending {still_pending}'
        ))
        self.stdout.write(self.style.SUCCESS('=' * 60))
