import os
import uuid
import requests
from decimal import Decimal


class TochkaPaymentService:
    """
    Сервис оплаты через Точка Банк.

    Режимы:
    - mock        — локальная разработка, без запроса в банк
    - sandbox    — песочница Точки
    - production — боевой API Точки
    """

    def __init__(self):
        self.mode = os.getenv('TOCHKA_MODE', 'mock')

        self.api_base_url = os.getenv('TOCHKA_API_BASE_URL', '').rstrip('/')
        self.access_token = os.getenv('TOCHKA_ACCESS_TOKEN', '')
        self.customer_code = os.getenv('TOCHKA_CUSTOMER_CODE', '')
        self.account_id = os.getenv('TOCHKA_ACCOUNT_ID', '')

        self.success_url = os.getenv(
            'TOCHKA_SUCCESS_URL',
            'http://127.0.0.1:8000/payment/success/'
        )
        self.fail_url = os.getenv(
            'TOCHKA_FAIL_URL',
            'http://127.0.0.1:8000/payment/cancel/'
        )

    def create_payment_link(self, amount, description, order_id=None):
        """
        Создаёт ссылку на оплату.

        Возвращает:
        {
            'success': True/False,
            'url': 'https://...',
            'payment_id': '...',
            'error': '...'
        }
        """

        if order_id is None:
            order_id = str(uuid.uuid4())

        amount = Decimal(amount)

        if self.mode == 'mock':
            return self._create_mock_payment(amount, description, order_id)

        if self.mode in ['sandbox', 'production']:
            return self._create_real_payment(amount, description, order_id)

        return {
            'success': False,
            'error': f'Неизвестный режим TOCHKA_MODE: {self.mode}',
        }

    def _create_mock_payment(self, amount, description, order_id):
        """
        Локальная имитация оплаты.
        """
        return {
            'success': True,
            'url': self.success_url,
            'payment_id': f'mock_{order_id}',
        }

    def _create_real_payment(self, amount, description, order_id):
        """
        Реальная интеграция с API Точки.

        ВАЖНО:
        Конкретный endpoint и payload нужно сверить
        с вашим договором/кабинетом Точка Банка.
        """
        if not self.api_base_url:
            return {
                'success': False,
                'error': 'Не указан TOCHKA_API_BASE_URL',
            }

        if not self.access_token:
            return {
                'success': False,
                'error': 'Не указан TOCHKA_ACCESS_TOKEN',
            }

        url = f'{self.api_base_url}/payments'

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        payload = {
            'amount': str(amount),
            'currency': 'RUB',
            'description': description,
            'order_id': order_id,
            'success_url': self.success_url,
            'fail_url': self.fail_url,
            'customer_code': self.customer_code,
            'account_id': self.account_id,
        }

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=20,
            )
        except requests.RequestException as e:
            return {
                'success': False,
                'error': f'Ошибка соединения с Точка Банком: {e}',
            }

        if response.status_code not in [200, 201]:
            return {
                'success': False,
                'error': f'Ошибка API Точки: {response.status_code} {response.text}',
            }

        data = response.json()

        payment_url = (
            data.get('payment_url')
            or data.get('url')
            or data.get('link')
        )

        payment_id = (
            data.get('payment_id')
            or data.get('id')
            or order_id
        )

        if not payment_url:
            return {
                'success': False,
                'error': f'API Точки не вернул ссылку оплаты: {data}',
            }

        return {
            'success': True,
            'url': payment_url,
            'payment_id': payment_id,
        }