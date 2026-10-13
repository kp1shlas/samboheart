from django.db import transaction
from django.utils import timezone

from core.models import Attendance, Certificate


def _covered_by_other_certificate(certificate, lesson_date):
    """
    Проверяет, покрывает ли дату другая одобренная справка этого же ребёнка.
    Нужно, чтобы отклонение одной справки не трогало занятия,
    возвращённые по другой (пересекающейся) справке.
    """
    return Certificate.objects.filter(
        child=certificate.child,
        status='approved',
        date_from__lte=lesson_date,
        date_to__gte=lesson_date,
    ).exclude(pk=certificate.pk).exists()


def approve_certificate(certificate):
    """
    Вызывается при одобрении справки.

    - Занятия «не был» в периоде справки переводятся в «пропуск по справке».
    - Возвращаются ТОЛЬКО реально списанные занятия (was_deducted=True)
      — на баланс записи в группу (ChildEnrollment.remaining_lessons).
    - Отметки «был» не изменяются (не затираем отметку преподавателя).
    - Идемпотентно: повторный вызов ничего не меняет и возвращает 0.

    Возвращает количество возвращённых занятий.
    """
    if not certificate.date_from or not certificate.date_to:
        return 0

    with transaction.atomic():
        cert = Certificate.objects.select_for_update().get(pk=certificate.pk)

        # Повторное одобрение не должно менять баланс
        if cert.status == 'approved':
            return 0

        records = (
            Attendance.objects.select_for_update()
            .filter(
                child=cert.child,
                lesson__date__gte=cert.date_from,
                lesson__date__lte=cert.date_to,
            )
            .select_related('enrollment')
        )

        returned = 0

        for record in records:
            if record.status != 'absent':
                # «Был» не трогаем, «по справке» уже обработаны ранее
                continue

            record.status = 'excused'

            if record.was_deducted:
                enrollment = record.enrollment
                if enrollment is not None:
                    enrollment.remaining_lessons += 1
                    enrollment.save(update_fields=['remaining_lessons'])
                    record.was_deducted = False
                    returned += 1
                # Если записи в группу нет — вернуть занятие некуда,
                # просто помечаем по справке

            record.save(update_fields=['status', 'was_deducted'])

        cert.status = 'approved'
        cert.reviewed_at = timezone.now()
        cert.save(update_fields=['status', 'reviewed_at'])

    # Синхронизируем переданный объект, чтобы вьюхи видели новый статус
    certificate.status = 'approved'
    certificate.reviewed_at = cert.reviewed_at
    return returned


def reject_certificate(certificate):
    """
    Вызывается при отклонении справки.

    - Занятия «по справке» в периоде возвращаются в статус «не был».
    - Списание занятия происходит ТОЛЬКО если оно ранее было возвращено
      справкой (was_deducted=False) и на балансе есть занятия
      (баланс никогда не уходит в минус).
    - Даты, покрытые другой одобренной справкой, не трогаются.
    - Идемпотентно: повторный вызов ничего не меняет и возвращает 0.

    Возвращает количество списанных занятий.
    """
    if not certificate.date_from or not certificate.date_to:
        return 0

    with transaction.atomic():
        cert = Certificate.objects.select_for_update().get(pk=certificate.pk)

        # Повторное отклонение не должно списывать занятия второй раз
        if cert.status == 'rejected':
            return 0

        records = (
            Attendance.objects.select_for_update()
            .filter(
                child=cert.child,
                lesson__date__gte=cert.date_from,
                lesson__date__lte=cert.date_to,
                status='excused',
            )
            .select_related('enrollment')
        )

        deducted = 0

        for record in records:
            if _covered_by_other_certificate(cert, record.lesson.date):
                # Дата принадлежит другой одобренной справке — не трогаем
                continue

            enrollment = record.enrollment
            record.status = 'absent'

            if (
                not record.was_deducted
                and enrollment is not None
                and not enrollment.is_free
                and enrollment.remaining_lessons > 0
            ):
                enrollment.remaining_lessons -= 1
                enrollment.save(update_fields=['remaining_lessons'])
                record.was_deducted = True
                deducted += 1

            record.save(update_fields=['status', 'was_deducted'])

        cert.status = 'rejected'
        cert.reviewed_at = timezone.now()
        cert.save(update_fields=['status', 'reviewed_at'])

    certificate.status = 'rejected'
    certificate.reviewed_at = cert.reviewed_at
    return deducted