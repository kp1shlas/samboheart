import json
import logging
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils import timezone

logger = logging.getLogger(__name__)

@csrf_exempt
def tochka_webhook(request):
    """Webhook от Точка Банка с максимальной совместимостью"""
    
    # GET — health check
    if request.method == 'GET':
        return JsonResponse({'status': 'ok'}, status=200)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        raw_body = request.body.decode('utf-8', errors='replace')
        logger.info(f"[WEBHOOK] Body: {raw_body[:1000]}")
    except Exception as e:
        logger.error(f"[WEBHOOK] Error reading body: {e}")
        return JsonResponse({'ok': True}, status=200)
    
    if not raw_body or raw_body.strip() == '':
        logger.info("[WEBHOOK] Empty body - returning 200")
        return JsonResponse({'ok': True}, status=200)
    
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("[WEBHOOK] Not JSON - returning 200")
        return JsonResponse({'ok': True}, status=200)
    
    if not isinstance(payload, dict) or len(payload) == 0:
        logger.info("[WEBHOOK] Empty payload - returning 200")
        return JsonResponse({'ok': True}, status=200)
    
    # Ищем payment_id
    payment_id = (
        payload.get('id') or
        payload.get('payment_id') or
        payload.get('operation_id') or
        payload.get('operationId') or
        payload.get('paymentLinkId') or
        payload.get('bank_payment_id')
    )
    
    status = payload.get('status') or payload.get('paymentStatus')
    
    if not payment_id:
        logger.warning(f"[WEBHOOK] No payment_id - treating as health check")
        return JsonResponse({'ok': True}, status=200)

    payment = Payment.objects.filter(bank_payment_id=str(payment_id)).first()

    if not payment:
        logger.warning(f"[WEBHOOK] Payment not found: {payment_id}")
        return JsonResponse({'ok': True}, status=200)

    # Обрабатываем статус
    if status in ['APPROVED', 'SUCCESS', 'paid', 'success', 'completed', 'PAID']:
        if payment.status != 'paid':
            payment.status = 'paid'
            payment.paid_at = timezone.now()
            payment.save()
            logger.info(f"[WEBHOOK] ✅ Payment {payment.id} marked as paid")

            if payment.event_registration:
                payment.event_registration.status = 'paid'
                payment.event_registration.paid_at = timezone.now()
                payment.event_registration.save()
            else:
                from core.services.debts import settle_debts_on_payment
                settle_debts_on_payment(payment)
                logger.info(f"[WEBHOOK] ✅ Debts settled for payment {payment.id}")

    elif status in ['REJECTED', 'CANCELLED', 'failed', 'cancelled', 'FAILED']:
        if payment.status == 'pending':
            payment.status = 'failed'
            payment.save()
            logger.info(f"[WEBHOOK] ❌ Payment {payment.id} marked as failed")

    return JsonResponse({'ok': True})