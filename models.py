"""Database models for LevelUpX — users, credits, transactions."""

from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(256), nullable=False, index=True)
    name = db.Column(db.String(256))
    picture = db.Column(db.String(512))
    analysis_count = db.Column(db.Integer, default=0)
    credits = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)

    transactions = db.relationship('Transaction', backref='user', lazy='dynamic')
    credit_usages = db.relationship('CreditUsage', backref='user', lazy='dynamic')

    def __repr__(self):
        return f'<User {self.email}>'


class Transaction(db.Model):
    """Razorpay payment transaction — tracks credit purchases."""
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    razorpay_order_id = db.Column(db.String(128), unique=True, nullable=False)
    razorpay_payment_id = db.Column(db.String(128))
    razorpay_signature = db.Column(db.String(256))
    amount_paise = db.Column(db.Integer, nullable=False)       # Amount in paise (₹199 = 19900)
    credits_purchased = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='created', nullable=False)  # created / paid / failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    def __repr__(self):
        return f'<Transaction {self.razorpay_order_id} {self.status}>'


class CreditUsage(db.Model):
    """Tracks credit consumption — rewrites, bonuses, etc."""
    __tablename__ = 'credit_usages'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    credits_used = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(50), nullable=False)  # 'cv_rewrite', 'bonus_signup'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<CreditUsage user={self.user_id} action={self.action} credits={self.credits_used}>'


class LLMUsage(db.Model):
    """Tracks LLM API call statistics — tokens, duration, model."""
    __tablename__ = 'llm_usages'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    action = db.Column(db.String(50), nullable=False)  # cv_analysis, jd_analysis, cv_rewrite, cv_refine
    model = db.Column(db.String(100), nullable=False)
    input_chars = db.Column(db.Integer, default=0)
    output_chars = db.Column(db.Integer, default=0)
    estimated_input_tokens = db.Column(db.Integer, default=0)
    estimated_output_tokens = db.Column(db.Integer, default=0)
    duration_ms = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<LLMUsage user={self.user_id} action={self.action} model={self.model}>'
