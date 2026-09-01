"""
Сервис оплаты через СБП Точка Банк.

Режимы:
- mock       — локальная разработка
- sandbox    — песочница Точки
- production — боевой API
"""
import os
import uuid
import requests
import base64
from decimal import Decimal


class TochkaPaymentService:
    def __init__(self):
        self.mode = os.getenv('TOCHKA_MODE', 'mock')
        
        # Базовые URL
        self.api_urls = {
            'mock': 'http://localhost',
            'sandbox': 'https://api.sandbox.tochka.com',
            'production': 'https://api.tochka.com',
        }
        
        self.api_base = self.api_urls.get(self.mode, self.api_urls['production'])
        self.jwt_token = os.getenv('TOCHKA_JWT_TOKEN', '')
        self.merchant_id = os.getenv('TOCHKA_MERCHANT_ID', '')
        self.account_id = os.getenv('TOCHKA_ACCOUNT_ID', '')
        
        self.success_url = os.getenv('TOCHKA_SUCCESS_URL')
        self.fail_url = os.getenv('TOCHKA_FAIL_URL')
    
    def _headers(self):
        """Заголовки для запросов к API"""
        return {
            'Authorization': f'Bearer {self.jwt_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
    
    def create_payment_link(self, amount, description, order_id=None):
        """
        Создаёт QR-код для оплаты через СБП.
        
        Возвращает:
        {
            'success': True/False,
            'qrc_id': '...',
            'qr_image': 'data:image/png;base64,...',
            'payload': 'https://qr.nspk.ru/...',
            'error': '...'
        }
        """
        if order_id is None:
            order_id = str(uuid.uuid4())
        
        amount = Decimal(amount)
        
        if self.mode == 'mock':
            return self._create_mock_payment(amount, description, order_id)
        
        return self._create_sbp_payment(amount, description, order_id)
    
    def _create_mock_payment(self, amount, description, order_id):
    # Возвращаем ссылку на нашу страницу mock-оплаты
    # Payment ID будет передан через сессию
        mock_url = 'https://samboheart.ru/payment/mock/'
        return {
           'success': True,
            'url': mock_url,
            'payment_id': f'mock_{order_id}',
        }
    
    def _create_sbp_payment(self, amount, description, order_id):
        """Создание реального QR-кода через СБП"""
        
        if not self.jwt_token:
            return {'success': False, 'error': 'Не указан TOCHKA_JWT_TOKEN'}
        
        if not self.merchant_id:
            return {'success': False, 'error': 'Не указан TOCHKA_MERCHANT_ID'}
        
        if not self.account_id:
            return {'success': False, 'error': 'Не указан TOCHKA_ACCOUNT_ID'}
        
        url = f'{self.api_base}/sbp/v1.0/qr-code/merchant/{self.merchant_id}/account/{self.account_id}'
        
        payload = {
            'amount': str(amount),
            'currency': 'RUB',
            'comment': description[:100],  # Ограничение длины
            'qrc_type': 'QRDynamic',
        }
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=20,
            )
        except requests.RequestException as e:
            return {
                'success': False,
                'error': f'Ошибка соединения: {e}',
            }
        
        if response.status_code not in [200, 201]:
            return {
                'success': False,
                'error': f'Ошибка API: {response.status_code} {response.text}',
            }
        
        data = response.json()
        
        qrc_id = data.get('qrc_id')
        qr_image_base64 = data.get('qr_image')
        payload_url = data.get('payload')
        
        if not qrc_id:
            return {
                'success': False,
                'error': f'API не вернул qrc_id: {data}',
            }
        
        # Формируем data URL для изображения
        qr_image = None
        if qr_image_base64:
            qr_image = f'data:image/png;base64,{qr_image_base64}'
        
        return {
            'success': True,
            'qrc_id': qrc_id,
            'qr_image': qr_image,
            'payload': payload_url,
        }
    
    def check_payment_status(self, qrc_id):
        """
        Проверяет статус оплаты по qrc_id.
        
        Возвращает:
        {
            'success': True/False,
            'status': 'QR_PAID' / 'QR_NOT_PAID' / 'QR_EXPIRED' / ...,
            'error': '...'
        }
        """
        if self.mode == 'mock':
            return {
                'success': True,
                'status': 'QR_NOT_PAID',
            }
        
        if not self.jwt_token:
            return {'success': False, 'error': 'Не указан TOCHKA_JWT_TOKEN'}
        
        url = f'{self.api_base}/sbp/v1.0/qr-codes/{qrc_id}/payment-status'
        
        try:
            response = requests.get(
                url,
                headers=self._headers(),
                timeout=10,
            )
        except requests.RequestException as e:
            return {
                'success': False,
                'error': f'Ошибка соединения: {e}',
            }
        
        if response.status_code != 200:
            return {
                'success': False,
                'error': f'Ошибка API: {response.status_code} {response.text}',
            }
        
        data = response.json()
        
        # API возвращает массив статусов
        qr_statuses = data.get('qr_statuses', [])
        
        if not qr_statuses:
            return {
                'success': False,
                'error': f'API не вернул статусы: {data}',
            }
        
        # Берём первый статус (у нас один QR-код)
        status = qr_statuses[0].get('status', 'UNKNOWN')
        
        return {
            'success': True,
            'status': status,
        }