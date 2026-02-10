"""Razorpay payment integration for LevelUpX credit purchases."""

import hashlib
import hmac
import logging
import os
from datetime import datetime

from models import Transaction, CreditUsage, User, db

logger = logging.getLogger(__name__)

RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', '')
RAZORPAY_WEBHOOK_SECRET = os.environ.get('RAZORPAY_WEBHOOK_SECRET', '')
PAYMENTS_ENABLED = bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)

# ---------------------------------------------------------------------------
# Pricing tiers
# ---------------------------------------------------------------------------
TIERS = {
    'starter': {'credits': 20, 'amount_paise': 19900, 'label': 'Starter', 'price': '₹199'},
    'popular': {'credits': 50, 'amount_paise': 44900, 'label': 'Popular', 'price': '₹449'},
    'pro':     {'credits': 100, 'amount_paise': 79900, 'label': 'Pro Pack', 'price': '₹799'},
}

CREDITS_PER_REWRITE = 5
CREDITS_PER_ANALYSIS = 2
FREE_ANALYSIS_LIMIT = 5

_razorpay_client = None


def _get_razorpay():
    """Lazy-init Razorpay client."""
    global _razorpay_client
    if _razorpay_client is None:
        import razorpay
        _razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return _razorpay_client


# ---------------------------------------------------------------------------
# Create Order
# ---------------------------------------------------------------------------

def create_order(user_id: int, tier: str) -> dict:
    """Create a Razorpay order and local Transaction record.

    Returns dict with 'order_id', 'amount_paise', 'credits', 'key_id'.
    Raises ValueError for invalid tier or RuntimeError if Razorpay fails.
    """
    if not PAYMENTS_ENABLED:
        raise RuntimeError('Payments are not configured (RAZORPAY keys missing)')

    tier_info = TIERS.get(tier)
    if not tier_info:
        raise ValueError(f'Invalid tier: {tier}')

    client = _get_razorpay()
    order_data = client.order.create({
        'amount': tier_info['amount_paise'],
        'currency': 'INR',
        'notes': {
            'user_id': str(user_id),
            'tier': tier,
            'credits': str(tier_info['credits']),
        },
    })

    order_id = order_data['id']
    logger.info('Razorpay order created: %s for user %d tier %s', order_id, user_id, tier)

    # Save transaction locally
    txn = Transaction(
        user_id=user_id,
        razorpay_order_id=order_id,
        amount_paise=tier_info['amount_paise'],
        credits_purchased=tier_info['credits'],
        status='created',
    )
    db.session.add(txn)
    db.session.commit()

    return {
        'order_id': order_id,
        'amount_paise': tier_info['amount_paise'],
        'credits': tier_info['credits'],
        'key_id': RAZORPAY_KEY_ID,
    }


# ---------------------------------------------------------------------------
# Verify Payment
# ---------------------------------------------------------------------------

def verify_payment(order_id: str, payment_id: str, signature: str) -> dict:
    """Verify Razorpay payment signature and credit the user.

    Returns dict with 'success', 'credits_added', 'new_balance'.
    """
    if not PAYMENTS_ENABLED:
        raise RuntimeError('Payments are not configured')

    # Find transaction
    txn = Transaction.query.filter_by(razorpay_order_id=order_id).first()
    if not txn:
        raise ValueError(f'Transaction not found for order {order_id}')
    if txn.status == 'paid':
        # Already processed (idempotent)
        user = User.query.get(txn.user_id)
        return {'success': True, 'credits_added': txn.credits_purchased,
                'new_balance': user.credits if user else 0}

    # Verify HMAC-SHA256 signature
    expected_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode('utf-8'),
        f'{order_id}|{payment_id}'.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        txn.status = 'failed'
        db.session.commit()
        logger.warning('Payment signature mismatch for order %s', order_id)
        raise ValueError('Invalid payment signature')

    # Credit the user atomically
    txn.razorpay_payment_id = payment_id
    txn.razorpay_signature = signature
    txn.status = 'paid'
    txn.completed_at = datetime.utcnow()

    user = User.query.get(txn.user_id)
    if not user:
        raise ValueError('User not found')

    user.credits += txn.credits_purchased

    # Record usage
    usage = CreditUsage(
        user_id=user.id,
        credits_used=-txn.credits_purchased,  # Negative = added
        action=f'purchase_{order_id}',
    )
    db.session.add(usage)
    db.session.commit()

    logger.info('Payment verified: user %d +%d credits (balance=%d)',
                user.id, txn.credits_purchased, user.credits)
    return {
        'success': True,
        'credits_added': txn.credits_purchased,
        'new_balance': user.credits,
    }


# ---------------------------------------------------------------------------
# Webhook handler (safety net)
# ---------------------------------------------------------------------------

def handle_webhook(payload: dict, signature: str) -> bool:
    """Process Razorpay webhook event. Returns True if handled."""
    if not RAZORPAY_WEBHOOK_SECRET:
        logger.info('Webhook received but no RAZORPAY_WEBHOOK_SECRET configured')
        return False

    # Verify webhook signature
    import json
    body = json.dumps(payload, separators=(',', ':'))
    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        logger.warning('Webhook signature mismatch')
        return False

    event = payload.get('event', '')
    if event == 'payment.captured':
        payment = payload.get('payload', {}).get('payment', {}).get('entity', {})
        order_id = payment.get('order_id')
        payment_id = payment.get('id')
        if order_id and payment_id:
            txn = Transaction.query.filter_by(razorpay_order_id=order_id).first()
            if txn and txn.status != 'paid':
                # Safety net: credit user if client callback missed
                txn.razorpay_payment_id = payment_id
                txn.status = 'paid'
                txn.completed_at = datetime.utcnow()
                user = User.query.get(txn.user_id)
                if user:
                    user.credits += txn.credits_purchased
                    usage = CreditUsage(
                        user_id=user.id,
                        credits_used=-txn.credits_purchased,
                        action=f'webhook_{order_id}',
                    )
                    db.session.add(usage)
                    db.session.commit()
                    logger.info('Webhook credited user %d +%d credits', user.id, txn.credits_purchased)
                    return True
    return False


# ---------------------------------------------------------------------------
# Credit deduction for rewrites
# ---------------------------------------------------------------------------

def deduct_credits(user_id: int, credits_needed: int = CREDITS_PER_REWRITE,
                   action: str = 'cv_rewrite') -> bool:
    """Atomically deduct credits. Returns True if successful, False if insufficient."""
    from sqlalchemy import text
    result = db.session.execute(
        text('UPDATE users SET credits = credits - :n WHERE id = :uid AND credits >= :n'),
        {'n': credits_needed, 'uid': user_id}
    )
    if result.rowcount == 0:
        db.session.rollback()
        return False

    usage = CreditUsage(
        user_id=user_id,
        credits_used=credits_needed,
        action=action,
    )
    db.session.add(usage)
    db.session.commit()
    logger.info('Deducted %d credits from user %d for %s', credits_needed, user_id, action)
    return True
