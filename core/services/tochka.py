"""
Сервис оплаты через Точка Банк (интернет-эквайринг)

Режимы:
- mock       — локальная разработка
- sandbox    — песочница Точки
- production — боевой API
"""
import os
import uuid
import requests
import urllib3
from decimal import Decimal

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TochkaPaymentService:
    def __init__(self):
        self.mode = os.getenv('TOCHKA_MODE', 'mock')
        self.api_base = 'https://enter.tochka.com/uapi'
        
        self.jwt_token = os.getenv('TOCHKA_JWT_TOKEN', '')
        self.merchant_id = os.getenv('TOCHKA_MERCHANT_ID', '')
        self.customer_code = os.getenv('TOCHKA_CUSTOMER_CODE', '')
        
        self.success_url = os.getenv('TOCHKA_SUCCESS_URL', 'https://samboheart.ru/payment/success/')
        self.fail_url = os.getenv('TOCHKA_FAIL_URL', 'https://samboheart.ru/payment/cancel/')
    
    def _headers(self):
        return {
            'Authorization': f'Bearer {self.jwt_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
    
    def create_payment_link(self, amount, description, order_id=None):
        """Создаёт ссылку на оплату через API интернет-эквайринга"""
        if order_id is None:
            order_id = str(uuid.uuid4())[:8]
        
        amount = Decimal(amount)
        
        if self.mode == 'mock' or not self.jwt_token:
            return self._create_mock_payment(amount, description, order_id)
        
        return self._create_real_payment(amount, description, order_id)
    
    def _create_mock_payment(self, amount, description, order_id):
        """Mock-оплата для локальной разработки"""
        mock_url = 'https://samboheart.ru/payment/mock/'
        return {
            'success': True,
            'url': mock_url,
            'payment_id': f'mock_{order_id}',
        }
    
    def _create_real_payment(self, amount, description, order_id):
        """Создание платёжной ссылкики через API интернет-эквайринга"""
        
        if not self.jwt_token:
            return {'success': False, 'error': 'Не указан TOCHKA_JWT_TOKEN'}
        
        if not self.merchant_id:
            return {'success': False, 'error': 'Не указан TOCHKA_MERCHANT_ID'}
        
        if not self.customer_code:
            return {'success': False, 'error': 'Не указан TOCHKA_CUSTOMER_CODE'}
        
        # Транслитерируем описание
        translit_map = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e',
            'ё': 'yo', 'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k',
            'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
            'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'c',
            'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '',
            'э': 'e', 'ю': 'yu', 'я': 'ya',
        }
        
        purpose_en = ''
        for char in description.lower():
            if char in translit_map:
                purpose_en += translit_map[char]
            elif char.isalpha() and char.isascii():
                purpose_en += char
            elif char in ' 0123456789.,!?-':
                purpose_en += char
        
        purpose_en = purpose_en[:140]
        
        url = f'{self.api_base}/acquiring/v1.0/payments'
        
        payload = {
            'Data': {
                'customerCode': self.customer_code,
                'merchantId': self.merchant_id,
                'amount': float(amount),
                'currency': 'RUB',
                'purpose': purpose_en,
                'paymentMode': ['sbp', 'card'],
                'redirectUrl': self.success_url,
                'failRedirectUrl': self.fail_url,
                'paymentLinkId': order_id,
                'ttl': 10080,  # 7 дней
            }
        }
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=20,
                verify=False,
            )
        except requests.RequestException as e:
            return {
                'success': False,
                'error': f'Ошибка соединения: {e}',
            }
        
        if response.status_code not in [200, 201]:
            return {
                'success': False,
                'error': f'Ошибка API: {response.status_code} {response.text[:500]}',
            }
        
        data = response.json()
        payment_data = data.get('Data', {})
        
        payment_link = payment_data.get('paymentLink')
        operation_id = payment_data.get('operationId')
        
        if not payment_link:
            return {
                'success': False,
                'error': f'API не вернул ссылку: {data}',
            }
        
        return {
            'success': True,
            'url': payment_link,
            'payment_id': operation_id or order_id,
        }
    
    def check_payment_status(self, operation_id):
        """Проверяет статус платежа по operationId"""
        if self.mode == 'mock':
            return {
                'success': True,
                'status': 'APPROVED',
            }
        
        if not self.jwt_token:
            return {'success': False, 'error': 'Не указан TOCHKA_JWT_TOKEN'}
        
        url = f'{self.api_base}/acquiring/v1.0/payments/{operation_id}'
        
        try:
            response = requests.get(
                url,
                headers=self._headers(),
                timeout=10,
                verify=False,
            )
        except requests.RequestException as e:
            return {
                'success': False,
                'error': f'Ошибка соединения: {e}',
            }
        
        if response.status_code != 200:
            return {
                'success': False,
                'error': f'Ошибка API: {response.status_code}',
            }
        
        data = response.json()
        status = data.get('Data', {}).get('status', 'UNKNOWN')
        
        return {
            'success': True,
            'status': status,
        }
