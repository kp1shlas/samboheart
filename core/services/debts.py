from django.db import transaction

from core.models import ChildEnrollment, Payment


def credit_lessons_on_payment(payment):
    """
    Начисляет оплаченные занятия на баланс записи в группу.

    Логика «занятий в долг» (Attendance.is_debt) УДАЛЕНА:
    оплата просто увеличивает ChildEnrollment.remaining_lessons.

    Возвращает {'lessons_credited': int, 'enrollment': ChildEnrollment|None}
    """
    with transaction.atomic():
        # Блокируем платёж, чтобы параллельные вызовы (webhook + возврат
        # пользователя) не начислили занятия дважды
        payment = (
            Payment.objects.select_for_update()
            .select_related('enrollment')
            .get(pk=payment.pk)
        )

        enrollment = payment.enrollment

        if enrollment is None:
            # Если запись не привязана — берём самую свежую активную запись ребёнка
            enrollment = (
                ChildEnrollment.objects.select_for_update()
                .filter(child=payment.child, is_active=True)
                .order_by('-enrolled_at')
                .first()
            )

        if enrollment is None:
            return {'lessons_credited': 0, 'enrollment': None}

        enrollment.remaining_lessons += payment.lessons_count
        enrollment.save(update_fields=['remaining_lessons'])

        return {
            'lessons_credited': payment.lessons_count,
            'enrollment': enrollment,
        }


def settle_debts_on_payment(payment):
    """
    Устаревшее имя (обратная совместимость).
    Теперь просто начисляет занятия — логика долгов удалена.
    """
    result = credit_lessons_on_payment(payment)
    return {
        'debts_settled': 0,
        'remaining_to_add': result['lessons_credited'],
        'lessons_credited': result['lessons_credited'],
    }