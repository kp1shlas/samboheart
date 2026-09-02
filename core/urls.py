from django.conf import settings
from django.urls import path, include
from django.conf.urls.static import static
from . import views

urlpatterns = [
    # ─── Главная и аутентификация ──────────────────────
     path('', views.home_view, name='home'),
     path('login/', views.login_view, name='login'),
     path('logout/', views.logout_view, name='logout'),
     path('register/', views.register_view, name='register'),
     path('welcome/', views.welcome_view, name='welcome'),
     path('change-password/', views.change_password, name='change_password'),
     path('oauth/', include('social_django.urls', namespace='social')),

    # ─── Дашборды ──────────────────────────────────────
     path('dashboard/', views.dashboard, name='dashboard'),
     path('parent/', views.parent_dashboard, name='parent_dashboard'),
     path('child/dashboard/', views.child_dashboard, name='child_dashboard'),
     path('child/<int:child_id>/', views.child_detail, name='child_detail'),
     path('teacher/', views.teacher_dashboard, name='teacher_dashboard'),
     path('child/certificate/upload/', views.child_upload_certificate, name='child_upload_certificate'),

    # ─── Преподаватель: занятия ────────────────────────
     path('teacher/group/<int:group_id>/lessons/',
         views.group_lessons, name='group_lessons'),
     path('teacher/group/<int:group_id>/attendance/',
         views.attendance_sheet, name='attendance_sheet'),
     path('teacher/lesson/<int:lesson_id>/attendance/',
         views.attendance_sheet_for_lesson,
         name='attendance_sheet_for_lesson'),

    # ─── Оплата ────────────────────────────────────────
     path('pay/', views.pay_view, name='pay'),
     path('enrollment/<int:enrollment_id>/pay/<str:tariff_code>/',
         views.pay_for_enrollment, name='pay_for_enrollment'),
     path('payment/mock-success/',
         views.payment_mock_success, name='payment_mock_success'),
     path('payment/success/', views.payment_success, name='payment_success'),
     path('payment/cancel/', views.payment_cancel, name='payment_cancel'),
     path('events/registration/<int:registration_id>/pay/',
         views.event_pay, name='event_pay'),
     path('payments/history/', views.payment_history, name='payment_history'),
     path('payment/tochka/webhook/', views.tochka_webhook, name='tochka_webhook'),
     path('payment/mock/', views.payment_mock_view, name='payment_mock'),
     path('payment/mock/confirm/', views.payment_mock_confirm, name='payment_mock_confirm'),

    # ─── Владелец ──────────────────────────────────────
     path('owner/', views.owner_dashboard, name='owner_dashboard'),
     path('owner/report/', views.owner_report, name='owner_report'),
     path('owner/cash-payment/',
         views.owner_cash_payment, name='owner_cash_payment'),
     path('owner/certificates/',
         views.owner_certificates, name='owner_certificates'),
     path('owner/groups/', views.owner_groups, name='owner_groups'),
     path('owner/groups/add/', views.owner_add_group, name='owner_add_group'),
     path('owner/generate-lessons/',
        views.owner_generate_lessons, name='owner_generate_lessons'),
     path('owner/import-children/',
         views.owner_import_children, name='owner_import_children'),

    # ─── Новости и события ─────────────────────────────
     path('news/', views.news_list, name='news_list'),
     path('news/<int:pk>/', views.news_detail, name='news_detail'),
     path('events/', views.events_list, name='events_list'),
     path('events/<int:pk>/', views.event_detail, name='event_detail'),
     path('events/<int:event_id>/register/',
         views.event_register, name='event_register'),
     path('events/registration/<int:registration_id>/cancel/',
         views.event_cancel_registration, name='event_cancel_registration'),
]

# Медиа-файлы в режиме разработки
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )