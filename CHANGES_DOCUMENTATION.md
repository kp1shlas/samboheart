# Документация изменений

## Дата: 09.11.2026

---

## Изменение 1: Скрытие детей из списка должников на дашборде владельца

### Описание
Добавлен чекбокс «Скрыть из должников» (`hide_from_debtors`) в модель `Child`. При включённом флаге ребёнок не отображается в блоке «Должники» на дашборде владельца и в отчётах.

### Затронутые файлы

#### `core/models.py` (строка 59)
- Добавлено поле `hide_from_debtors` (BooleanField, default=False) в модель `Child`
- Поле имеет `help_text` с описанием назначения

#### `core/admin.py` — `ChildAdmin` (строки 93-95, 116)
- `list_display`: добавлен столбец `hide_from_debtors`
- `list_filter`: добавлен фильтр по `hide_from_debtors`
- `list_editable`: добавлен `hide_from_debtors` (можно переключать прямо в списке)
- `fieldsets`: поле добавлено в основную секцию редактирования ребёнка

#### `core/views.py` — `owner_dashboard` (строки 1220-1231) и `owner_report` (строки 1333-1344)
- В оба запроса `debtors` добавлен фильтр `child__hide_from_debtors=False`
- Фильтр работает совместно с существующим `exclude_from_debtors=False` на уровне записи в группу

### Влияние на существующие данные
- Новое поле имеет `default=False`, все существующие записи получают значение `False`
- Никакие существующие данные не изменяются
- Миграция безопасна, не требует ручных действий

### Как использовать
1. Открыть админку Django → Дети
2. Найти нужного ребёнка
3. В списке детей поставить галочку в колонке «Скрыть из должников» (или открыть карточку ребёнка и поставить чекбокс там)
4. Ребёнок перестанет отображаться в блоке «Должники» на дашборде владельца и в отчётах

---

## Изменение 2: Регистрация и оплата мероприятий детьми без родителей

### Описание
Исправлена логика регистрации, оплаты и отмены мероприятий для детей без привязанного родителя. Также изменено поле `EventRegistration.parent` на nullable.

### Анализ текущего поведения (до изменений)

| Операция | Работала без родителя? | Примечание |
|----------|----------------------|------------|
| Регистрация (`event_register`) | Да | `parent` может быть `None` |
| Оплата (`event_pay`) | Частично | Не сохранял `order_id`, webhook мог не найти платёж |
| Отмена (`event_cancel_registration`) | **Нет** | Требовала `request.user.parent_profile` |
| Просмотр регистраций (`event_detail`) | **Нет** | Блок «Мои регистрации» показывался только родителям |

### Затронутые файлы

#### `core/models.py` — `EventRegistration.parent` (строки 446-451)
- Было: `on_delete=models.CASCADE`, без `null=True, blank=True`
- Стало: `on_delete=models.SET_NULL, null=True, blank=True`
- Позволяет создавать регистрации без привязки к родителю

#### `core/views.py` — `event_cancel_registration` (строки 1735-1751)
- Было: проверка прав только через `request.user.parent_profile`
- Стало: если пользователь — ребёнок, проверяется `registration.child == child_profile`; если родитель — `registration.parent == parent`

#### `core/views.py` — `event_detail` (строки 1642-1660)
- Добавлено вычисление `my_registrations` в зависимости от роли пользователя
- Для ребёнка: фильтрация по `child=request.user.child_profile`
- Для родителя: фильтрация по `parent=request.user.parent_profile`
- **НОВОЕ:** Добавлен запрос `participants` для получения всех зарегистрированных участников
- Передаётся в контекст шаблона для всех авторизованных пользователей

#### `templates/event_detail.html` (блоки «Мои регистрации» и «Список участников»)
- Было: `{% if user.is_authenticated and user.parent_profile %}` + inline-фильтрация
- Стало: `{% if user.is_authenticated and my_registrations %}` + цикл по переданному queryset
- **НОВОЕ:** Добавлен блок «👥 Участники» для всех авторизованных пользователей
- Отображаются короткие имена (`child.short_name`) для конфиденциальности
- Кнопка «Отменить» теперь показывается только для статуса `registered`

#### `core/views.py` — `event_pay` (строки 1798-1831)
- Выровнено по эталону `pay_for_enrollment`:
  - Добавлен `order_id=order_id` при создании Payment
  - Добавлен `bank_payment_id=order_id` при создании (временное значение)
  - После создания ссылки: `operation_id = result['payment_id']`, `bank_payment_id = operation_id or order_id`
- Это гарантирует корректное сопоставление платежа в webhook (поиск по `operation_id OR bank_payment_id`)

### Сравнение оплаты мероприятий с оплатой занятий (эталон)

Оба потока теперь используют идентичную архитектуру:

| Этап | Оплата занятий (`pay_for_enrollment`) | Оплата мероприятий (`event_pay`) |
|------|---------------------------------------|----------------------------------|
| Создание Payment | `order_id`, `bank_payment_id=order_id` | `order_id`, `bank_payment_id=order_id` |
| Платёжный шлюз | `TochkaPaymentService.create_payment_link()` | `TochkaPaymentService.create_payment_link()` |
| После ссылки | `operation_id=result['payment_id']`, `bank_payment_id=op or order_id` | `operation_id=result['payment_id']`, `bank_payment_id=op or order_id` |
| Webhook поиск | `Q(operation_id=id) \| Q(bank_payment_id=id)` | `Q(operation_id=id) \| Q(bank_payment_id=id)` |
| Обработка успеха | `settle_debts_on_payment(payment)` | `event_registration.status = 'paid'` |
| Parent nullable | Да | Да |

### Влияние на существующие данные
- `EventRegistration.parent` стало nullable — существующие записи не затрагиваются
- Логика проверки прав доступа изменена — обратная совместимость сохранена
- Формат создания платежей изменён — новые платежи будут надёжнее сопоставляться с webhook

---

## Изменение 3: Идемпотентность webhook и список участников

### Описание
Дополнительные улучшения для надёжности обработки платежей и информативности страниц событий.

### 3.1. Идемпотентность webhook (Issue #7)

#### `core/views.py` — `tochka_webhook` (строки 1929-1947)
- **Было:** Проверка `if payment.status != 'paid':` не была атомарной, повторный webhook мог вызвать двойное списание
- **Стало:** 
  - Атомарное обновление: `Payment.objects.filter(id=payment.id).exclude(status='paid').update(...)`
  - Обработка (`settle_debts_on_payment` или обновление `EventRegistration`) выполняется только если `updated > 0`
  - Обёрнуто в `transaction.atomic()` для гарантии консистентности
  - Аналогичная защита для отклонённых платежей: `Payment.objects.filter(id=payment.id, status='pending').update(status='failed')`

### 3.2. Список участников для всех пользователей (Issue #9)

#### `core/views.py` — `event_detail` (строки 1657-1661)
- Добавлен запрос `participants` для получения всех зарегистрированных участников
- Фильтрация: `status__in=['registered', 'paid', 'attended']`
- Сортировка: `order_by('registered_at')`
- Передаётся в контекст для всех авторизованных пользователей

#### `templates/event_detail.html` (блок «Список участников»)
- Добавлен новый блок после «Мои регистрации»
- Показывается всем авторизованным пользователям
- Отображает количество и короткие имена участников (`child.short_name`)
- Конфиденциальность: полные имена не раскрываются

### Влияние на существующие данные
- Изменения не затрагивают существующие данные
- Webhook теперь безопасен при повторных вызовах от банка
- Все авторизованные пользователи видят список участников событий

---

## Миграции базы данных

### `0013_merge_20261109_1952.py`
- Merge-миграция для разрешения конфликта между ветками `0011_certificate_reason_lesson_teacher` и `0012_certificate_reason`
- На продуктивной базе применять с `--fake` если колонки уже существуют

### `0014_make_event_registration_parent_nullable.py`
- Добавляет поле `hide_from_debtors` в таблицу `core_child` (BOOLEAN NOT NULL DEFAULT FALSE)
- Изменяет `EventRegistration.parent` на nullable (SET_NULL, null=True, blank=True)
- Безопасна для применения на продуктивной базе

### Команды для деплоя
```bash
# Если есть конфликт миграций (колонки teacher_id/reason уже есть в БД):
python manage.py migrate core 0013 --fake

# Применить новые изменения:
python manage.py migrate core
```

---

## Тестирование

### Проверка Issue #7 (Webhook идемпотентность)
1. Создать платёж через `pay_for_enrollment` или `event_pay`
2. Отправить webhook со статусом `PAID` дважды
3. Убедиться что `settle_debts_on_payment` вызвался только один раз
4. Проверить логи `WebhookLog` — оба вызова записаны, но обработка только один раз

### Проверка Issue #9 (Список участников)
1. Зайти как ребёнок без родителя
2. Открыть страницу события с регистрациями
3. Убедиться что блок «👥 Участники» виден
4. Проверить что отображаются только короткие имена (Фамилия И.)
