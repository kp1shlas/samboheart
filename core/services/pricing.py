from decimal import Decimal
from django.utils import timezone
from core.models import ChildDiscount


def calculate_discounted_price(enrollment, base_price):
    """
    Рассчитывает цену со скидкой для записи в группу.
    
    Параметры:
        enrollment: ChildEnrollment
        base_price: Decimal — базовая цена
    
    Возвращает: {
        'original_price': Decimal,
        'discounted_price': Decimal,
        'discount': Decimal,
        'discount_info': str (описание скидки)
    }
    """
    today = timezone.now().date()
    
    # Находим активную скидку на сегодня для этой записи
    discount = ChildDiscount.objects.filter(
        enrollment=enrollment,
        is_active=True,
        valid_from__lte=today,
        valid_until__gte=today
    ).first()
    
    if not discount:
        return {
            'original_price': base_price,
            'discounted_price': base_price,
            'discount': Decimal('0'),
            'discount_info': None
        }
    
    # Применяем скидку
    if discount.discount_type == 'free':
        discounted = Decimal('0')
        discount_amount = base_price
        info = f'Бесплатно ({discount.reason})'
    
    elif discount.discount_type == 'percent':
        discount_percent = discount.discount_value / Decimal('100')
        discount_amount = base_price * discount_percent
        discounted = base_price - discount_amount
        info = f'Скидка {discount.discount_value}% ({discount.reason})'
    
    elif discount.discount_type == 'fixed':
        discount_amount = min(discount.discount_value, base_price)
        discounted = base_price - discount_amount
        info = f'Скидка {discount.discount_value}₽ ({discount.reason})'
    
    else:
        discounted = base_price
        discount_amount = Decimal('0')
        info = None
    
    return {
        'original_price': base_price,
        'discounted_price': max(Decimal('0'), discounted),
        'discount': discount_amount,
        'discount_info': info
    }