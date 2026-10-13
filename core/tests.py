from datetime import date, time

from django.test import TestCase

from core.models import (
    Attendance, Certificate, Child, ChildEnrollment, Group,
    Lesson, ParentProfile, TeacherProfile, User,
)
from core.services.certificates import approve_certificate, reject_certificate
from core.services.debts import credit_lessons_on_payment, settle_debts_on_payment


class CertificateServiceTests(TestCase):
    """Тесты исправленной логики подтверждения справок."""

    def setUp(self):
        parent_user = User.objects.create_user(username='parent1', password='x')
        self.parent = ParentProfile.objects.create(user=parent_user)
        self.child = Child.objects.create(
            parent=self.parent, full_name='Иванов Иван'
        )
        teacher_user = User.objects.create_user(username='teacher1', password='x')
        teacher = TeacherProfile.objects.create(user=teacher_user)
        self.group = Group.objects.create(
            teacher=teacher, price_per_lesson=1000, lessons_per_month=8
        )
        self.enrollment = ChildEnrollment.objects.create(
            child=self.child, group=self.group, remaining_lessons=4
        )

    def _lesson(self, day):
        return Lesson.objects.create(
            group=self.group, date=date(2026, 1, day), start_time=time(10, 0)
        )

    def _attendance(self, day, status, was_deducted):
        return Attendance.objects.create(
            lesson=self._lesson(day), child=self.child,
            enrollment=self.enrollment,
            status=status, was_deducted=was_deducted,
        )

    def _certificate(self, day_from, day_to, status='pending'):
        return Certificate.objects.create(
            child=self.child,
            file='certificates/test.pdf',
            date_from=date(2026, 1, day_from),
            date_to=date(2026, 1, day_to),
            status=status,
        )

    def test_approve_returns_only_actually_deducted(self):
        """Возвращаются только реально списанные занятия (was_deducted=True)."""
        self._attendance(5, 'absent', was_deducted=True)   # списано → вернётся
        self._attendance(6, 'absent', was_deducted=False)  # не списывалось → не вернётся
        self._attendance(7, 'present', was_deducted=True)  # «был» не трогаем

        cert = self._certificate(1, 10)
        returned = approve_certificate(cert)

        self.enrollment.refresh_from_db()
        self.assertEqual(returned, 1)
        self.assertEqual(self.enrollment.remaining_lessons, 5)
        self.assertEqual(cert.status, 'approved')

    def test_approve_does_not_use_child_model(self):
        """Баланс хранится в ChildEnrollment, а не в Child (был AttributeError)."""
        self._attendance(5, 'absent', was_deducted=True)
        cert = self._certificate(1, 10)
        # Раньше здесь падало: Child не имеет атрибута remaining_lessons
        approve_certificate(cert)
        self.assertFalse(hasattr(self.child, 'remaining_lessons'))

    def test_approve_is_idempotent(self):
        """Повторное одобрение не увеличивает баланс второй раз."""
        self._attendance(5, 'absent', was_deducted=True)
        cert = self._certificate(1, 10)

        approve_certificate(cert)
        approve_certificate(cert)  # повторный вызов

        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.remaining_lessons, 5)

    def test_reject_returns_status_and_deducts(self):
        """Отклонение возвращает «не был» и списывает занятие."""
        record = self._attendance(5, 'excused', was_deducted=False)

        cert = self._certificate(1, 10, status='approved')
        deducted = reject_certificate(cert)

        record.refresh_from_db()
        self.enrollment.refresh_from_db()
        self.assertEqual(deducted, 1)
        self.assertEqual(record.status, 'absent')
        self.assertTrue(record.was_deducted)
        self.assertEqual(self.enrollment.remaining_lessons, 3)
        self.assertEqual(cert.status, 'rejected')

    def test_reject_never_goes_negative(self):
        """Баланс не уходит в минус при отклонении справки."""
        self.enrollment.remaining_lessons = 0
        self.enrollment.save()
        record = self._attendance(5, 'excused', was_deducted=False)

        cert = self._certificate(1, 10, status='approved')
        deducted = reject_certificate(cert)

        record.refresh_from_db()
        self.enrollment.refresh_from_db()
        self.assertEqual(deducted, 0)
        self.assertEqual(record.status, 'absent')
        self.assertFalse(record.was_deducted)
        self.assertEqual(self.enrollment.remaining_lessons, 0)

    def test_reject_does_not_touch_dates_of_other_cert(self):
        """Отклонение не трогает даты, покрытые другой одобренной справкой."""
        self._attendance(5, 'excused', was_deducted=False)

        # Первая (другая) одобренная справка покрывает 5 января
        self._certificate(1, 10, status='approved')
        cert2 = self._certificate(1, 10, status='approved')

        deducted = reject_certificate(cert2)

        self.assertEqual(deducted, 0)
        self.assertEqual(self.enrollment.remaining_lessons, 4)

    def test_reject_is_idempotent(self):
        """Повторное отклонение не списывает занятия второй раз."""
        self._attendance(5, 'excused', was_deducted=False)
        cert = self._certificate(1, 10, status='approved')

        reject_certificate(cert)
        reject_certificate(cert)

        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.remaining_lessons, 3)


class PaymentCreditTests(TestCase):
    """Тесты начисления занятий при оплате (логика is_debt удалена)."""

    def setUp(self):
        from core.models import Payment
        parent_user = User.objects.create_user(username='parent2', password='x')
        self.parent = ParentProfile.objects.create(user=parent_user)
        self.child = Child.objects.create(
            parent=self.parent, full_name='Петров Пётр'
        )
        teacher_user = User.objects.create_user(username='teacher2', password='x')
        teacher = TeacherProfile.objects.create(user=teacher_user)
        self.group = Group.objects.create(
            teacher=teacher, price_per_lesson=1000, lessons_per_month=8
        )
        self.enrollment = ChildEnrollment.objects.create(
            child=self.child, group=self.group, remaining_lessons=0
        )
        self.payment = Payment.objects.create(
            parent=self.parent, child=self.child, enrollment=self.enrollment,
            amount=8000, lessons_count=8, status='paid', method='cash',
        )

    def test_credit_adds_lessons(self):
        result = credit_lessons_on_payment(self.payment)
        self.enrollment.refresh_from_db()
        self.assertEqual(result['lessons_credited'], 8)
        self.assertEqual(self.enrollment.remaining_lessons, 8)

    def test_legacy_name_still_works(self):
        """settle_debts_on_payment — совместимость, но без долгов."""
        result = settle_debts_on_payment(self.payment)
        self.enrollment.refresh_from_db()
        self.assertEqual(result['debts_settled'], 0)
        self.assertEqual(self.enrollment.remaining_lessons, 8)

    def test_no_enrollment_found(self):
        """Платёж без записи в группу не роняет ошибку."""
        from core.models import Payment
        payment = Payment.objects.create(
            parent=self.parent, child=self.child, enrollment=None,
            amount=1000, lessons_count=1, status='paid', method='cash',
        )
        ChildEnrollment.objects.all().delete()
        result = credit_lessons_on_payment(payment)
        self.assertEqual(result['lessons_credited'], 0)

