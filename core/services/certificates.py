from core.models import Attendance, Certificate


def approve_certificate(certificate):
    """
    Вызывается при одобрении справки.
    Находит занятия в периоде и помечает как «по справке».
    Возвращает количество возвращённых занятий.
    """
    child = certificate.child
    date_from = certificate.date_from
    date_to = certificate.date_to

    if not date_from or not date_to:
        return 0

    attendance_records = Attendance.objects.filter(
        child=child,
        lesson__date__gte=date_from,
        lesson__date__lte=date_to,
    )

    returned_lessons = 0

    for record in attendance_records:
        if record.status == 'absent':
            record.status = 'excused'
            record.save()
            child.remaining_lessons += 1
            returned_lessons += 1
        elif record.status == 'present':
            record.status = 'excused'
            record.save()

    if returned_lessons > 0:
        child.save()

    return returned_lessons


def reject_certificate(certificate):
    """
    Вызывается при отклонении справки.
    Возвращает статус «не был» и списывает занятия.
    """
    child = certificate.child
    date_from = certificate.date_from
    date_to = certificate.date_to

    if not date_from or not date_to:
        return 0

    attendance_records = Attendance.objects.filter(
        child=child,
        lesson__date__gte=date_from,
        lesson__date__lte=date_to,
        status='excused',
    )

    deducted_lessons = 0

    for record in attendance_records:
        record.status = 'absent'
        record.save()
        child.remaining_lessons = max(0, child.remaining_lessons - 1)
        deducted_lessons += 1

    if deducted_lessons > 0:
        child.save()

    return deducted_lessons