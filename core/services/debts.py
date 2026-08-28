from core.models import Attendance, ChildEnrollment, Payment


def settle_debts_on_payment(payment):
    """
    При оплате сначала списывает занятия "в долг" для данной записи,
    потом начисляет остаток.
    """
    enrollment = payment.enrollment
    lessons_paid = payment.lessons_count
    
    # Находим все долги этой записи
    debts = Attendance.objects.filter(
        enrollment=enrollment,
        is_debt=True,
    ).order_by('lesson__date')
    
    debts_settled = 0
    remaining_to_add = lessons_paid
    
    for debt in debts:
        if remaining_to_add <= 0:
            break
        
        # Погашаем долг
        debt.is_debt = False
        debt.was_deducted = True
        debt.save()
        debts_settled += 1
        remaining_to_add -= 1
    
    # Остаток идёт в баланс записи
    if remaining_to_add > 0:
        enrollment.remaining_lessons += remaining_to_add
        enrollment.save()
    
    return {
        'debts_settled': debts_settled,
        'remaining_to_add': remaining_to_add,
    }