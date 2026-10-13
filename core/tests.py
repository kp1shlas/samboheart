from datetime import date, time

from django.test import TestCase

from core.models import (
    Attendance, Certificate, Child, ChildEnrollment, Group,
    Lesson, ParentProfile, TeacherProfile, User,
)
from core.services.certificates import approve_certificate, reject_certificate
from core.services.debts import settle_debts_on_payment


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
    """Тесты начисления занятий при оплате (серверная логика долгов)."""

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
        result = settle_debts_on_payment(self.payment)
        self.enrollment.refresh_from_db()
        self.assertEqual(result['remaining_to_add'], 8)
        self.assertEqual(self.enrollment.remaining_lessons, 8)

    def test_negative_balance_is_covered_first(self):
        """Оплата сначала покрывает отрицательный баланс (долг за прогулы)."""
        self.enrollment.remaining_lessons = -3
        self.enrollment.save()

        result = settle_debts_on_payment(self.payment)

        self.enrollment.refresh_from_db()
        self.assertEqual(result['negative_debt_covered'], 3)
        # 8 оплачено → 3 на покрытие долга, 5 в баланс; −3 + 3 + 5 = 5
        self.assertEqual(result['remaining_to_add'], 5)
        self.assertEqual(self.enrollment.remaining_lessons, 5)

    def test_is_debt_records_settled(self):
        """Записи is_debt=True погашаются за счёт оплаты."""
        from core.models import Attendance, Lesson, Payment
        lesson = Lesson.objects.create(
            group=self.group, date=date(2026, 1, 5), start_time=time(10, 0)
        )
        Attendance.objects.create(
            lesson=lesson, child=self.child, enrollment=self.enrollment,
            status='present', was_deducted=False, is_debt=True,
        )

        result = settle_debts_on_payment(self.payment)

        self.enrollment.refresh_from_db()
        self.assertEqual(result['debts_settled'], 1)
        # 8 оплачено − 1 долг = 7 в баланс
        self.assertEqual(self.enrollment.remaining_lessons, 7)
        record = Attendance.objects.get(lesson=lesson, child=self.child)
        self.assertFalse(record.is_debt)
        self.assertTrue(record.was_deducted)

    def test_no_enrollment_found(self):
        """Платёж без записи в группу не роняет ошибку."""
        from core.models import Payment
        payment = Payment.objects.create(
            parent=self.parent, child=self.child, enrollment=None,
            amount=1000, lessons_count=1, status='paid', method='cash',
        )
        result = settle_debts_on_payment(payment)
        self.assertEqual(result['remaining_to_add'], 1)
        self.assertEqual(result['negative_debt_covered'], 0)

