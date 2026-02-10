"""Google OAuth helpers for LevelUpX using Authlib."""

import os

from authlib.integrations.flask_client import OAuth
from flask import session

from models import User, db

oauth = OAuth()


def init_oauth(app):
    """Register Google OAuth with the Flask app."""
    oauth.init_app(app)
    oauth.register(
        name='google',
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )


def get_or_create_user(userinfo: dict) -> User:
    """Find existing user by google_id or create a new one."""
    from datetime import datetime
    user = User.query.filter_by(google_id=userinfo['sub']).first()
    if user:
        user.last_login = datetime.utcnow()
        user.name = userinfo.get('name', user.name)
        user.picture = userinfo.get('picture', user.picture)
        db.session.commit()
        return user

    user = User(
        google_id=userinfo['sub'],
        email=userinfo['email'],
        name=userinfo.get('name', ''),
        picture=userinfo.get('picture', ''),
    )
    db.session.add(user)
    db.session.commit()
    return user


def track_analysis(user_id: int):
    """Increment analysis_count for a logged-in user."""
    user = User.query.get(user_id)
    if user:
        user.analysis_count += 1
        db.session.commit()


def current_user() -> User | None:
    """Return the logged-in User or None."""
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None
