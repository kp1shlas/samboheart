from core.models import Attendance, ChildEnrollment, Payment


def settle_debts_on_payment(payment):
    """
    При оплате:
    1. Сначала покрывает отрицательный баланс (долг за прогулы)
    2. Потом погашает записи "был без оплаты" (is_debt=True)
    3. Остаток идёт в баланс записи
    """
    enrollment = payment.enrollment
    if not enrollment:
        return {
            'negative_debt_covered': 0,
            'debts_settled': 0,
            'remaining_to_add': payment.lessons_count,
        }

    lessons_paid = payment.lessons_count
    remaining_to_add = lessons_paid

    # ШАГ 1: Покрываем отрицательный баланс (долг за прогулы)
    negative_debt_covered = 0
    if enrollment.remaining_lessons < 0:
        debt_amount = abs(enrollment.remaining_lessons)
        cover_amount = min(remaining_to_add, debt_amount)
        enrollment.remaining_lessons += cover_amount
        remaining_to_add -= cover_amount
        negative_debt_covered = cover_amount

    # ШАГ 2: Погашаем записи "был без оплаты" (is_debt=True)
    debts = Attendance.objects.filter(
        enrollment=enrollment,
        is_debt=True,
    ).order_by('lesson__date')

    debts_settled = 0
    for debt in debts:
        if remaining_to_add <= 0:
            break
        debt.is_debt = False
        debt.was_deducted = True
        debt.save()
        debts_settled += 1
        remaining_to_add -= 1

    # ШАГ 3: Остаток идёт в баланс записи
    if remaining_to_add > 0:
        enrollment.remaining_lessons += remaining_to_add

    enrollment.save()

    return {
        'negative_debt_covered': negative_debt_covered,
        'debts_settled': debts_settled,
        'remaining_to_add': remaining_to_add,
    }