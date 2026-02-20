import io
import json
import logging
import os
import re
import shutil
import smtplib
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime
from email.message import EmailMessage

from dotenv import load_dotenv
load_dotenv()  # Load .env file (GROQ_API_KEY, etc.)

import requests as http_requests
from bs4 import BeautifulSoup
from flask import (Flask, Response, flash, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from sqlalchemy.orm import defer
from analyzer import analyze_cv_against_jd
from flask_cors import CORS
from models import (db, User, Transaction, CreditUsage, LLMUsage, StoredCV,
                    UserResume, JDAnalysis, JobPreferences, JobPool, ApiUsage,
                    ExtensionToken, UserProfile)

# Configure logging for debugging on Render
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Trust Railway's reverse proxy headers so url_for() generates https:// URLs
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
_secret = os.environ.get('SECRET_KEY')
if not _secret:
    logger.warning('SECRET_KEY not set — using fallback. Set SECRET_KEY env var for production!')
    _secret = 'levelupx-dev-fallback-key-change-in-production'
app.secret_key = _secret
app.config['PREFERRED_URL_SCHEME'] = 'https'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()

# CORS — only for Chrome Extension API endpoints
CORS(app, resources={r"/api/extension/*": {"origins": "*"}},
     allow_headers=["Authorization", "Content-Type"])

# ---------------------------------------------------------------------------
# Server-side session data (large data that won't fit in cookie sessions)
# ---------------------------------------------------------------------------
_SESSION_DATA_DIR = os.path.join(tempfile.gettempdir(), 'levelupx_sessions')
os.makedirs(_SESSION_DATA_DIR, exist_ok=True)


def _save_session_data(data: dict) -> str:
    """Save large data server-side. Returns a token stored in the cookie session."""
    token = str(uuid.uuid4())
    path = os.path.join(_SESSION_DATA_DIR, f'{token}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return token


def _load_session_data(token: str) -> dict:
    """Load data saved by _save_session_data. Returns {} if not found."""
    if not token:
        return {}
    path = os.path.join(_SESSION_DATA_DIR, f'{token}.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _update_session_data(token: str, updates: dict) -> str:
    """Update existing session data or create new. Returns token."""
    data = _load_session_data(token) if token else {}
    data.update(updates)
    if token:
        path = os.path.join(_SESSION_DATA_DIR, f'{token}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return token
    return _save_session_data(data)


# ---------------------------------------------------------------------------
# Database — always initialised (Postgres via DATABASE_URL, else SQLite)
# ---------------------------------------------------------------------------
database_url = os.environ.get('DATABASE_URL', '')
if database_url:
    # Railway Postgres URLs start with postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Fallback to SQLite (good enough for Railway single-instance deploys)
    _db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{_db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Connection pool config for PostgreSQL (Supabase / Railway) — not used for SQLite
if database_url:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 5,
        'pool_recycle': 300,
        'pool_pre_ping': True,
    }
db.init_app(app)
with app.app_context():
    db.create_all()
    # Migration: add 'credits' column to existing users table if missing
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        columns = [c['name'] for c in inspector.get_columns('users')]
        if 'credits' not in columns:
            db.session.execute(text('ALTER TABLE users ADD COLUMN credits INTEGER DEFAULT 0 NOT NULL'))
            db.session.commit()
            logger.info('Migration: added credits column to users table')
    except Exception as e:
        logger.info('Migration check: %s', e)
        db.session.rollback()

    # Migration: add 'onboarding_completed' column to users table if missing
    try:
        from sqlalchemy import text, inspect as sa_inspect
        insp = sa_inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('users')]
        if 'onboarding_completed' not in cols:
            db.session.execute(text('ALTER TABLE users ADD COLUMN onboarding_completed BOOLEAN DEFAULT FALSE NOT NULL'))
            db.session.commit()
            logger.info('Migration: added onboarding_completed column to users table')
    except Exception as e:
        logger.info('Migration check (onboarding): %s', e)
        db.session.rollback()

    # Migration: add analysis persistence columns to user_resumes table
    try:
        from sqlalchemy import text, inspect as _insp_fn
        _ur_insp = _insp_fn(db.engine)
        ur_cols = [c['name'] for c in _ur_insp.get_columns('user_resumes')]
        _new_ur_cols = {
            'target_job': "ALTER TABLE user_resumes ADD COLUMN target_job VARCHAR(200) DEFAULT 'General'",
            'ats_score': 'ALTER TABLE user_resumes ADD COLUMN ats_score INTEGER',
            'analysis_status': "ALTER TABLE user_resumes ADD COLUMN analysis_status VARCHAR(20) DEFAULT 'none'",
            'analysis_results_json': 'ALTER TABLE user_resumes ADD COLUMN analysis_results_json TEXT',
            'last_analyzed_at': 'ALTER TABLE user_resumes ADD COLUMN last_analyzed_at TIMESTAMP',
        }
        for col_name, ddl in _new_ur_cols.items():
            if col_name not in ur_cols:
                db.session.execute(text(ddl))
                logger.info('Migration: added %s column to user_resumes', col_name)
        db.session.commit()
    except Exception as e:
        logger.info('Migration check (user_resumes analysis): %s', e)
        db.session.rollback()

    # Migration: add jd_text column to jd_analyses table if missing
    try:
        from sqlalchemy import text as _sa_text, inspect as _sa_inspect
        _jda_insp = _sa_inspect(db.engine)
        if 'jd_analyses' in _jda_insp.get_table_names():
            jda_cols = [c['name'] for c in _jda_insp.get_columns('jd_analyses')]
            if 'jd_text' not in jda_cols:
                db.session.execute(_sa_text('ALTER TABLE jd_analyses ADD COLUMN jd_text TEXT'))
                db.session.commit()
                logger.info('Migration: added jd_text column to jd_analyses')
    except Exception as e:
        logger.info('Migration check (jd_analyses jd_text): %s', e)
        db.session.rollback()

    # Migration: create job_preferences, job_pool, snapshot and cache tables if missing
    try:
        from sqlalchemy import inspect as _jp_inspect
        from models import UserJobSnapshot, QuickATSCache
        _jp_insp = _jp_inspect(db.engine)
        _existing_tables = _jp_insp.get_table_names()
        if 'job_preferences' not in _existing_tables:
            JobPreferences.__table__.create(db.engine)
            logger.info('Migration: created job_preferences table')
        if 'job_pool' not in _existing_tables:
            JobPool.__table__.create(db.engine)
            logger.info('Migration: created job_pool table')
        if 'user_job_snapshots' not in _existing_tables:
            UserJobSnapshot.__table__.create(db.engine)
            logger.info('Migration: created user_job_snapshots table')
        if 'quick_ats_cache' not in _existing_tables:
            QuickATSCache.__table__.create(db.engine)
            logger.info('Migration: created quick_ats_cache table')
    except Exception as e:
        logger.info('Migration check (tables): %s', e)
        db.session.rollback()

    # Migration: create api_usage table + add page/source columns to job_search_cache
    try:
        from sqlalchemy import inspect as _au_inspect
        _au_insp = _au_inspect(db.engine)
        _au_tables = _au_insp.get_table_names()
        if 'api_usage' not in _au_tables:
            ApiUsage.__table__.create(db.engine)
            logger.info('Migration: created api_usage table')
        if 'job_search_cache' in _au_tables:
            from sqlalchemy import text as _au_text
            _jsc_cols = [c['name'] for c in _au_insp.get_columns('job_search_cache')]
            if 'page' not in _jsc_cols:
                db.session.execute(_au_text('ALTER TABLE job_search_cache ADD COLUMN page INTEGER DEFAULT 1'))
                db.session.commit()
                logger.info('Migration: added page column to job_search_cache')
            if 'source' not in _jsc_cols:
                db.session.execute(_au_text("ALTER TABLE job_search_cache ADD COLUMN source VARCHAR(20) DEFAULT 'jsearch'"))
                db.session.commit()
                logger.info('Migration: added source column to job_search_cache')
    except Exception as e:
        logger.info('Migration check (api_usage/cache cols): %s', e)
        db.session.rollback()

    # Migration: add 'level' column to job_preferences table if missing
    try:
        from sqlalchemy import inspect as _lv_inspect, text as _lv_text
        _lv_insp = _lv_inspect(db.engine)
        if 'job_preferences' in _lv_insp.get_table_names():
            _jp_cols = [c['name'] for c in _lv_insp.get_columns('job_preferences')]
            if 'level' not in _jp_cols:
                db.session.execute(_lv_text("ALTER TABLE job_preferences ADD COLUMN level VARCHAR(30) DEFAULT ''"))
                db.session.commit()
                logger.info('Migration: added level column to job_preferences')
    except Exception as e:
        logger.info('Migration check (job_preferences level): %s', e)
        db.session.rollback()

    # Migration: add 'source' column to job_pool table if missing
    try:
        from sqlalchemy import inspect as _jp2_inspect, text as _jp2_text
        _jp2_insp = _jp2_inspect(db.engine)
        if 'job_pool' in _jp2_insp.get_table_names():
            _pool_cols = [c['name'] for c in _jp2_insp.get_columns('job_pool')]
            if 'source' not in _pool_cols:
                db.session.execute(_jp2_text("ALTER TABLE job_pool ADD COLUMN source VARCHAR(30) DEFAULT 'jsearch'"))
                db.session.commit()
                logger.info('Migration: added source column to job_pool')
    except Exception as e:
        logger.info('Migration check (job_pool source): %s', e)
        db.session.rollback()

    # Migration: add resume editor columns to user_resumes table
    try:
        from sqlalchemy import inspect as _re_inspect, text as _re_text
        _re_insp = _re_inspect(db.engine)
        if 'user_resumes' in _re_insp.get_table_names():
            _re_cols = [c['name'] for c in _re_insp.get_columns('user_resumes')]
            _editor_cols = {
                'resume_json': 'ALTER TABLE user_resumes ADD COLUMN resume_json TEXT',
                'template_id': "ALTER TABLE user_resumes ADD COLUMN template_id VARCHAR(30) DEFAULT 'classic'",
                'resume_source': "ALTER TABLE user_resumes ADD COLUMN resume_source VARCHAR(20) DEFAULT 'upload'",
            }
            for col_name, ddl in _editor_cols.items():
                if col_name not in _re_cols:
                    db.session.execute(_re_text(ddl))
                    logger.info('Migration: added %s column to user_resumes', col_name)
            db.session.commit()
    except Exception as e:
        logger.info('Migration check (resume editor): %s', e)
        db.session.rollback()

    # Migration: create user_profiles table if missing
    try:
        from sqlalchemy import inspect as _up_inspect
        _up_insp = _up_inspect(db.engine)
        if 'user_profiles' not in _up_insp.get_table_names():
            UserProfile.__table__.create(db.engine)
            logger.info('Migration: created user_profiles table')
    except Exception as e:
        logger.info('Migration check (user_profiles): %s', e)
        db.session.rollback()

    # Migration: add new application-preference columns to user_profiles
    try:
        from sqlalchemy import inspect as _up2_inspect, text as _up2_text
        _up2_insp = _up2_inspect(db.engine)
        if 'user_profiles' in _up2_insp.get_table_names():
            _up2_cols = [c['name'] for c in _up2_insp.get_columns('user_profiles')]
            _new_up_cols = {
                'earliest_start_date': "ALTER TABLE user_profiles ADD COLUMN earliest_start_date VARCHAR(30) DEFAULT ''",
                'additional_info': "ALTER TABLE user_profiles ADD COLUMN additional_info TEXT DEFAULT ''",
                'willing_to_relocate': "ALTER TABLE user_profiles ADD COLUMN willing_to_relocate VARCHAR(5) DEFAULT ''",
                'can_work_onsite': "ALTER TABLE user_profiles ADD COLUMN can_work_onsite VARCHAR(5) DEFAULT ''",
                'preferred_office': "ALTER TABLE user_profiles ADD COLUMN preferred_office VARCHAR(200) DEFAULT ''",
            }
            for col_name, ddl in _new_up_cols.items():
                if col_name not in _up2_cols:
                    db.session.execute(_up2_text(ddl))
                    logger.info('Migration: added %s column to user_profiles', col_name)
            db.session.commit()
    except Exception as e:
        logger.info('Migration check (user_profiles new cols): %s', e)
        db.session.rollback()

    # Migration: create interview_sessions and interview_exchanges tables
    try:
        from sqlalchemy import inspect as _iv_inspect
        from models import InterviewSession, InterviewExchange
        _iv_insp = _iv_inspect(db.engine)
        _iv_tables = _iv_insp.get_table_names()
        if 'interview_sessions' not in _iv_tables:
            InterviewSession.__table__.create(db.engine)
            logger.info('Migration: created interview_sessions table')
        if 'interview_exchanges' not in _iv_tables:
            InterviewExchange.__table__.create(db.engine)
            logger.info('Migration: created interview_exchanges table')
    except Exception as e:
        logger.info('Migration check (interview tables): %s', e)
        db.session.rollback()

    # Migration: add new columns to interview_exchanges (v2 upgrade)
    try:
        _ix_cols = [c['name'] for c in _iv_insp.get_columns('interview_exchanges')]
        if 'question_type' not in _ix_cols:
            db.session.execute(text("ALTER TABLE interview_exchanges ADD COLUMN question_type VARCHAR(30)"))
            logger.info('Migration: added question_type to interview_exchanges')
        if 'requires_code' not in _ix_cols:
            db.session.execute(text("ALTER TABLE interview_exchanges ADD COLUMN requires_code BOOLEAN DEFAULT FALSE"))
            logger.info('Migration: added requires_code to interview_exchanges')
        if 'code_language' not in _ix_cols:
            db.session.execute(text("ALTER TABLE interview_exchanges ADD COLUMN code_language VARCHAR(20)"))
            logger.info('Migration: added code_language to interview_exchanges')
        db.session.commit()
    except Exception as e:
        logger.info('Migration check (interview_exchanges new cols): %s', e)
        db.session.rollback()

    # Cleanup: remove expired job_search_cache entries older than 7 days
    try:
        from models import JobSearchCache
        from datetime import timedelta as _cache_td
        _cache_cutoff = datetime.utcnow() - _cache_td(days=7)
        _cache_deleted = JobSearchCache.query.filter(
            JobSearchCache.expires_at < _cache_cutoff
        ).delete()
        db.session.commit()
        if _cache_deleted:
            logger.info('Cache cleanup: removed %d expired entries', _cache_deleted)
    except Exception as e:
        logger.info('Cache cleanup: %s', e)
        db.session.rollback()

    # Cleanup: remove stale job_pool entries older than 14 days
    try:
        from datetime import timedelta as _td
        _pool_cutoff = datetime.utcnow() - _td(days=14)
        _deleted = JobPool.query.filter(JobPool.fetched_at < _pool_cutoff).delete()
        db.session.commit()
        if _deleted:
            logger.info('Job pool cleanup: removed %d stale entries', _deleted)
    except Exception as e:
        logger.info('Job pool cleanup: %s', e)
        db.session.rollback()

# ---------------------------------------------------------------------------
# Google OAuth (optional — only if credentials are set)
# ---------------------------------------------------------------------------
_oauth_enabled = bool(os.environ.get('GOOGLE_CLIENT_ID'))
if _oauth_enabled:
    from auth import init_oauth, get_or_create_user, track_analysis, current_user, oauth
    init_oauth(app)

# ---------------------------------------------------------------------------
# Chrome Extension API — token auth, profile, resume file, token CRUD
# ---------------------------------------------------------------------------
import hashlib
import secrets
from functools import wraps


def require_extension_token(f):
    """Decorator: validate Bearer token from Chrome Extension requests."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        raw_token = auth_header[7:].strip()
        if not raw_token:
            return jsonify({'error': 'Empty token'}), 401
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        ext_token = ExtensionToken.query.filter_by(
            token_hash=token_hash, is_active=True
        ).first()
        if not ext_token:
            return jsonify({'error': 'Invalid or revoked token'}), 401
        # Update last_used_at
        ext_token.last_used_at = datetime.utcnow()
        db.session.commit()
        # Attach user to request
        request._extension_user = User.query.get(ext_token.user_id)
        if not request._extension_user:
            return jsonify({'error': 'User not found'}), 404
        return f(*args, **kwargs)
    return decorated


def _build_extension_profile(resume):
    """Build structured profile dict from a UserResume for the Chrome Extension.

    Handles both editor resumes (resume_json) and uploaded resumes (extracted_text).
    """
    profile = {
        'basics': {
            'firstName': '', 'lastName': '', 'fullName': '',
            'email': '', 'phone': '',
            'location': {'city': '', 'region': '', 'country': ''},
            'summary': '', 'title': '',
            'linkedin': '', 'github': '', 'website': '',
        },
        'work': [],
        'education': [],
        'skills': [],
        'projects': [],
        'certificates': [],
        'resumeId': resume.id,
        'resumeLabel': resume.label or 'My Resume',
    }

    # --- Editor resumes: parse JSON Resume schema ---
    if resume.resume_json:
        try:
            data = json.loads(resume.resume_json)
        except (json.JSONDecodeError, TypeError):
            data = {}

        basics = data.get('basics', {})
        full_name = basics.get('name', '')
        name_parts = full_name.split(None, 1)
        profile['basics']['firstName'] = name_parts[0] if name_parts else ''
        profile['basics']['lastName'] = name_parts[1] if len(name_parts) > 1 else ''
        profile['basics']['fullName'] = full_name
        profile['basics']['email'] = basics.get('email', '')
        profile['basics']['phone'] = basics.get('phone', '')
        profile['basics']['summary'] = basics.get('summary', '')
        profile['basics']['title'] = basics.get('label', '')

        loc = basics.get('location', {})
        if isinstance(loc, dict):
            profile['basics']['location'] = {
                'city': loc.get('city', ''),
                'region': loc.get('region', ''),
                'country': loc.get('countryCode', loc.get('country', '')),
            }

        # Parse profiles (linkedin, github, website)
        for p in basics.get('profiles', []):
            network = (p.get('network', '') or '').lower()
            url = p.get('url', '')
            if 'linkedin' in network:
                profile['basics']['linkedin'] = url
            elif 'github' in network:
                profile['basics']['github'] = url
        profile['basics']['website'] = basics.get('url', '')

        # Work experience
        for w in data.get('work', []):
            profile['work'].append({
                'company': w.get('name', w.get('company', '')),
                'position': w.get('position', ''),
                'startDate': w.get('startDate', ''),
                'endDate': w.get('endDate', ''),
                'summary': w.get('summary', ''),
                'highlights': w.get('highlights', []),
                'current': not bool(w.get('endDate')),
            })

        # Education
        for e in data.get('education', []):
            profile['education'].append({
                'institution': e.get('institution', ''),
                'studyType': e.get('studyType', ''),
                'area': e.get('area', ''),
                'startDate': e.get('startDate', ''),
                'endDate': e.get('endDate', ''),
                'score': e.get('score', e.get('gpa', '')),
            })

        # Skills
        for s in data.get('skills', []):
            if isinstance(s, dict):
                profile['skills'].append(s.get('name', ''))
            elif isinstance(s, str):
                profile['skills'].append(s)

        # Projects
        for p in data.get('projects', []):
            profile['projects'].append({
                'name': p.get('name', ''),
                'description': p.get('description', ''),
                'url': p.get('url', ''),
                'keywords': p.get('keywords', []),
            })

        # Certificates
        for c in data.get('certificates', []):
            profile['certificates'].append({
                'name': c.get('name', ''),
                'issuer': c.get('issuer', ''),
                'date': c.get('date', ''),
                'url': c.get('url', ''),
            })

    # --- Uploaded resumes: extract from text ---
    elif resume.extracted_text:
        text = resume.extracted_text
        from nlp_service import (extract_candidate_name, extract_skills_from_cv,
                                 _EMAIL_RE, _PHONE_RE, _LINKEDIN_RE, _GITHUB_RE)

        # Name
        full_name = extract_candidate_name(text)
        name_parts = full_name.split(None, 1) if full_name else []
        profile['basics']['firstName'] = name_parts[0] if name_parts else ''
        profile['basics']['lastName'] = name_parts[1] if len(name_parts) > 1 else ''
        profile['basics']['fullName'] = full_name

        # Contact info via regex
        email_match = _EMAIL_RE.search(text)
        if email_match:
            profile['basics']['email'] = email_match.group(0)

        phone_match = _PHONE_RE.search(text)
        if phone_match:
            profile['basics']['phone'] = phone_match.group(0).strip()

        linkedin_match = _LINKEDIN_RE.search(text)
        if linkedin_match:
            profile['basics']['linkedin'] = 'https://' + linkedin_match.group(0)

        github_match = _GITHUB_RE.search(text)
        if github_match:
            profile['basics']['github'] = 'https://' + github_match.group(0)

        # Skills
        try:
            skills_result = extract_skills_from_cv(text)
            profile['skills'] = skills_result.get('skills_found', [])[:30]
        except Exception:
            pass

    # Fall back: use user email/name if resume didn't have it
    return profile


@app.route('/api/extension/profile', methods=['GET'])
@require_extension_token
def api_extension_profile():
    """Return structured profile data for the Chrome Extension."""
    user = request._extension_user
    # Find primary resume, or most recent
    resume = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()
    if not resume:
        resume = UserResume.query.filter_by(user_id=user.id).order_by(
            UserResume.updated_at.desc()).first()
    if not resume:
        return jsonify({'error': 'No resume found. Please upload a resume on LevelUpX first.'}), 404

    profile = _build_extension_profile(resume)
    # Fill in user-level data if missing from resume
    if not profile['basics']['email']:
        profile['basics']['email'] = user.email or ''
    if not profile['basics']['fullName']:
        profile['basics']['fullName'] = user.name or ''
        parts = (user.name or '').split(None, 1)
        profile['basics']['firstName'] = parts[0] if parts else ''
        profile['basics']['lastName'] = parts[1] if len(parts) > 1 else ''

    # ── Merge UserProfile data ──────────────────────────────────
    # UserProfile (manually entered by user) ALWAYS wins over NLP-extracted
    # resume data, since user input is more trustworthy than regex heuristics.
    up = UserProfile.query.filter_by(user_id=user.id).first()
    if up:
        b = profile['basics']
        loc = b['location']

        # UserProfile overrides NLP extraction when it has data
        if up.first_name:
            b['firstName'] = up.first_name
        if up.last_name:
            b['lastName'] = up.last_name
        if up.first_name or up.last_name:
            b['fullName'] = f'{up.first_name or b["firstName"]} {up.last_name or b["lastName"]}'.strip()
        if up.phone:
            b['phone'] = up.phone
        if up.city:
            loc['city'] = up.city
        if up.state:
            loc['region'] = up.state
        if up.country:
            loc['country'] = 'India' if up.country == 'IN' else 'United States' if up.country == 'US' else up.country
        if up.postal_code:
            loc['postalCode'] = up.postal_code
        if up.street_address:
            loc['address'] = up.street_address
        if up.linkedin_url:
            b['linkedin'] = up.linkedin_url
        if up.github_url:
            b['github'] = up.github_url
        if up.website_url:
            b['website'] = up.website_url

        # Work: UserProfile wins when it has data
        if up.current_company or up.current_title:
            if not profile['work']:
                profile['work'] = [{}]
            w = profile['work'][0]
            if up.current_company:
                w['company'] = up.current_company
            if up.current_title:
                w['position'] = up.current_title

        # Education: UserProfile wins when it has data
        if up.university or up.degree or up.major:
            if not profile['education']:
                profile['education'] = [{}]
            e = profile['education'][0]
            if up.university:
                e['institution'] = up.university
            if up.degree:
                e['studyType'] = up.degree
            if up.major:
                e['area'] = up.major
            if up.gpa:
                e['score'] = up.gpa
            if up.graduation_year:
                e['endDate'] = up.graduation_year

        # Application preferences (all India + US fields)
        profile['applicationPrefs'] = {
            'country': up.country or 'IN',
            # India
            'currentCTC': up.current_ctc or '',
            'expectedCTC': up.expected_ctc or '',
            'noticePeriod': up.notice_period or '',
            'totalExperienceYears': up.total_experience_years or '',
            'languagesKnown': json.loads(up.languages_known or '[]'),
            'preferredLocations': json.loads(up.preferred_locations or '[]'),
            'dateOfBirth': up.date_of_birth or '',
            'genderIN': up.gender_in or '',
            # US
            'workAuthorization': up.work_authorization or '',
            'visaSponsorship': up.visa_sponsorship or '',
            'genderUS': up.gender_us or '',
            'raceEthnicity': up.race_ethnicity or '',
            'veteranStatus': up.veteran_status or '',
            'disabilityStatus': up.disability_status or '',
            'salaryExpectationUSD': up.salary_expectation_usd or '',
            'referralSource': up.referral_source or '',
            # Common application fields
            'earliestStartDate': up.earliest_start_date or '',
            'additionalInfo': up.additional_info or '',
            'willingToRelocate': up.willing_to_relocate or '',
            'canWorkOnsite': up.can_work_onsite or '',
            'preferredOffice': up.preferred_office or '',
        }
    else:
        # Always include applicationPrefs (even empty) so extension code works
        profile['applicationPrefs'] = {
            'country': '', 'currentCTC': '', 'expectedCTC': '',
            'noticePeriod': '', 'totalExperienceYears': '',
            'languagesKnown': [], 'preferredLocations': [],
            'dateOfBirth': '', 'genderIN': '',
            'workAuthorization': '', 'visaSponsorship': '',
            'genderUS': '', 'raceEthnicity': '',
            'veteranStatus': '', 'disabilityStatus': '',
            'salaryExpectationUSD': '', 'referralSource': '',
            'earliestStartDate': '', 'additionalInfo': '',
            'willingToRelocate': '', 'canWorkOnsite': '',
            'preferredOffice': '',
        }

    return jsonify(profile)


@app.route('/api/extension/resume-file', methods=['GET'])
@require_extension_token
def api_extension_resume_file():
    """Return the actual resume PDF/DOCX file for form upload."""
    user = request._extension_user
    resume = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()
    if not resume:
        resume = UserResume.query.filter_by(user_id=user.id).order_by(
            UserResume.updated_at.desc()).first()
    if not resume or not resume.file_data:
        return jsonify({'error': 'No resume file found'}), 404

    mimetype = 'application/pdf'
    if resume.filename and resume.filename.lower().endswith('.docx'):
        mimetype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

    return send_file(
        io.BytesIO(resume.file_data),
        mimetype=mimetype,
        as_attachment=True,
        download_name=resume.filename or 'resume.pdf',
    )


@app.route('/api/extension/tokens', methods=['GET'])
def api_extension_tokens_list():
    """List user's extension tokens (session-authed, for Settings page)."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    tokens = ExtensionToken.query.filter_by(
        user_id=session['user_id'], is_active=True
    ).order_by(ExtensionToken.created_at.desc()).all()
    return jsonify({'tokens': [{
        'id': t.id,
        'label': t.label,
        'created_at': t.created_at.isoformat() if t.created_at else '',
        'last_used_at': t.last_used_at.isoformat() if t.last_used_at else None,
    } for t in tokens]})


@app.route('/api/extension/tokens', methods=['POST'])
def api_extension_tokens_create():
    """Generate a new extension token (max 3 per user)."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']

    # Max 3 active tokens per user
    active_count = ExtensionToken.query.filter_by(
        user_id=user_id, is_active=True).count()
    if active_count >= 3:
        return jsonify({'error': 'Maximum 3 active tokens. Please revoke one first.'}), 400

    label = (request.json or {}).get('label', 'Chrome Extension')
    raw_token = secrets.token_hex(24)  # 48-char hex string
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    ext_token = ExtensionToken(
        user_id=user_id,
        token_hash=token_hash,
        label=label[:100],
    )
    db.session.add(ext_token)
    db.session.commit()

    return jsonify({
        'token': raw_token,  # Shown ONCE, never stored raw
        'id': ext_token.id,
        'label': ext_token.label,
        'message': 'Copy this token now — it will not be shown again.',
    })


@app.route('/api/extension/tokens/<int:token_id>', methods=['DELETE'])
def api_extension_tokens_revoke(token_id):
    """Revoke (deactivate) an extension token."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    ext_token = ExtensionToken.query.filter_by(
        id=token_id, user_id=session['user_id']
    ).first()
    if not ext_token:
        return jsonify({'error': 'Token not found'}), 404
    ext_token.is_active = False
    db.session.commit()
    return jsonify({'success': True, 'message': 'Token revoked'})


@app.route('/download-extension')
def download_extension_zip():
    """Serve the Chrome Extension as a downloadable ZIP file."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    ext_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chrome-extension')
    if not os.path.isdir(ext_dir):
        return jsonify({'error': 'Extension files not found'}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(ext_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                arc_name = os.path.join('levelupx-autofill',
                                        os.path.relpath(full_path, ext_dir))
                zf.write(full_path, arc_name)
    buf.seek(0)
    return send_file(buf, mimetype='application/zip', as_attachment=True,
                     download_name='levelupx-autofill.zip')


# ---------------------------------------------------------------------------
# Session credits are updated at every point where credits change (login,
# analysis, purchase, rewrite, etc.) — no need for a before_request DB hit.
# ---------------------------------------------------------------------------

@app.after_request
def _set_cache_headers(response):
    """Prevent proxy/CDN caching of authenticated pages (security fix)."""
    if session.get('user_id'):
        response.headers['Cache-Control'] = 'private, no-cache, no-store, must-revalidate'
        response.headers['Vary'] = 'Cookie'
    return response

# Folder to store consented CVs
# Default: ~/Downloads/LevelUpX_CVs/ locally, or collected_cvs/ on Railway
_default_cv_path = os.path.join(os.path.expanduser('~'), 'Downloads', 'LevelUpX_CVs')
if not os.path.isdir(os.path.join(os.path.expanduser('~'), 'Downloads')):
    # On Railway / Linux server, fall back to app-local folder
    _default_cv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'collected_cvs')
CV_STORAGE = os.environ.get('CV_STORAGE_PATH', _default_cv_path)
os.makedirs(CV_STORAGE, exist_ok=True)

# SMTP config for emailing CVs to owner (optional — graceful no-op if not set)
SMTP_HOST = os.environ.get('SMTP_HOST', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
CV_NOTIFY_EMAIL = os.environ.get('CV_NOTIFY_EMAIL', 'contact@levelupx.ai')

def _email_cv_to_owner(file_path, user_email):
    """Email uploaded CV as attachment to site owner. Runs in background thread."""
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS]):
        logger.debug('SMTP not configured — skipping CV email notification')
        return

    # Read file bytes NOW (before temp file may be deleted)
    filename = os.path.basename(file_path)
    with open(file_path, 'rb') as f:
        file_bytes = f.read()

    ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else 'pdf'
    mime_map = {'pdf': 'application/pdf', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'txt': 'text/plain'}
    maintype, _, subtype = mime_map.get(ext, 'application/octet-stream').partition('/')

    def _send():
        try:
            msg = EmailMessage()
            msg['Subject'] = f'New CV Upload — {user_email} — {datetime.now().strftime("%Y-%m-%d %H:%M")}'
            msg['From'] = SMTP_USER
            msg['To'] = CV_NOTIFY_EMAIL
            msg.set_content(
                f'A new CV was uploaded by {user_email}.\n\n'
                f'File: {filename}\n'
                f'Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
            )
            msg.add_attachment(file_bytes, maintype=maintype, subtype=subtype,
                               filename=filename)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
            logger.info('CV emailed to %s for upload by %s', CV_NOTIFY_EMAIL, user_email)
        except Exception as e:
            logger.error('Failed to email CV to owner: %s', e)

    threading.Thread(target=_send, daemon=True).start()

def _save_cv_to_db(file_path, user_email, user_id=None):
    """Save uploaded CV to PostgreSQL for persistent storage across deploys."""
    try:
        filename = os.path.basename(file_path)
        with open(file_path, 'rb') as f:
            file_data = f.read()
        cv = StoredCV(
            user_id=user_id,
            user_email=user_email or 'unknown',
            filename=filename,
            file_data=file_data,
            file_size=len(file_data),
        )
        db.session.add(cv)
        db.session.commit()
        logger.info('CV stored in DB: %s (user=%s, size=%d bytes)', filename, user_email, len(file_data))
    except Exception as e:
        db.session.rollback()
        logger.error('Failed to store CV in DB: %s', e)

# Admin token for accessing stored CVs (set via env var on Render)
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'change-me-in-production')

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}

BROWSER_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/120.0.0.0 Safari/537.36'),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# File extraction helpers
# ---------------------------------------------------------------------------

def extract_text_from_file(filepath: str) -> str:
    ext = filepath.rsplit('.', 1)[-1].lower()
    if ext == 'pdf':
        return _extract_pdf(filepath)
    elif ext == 'docx':
        return _extract_docx(filepath)
    elif ext == 'txt':
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    raise ValueError(f'Unsupported file type: {ext}')


def _extract_pdf(filepath: str) -> str:
    import pdfplumber
    text_parts = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

    text = '\n'.join(text_parts)

    # Fallback: if pdfplumber found no text (image-based PDF), try Gemini Vision OCR
    if not text.strip():
        logger.info('PDF has no extractable text, attempting Gemini Vision OCR: %s', filepath)
        text = _ocr_pdf_with_gemini(filepath)

    return text


def _ocr_pdf_with_gemini(filepath: str) -> str:
    """OCR fallback for image-based PDFs using Gemini Vision.

    Opens the PDF, renders each page to a PNG image, sends to Gemini 2.5 Flash
    with a vision prompt to extract all text. Returns concatenated text.
    """
    import base64
    import io
    import pdfplumber
    from openai import OpenAI

    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        logger.warning('Gemini Vision OCR skipped — no GEMINI_API_KEY')
        return ''

    model = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')
    client = OpenAI(
        api_key=api_key,
        base_url='https://generativelanguage.googleapis.com/v1beta/openai/',
    )

    text_parts = []
    try:
        with pdfplumber.open(filepath) as pdf:
            for i, page in enumerate(pdf.pages):
                # Render page to PIL Image
                img = page.to_image(resolution=200).original

                # Convert to base64 PNG
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

                response = client.chat.completions.create(
                    model=model,
                    messages=[{
                        'role': 'user',
                        'content': [
                            {
                                'type': 'text',
                                'text': (
                                    'Extract ALL text from this resume/CV image exactly as written. '
                                    'Preserve the original structure with section headings, bullet points, '
                                    'dates, and formatting. Output ONLY the extracted text, nothing else.'
                                ),
                            },
                            {
                                'type': 'image_url',
                                'image_url': {'url': f'data:image/png;base64,{b64}'},
                            },
                        ],
                    }],
                    max_tokens=4000,
                    temperature=0.1,
                )
                page_text = response.choices[0].message.content
                if page_text and page_text.strip():
                    text_parts.append(page_text.strip())
                    logger.info('Gemini Vision OCR page %d: %d chars extracted', i, len(page_text))
    except Exception as e:
        logger.warning('Gemini Vision OCR failed: %s', e)

    return '\n\n'.join(text_parts)


def _extract_docx(filepath: str) -> str:
    from docx import Document
    doc = Document(filepath)
    return '\n'.join(para.text for para in doc.paragraphs if para.text.strip())


def _sanitize_for_pdf(text: str) -> str:
    """Sanitize text: replace unicode chars that Helvetica (Latin-1) can't render."""
    clean = text
    clean = clean.replace('\u2018', "'").replace('\u2019', "'")   # smart quotes
    clean = clean.replace('\u201c', '"').replace('\u201d', '"')   # smart double quotes
    clean = clean.replace('\u2013', '-').replace('\u2014', '--')  # en/em dash
    clean = clean.replace('\u2022', '-').replace('\u2023', '>')   # bullets
    clean = clean.replace('\u2026', '...')                        # ellipsis
    clean = clean.replace('\u00a0', ' ')                          # non-breaking space
    clean = clean.encode('latin-1', errors='replace').decode('latin-1')
    return clean


def _text_to_pdf(text: str, output_path: str):
    """Basic text-to-PDF for original CV downloads."""
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Helvetica', size=10)
    clean = _sanitize_for_pdf(text)
    usable_w = pdf.w - pdf.l_margin - pdf.r_margin

    for line in clean.split('\n'):
        if not line.strip():
            pdf.ln(5)
            continue
        try:
            pdf.multi_cell(usable_w, 5, line)
        except Exception:
            try:
                pdf.multi_cell(usable_w, 5, line[:500])
            except Exception:
                pdf.ln(5)
        pdf.x = pdf.l_margin

    pdf.output(output_path)


def _rewritten_cv_to_pdf(text: str, output_path: str):
    """Convert a rewritten CV (plain text with structure) to a well-formatted PDF."""
    import re as regex
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    usable_w = pdf.w - pdf.l_margin - pdf.r_margin

    clean = _sanitize_for_pdf(text)

    # Strip any leftover markdown syntax
    clean = regex.sub(r'^#{1,4}\s+', '', clean, flags=regex.MULTILINE)  # ### headings
    clean = regex.sub(r'\*\*(.+?)\*\*', r'\1', clean)                  # **bold** → plain

    lines = clean.split('\n')

    # Section headings we recognize (all caps)
    section_headings = {
        'SUMMARY', 'EXPERIENCE', 'EDUCATION', 'PROJECTS', 'SKILLS',
        'CONTACT', 'HOBBIES', 'CERTIFICATIONS', 'ACHIEVEMENTS',
        'PUBLICATIONS', 'INTERESTS', 'VOLUNTEER', 'AWARDS',
        'TECHNICAL SKILLS', 'CORE COMPETENCIES', 'PROFESSIONAL SUMMARY',
    }

    def _is_section_heading(line_text):
        stripped = line_text.strip().rstrip(':')
        return stripped.upper() in section_headings or stripped.isupper() and len(stripped) > 2 and not stripped.startswith(('*', '-', 'HTTP'))

    def _is_company_line(line_text):
        """Detect company name lines: ALL CAPS with optional date range."""
        stripped = line_text.strip()
        if not stripped:
            return False
        # Pattern: "COMPANY NAME    Month Year - Month Year" or just "COMPANY NAME"
        parts = regex.split(r'\s{2,}|\t+', stripped, maxsplit=1)
        name_part = parts[0].strip()
        # Check if name part is mostly uppercase and at least 2 words or known company pattern
        if name_part.isupper() and len(name_part) > 3 and name_part not in section_headings:
            return True
        return False

    def _is_bullet(line_text):
        stripped = line_text.strip()
        return stripped.startswith(('* ', '- ', '- '))

    first_line = True
    for i, line in enumerate(lines):
        stripped = line.strip()

        if not stripped:
            pdf.ln(3)
            continue

        try:
            # Line 1: Candidate name (large, bold)
            if first_line and stripped and not _is_section_heading(stripped) and not _is_bullet(stripped):
                pdf.set_font('Helvetica', 'B', 16)
                pdf.multi_cell(usable_w, 8, stripped)
                pdf.x = pdf.l_margin
                pdf.ln(1)
                first_line = False
                continue

            first_line = False

            # Title/tagline line (e.g., "EXPERIENCED ENGINEER | AI | ...")
            if '|' in stripped and i < 5:
                pdf.set_font('Helvetica', '', 9)
                pdf.set_text_color(80, 80, 80)
                pdf.multi_cell(usable_w, 5, stripped)
                pdf.x = pdf.l_margin
                pdf.set_text_color(0, 0, 0)
                pdf.ln(1)
                continue

            # Section headings (SUMMARY, EXPERIENCE, etc.)
            if _is_section_heading(stripped):
                pdf.ln(4)
                pdf.set_font('Helvetica', 'B', 12)
                pdf.set_text_color(0, 80, 60)  # Emerald color
                pdf.multi_cell(usable_w, 6, stripped.upper())
                pdf.x = pdf.l_margin
                # Draw a thin line under the heading
                y = pdf.get_y()
                pdf.set_draw_color(0, 80, 60)
                pdf.line(pdf.l_margin, y, pdf.l_margin + usable_w, y)
                pdf.ln(3)
                pdf.set_text_color(0, 0, 0)
                pdf.set_draw_color(0, 0, 0)
                continue

            # Company / role lines (VERIZON, EXTRON ELECTRONICS, etc.)
            if _is_company_line(stripped):
                pdf.ln(2)
                pdf.set_font('Helvetica', 'B', 11)
                pdf.multi_cell(usable_w, 5.5, stripped)
                pdf.x = pdf.l_margin
                continue

            # Sub-title lines (job title, degree name — usually after company/education)
            # Detect: italic-style subtitle like "Business Strategy, Data Science Group"
            # or "Concentration: ..."
            prev_stripped = lines[i - 1].strip() if i > 0 else ''
            if (_is_company_line(prev_stripped) or prev_stripped.upper() in section_headings) and not _is_bullet(stripped):
                pdf.set_font('Helvetica', 'I', 10)
                pdf.multi_cell(usable_w, 5, stripped)
                pdf.x = pdf.l_margin
                continue

            # Bullet points
            if _is_bullet(stripped):
                bullet_text = regex.sub(r'^[\*\-]\s+', '', stripped)
                pdf.set_font('Helvetica', '', 10)
                indent = 10
                bullet_y = pdf.get_y() + 2.0  # Center dot with first line of text
                # Draw a small filled circle as bullet marker
                pdf.set_fill_color(60, 60, 60)
                pdf.ellipse(pdf.l_margin + 3.5, bullet_y, 1.5, 1.5, 'F')
                pdf.set_fill_color(0, 0, 0)  # Reset fill
                pdf.x = pdf.l_margin + indent
                pdf.multi_cell(usable_w - indent, 5, bullet_text)
                pdf.x = pdf.l_margin
                continue

            # Regular text
            pdf.set_font('Helvetica', '', 10)
            pdf.multi_cell(usable_w, 5, stripped)
            pdf.x = pdf.l_margin

        except Exception:
            try:
                pdf.set_font('Helvetica', '', 10)
                pdf.multi_cell(usable_w, 5, stripped[:500])
                pdf.x = pdf.l_margin
            except Exception:
                pdf.ln(5)

    pdf.output(output_path)


# ---------------------------------------------------------------------------
# URL extraction helpers
# ---------------------------------------------------------------------------

def _extract_from_linkedin_url(url: str) -> str:
    """Extract profile text from a public LinkedIn profile URL.

    Returns extracted text, or a string starting with 'ERROR:' if
    extraction failed with a user-friendly reason.
    """
    if 'linkedin.com/in/' not in url:
        return ''

    logger.info('LinkedIn extraction: requesting %s', url)

    try:
        resp = http_requests.get(url, headers=BROWSER_HEADERS, timeout=15,
                                 allow_redirects=True)
        logger.info('LinkedIn response: status=%s, final_url=%s, length=%d',
                     resp.status_code, resp.url, len(resp.text))
        resp.raise_for_status()
    except http_requests.exceptions.Timeout:
        logger.warning('LinkedIn extraction: request timed out')
        return 'ERROR:TIMEOUT'
    except http_requests.exceptions.ConnectionError:
        logger.warning('LinkedIn extraction: connection error')
        return 'ERROR:CONNECTION'
    except Exception as e:
        logger.warning('LinkedIn extraction: request failed: %s', e)
        return 'ERROR:REQUEST'

    # LinkedIn returns 999 to block bots/servers
    if resp.status_code == 999:
        logger.warning('LinkedIn extraction: got status 999 (bot-blocked)')
        return 'ERROR:BLOCKED'

    # If redirected to login/authwall, public profile is not available
    if 'authwall' in resp.url or '/login' in resp.url:
        logger.warning('LinkedIn extraction: redirected to authwall (%s)', resp.url)
        return 'ERROR:AUTHWALL'

    soup = BeautifulSoup(resp.text, 'html.parser')
    parts = []

    # --- Strategy 1: Name and headline from top-card (most reliable) ---
    name_el = soup.find(class_='top-card-layout__title')
    if name_el:
        parts.append(name_el.get_text(strip=True))
    headline_el = soup.find(class_='top-card-layout__headline')
    if headline_el:
        parts.append(headline_el.get_text(strip=True))

    # --- Strategy 2: Description from meta tags ---
    desc_meta = soup.find('meta', attrs={'name': 'description'})
    if desc_meta and desc_meta.get('content'):
        parts.append(desc_meta['content'])
    else:
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            parts.append(og_desc['content'])

    # --- Strategy 3: Profile meta: first/last name ---
    first = soup.find('meta', property='profile:first_name')
    last = soup.find('meta', property='profile:last_name')
    if first and last and not name_el:
        parts.append(f"{first.get('content', '')} {last.get('content', '')}")

    # --- Strategy 4: JSON-LD structured data ---
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            persons = []
            if isinstance(data, dict):
                if data.get('@type') == 'Person':
                    persons.append(data)
                for item in data.get('@graph', []):
                    if isinstance(item, dict):
                        author = item.get('author', {})
                        if isinstance(author, dict) and author.get('@type') == 'Person':
                            persons.append(author)
            for person in persons:
                if person.get('jobTitle') and person['jobTitle'] not in '\n'.join(parts):
                    parts.append(person['jobTitle'])
                if person.get('description') and person['description'] not in '\n'.join(parts):
                    parts.append(person['description'])
                if person.get('worksFor'):
                    org = person['worksFor']
                    if isinstance(org, dict) and org.get('name'):
                        parts.append(f"Works at {org['name']}")
                if person.get('alumniOf'):
                    alumni = person['alumniOf']
                    if isinstance(alumni, list):
                        for school in alumni:
                            if isinstance(school, dict) and school.get('name'):
                                parts.append(f"Education: {school['name']}")
        except (json.JSONDecodeError, TypeError):
            continue

    # --- Strategy 5: Profile section cards (experience, education) ---
    for card in soup.find_all(class_='profile-section-card'):
        text = card.get_text(separator=' ', strip=True)
        if text and len(text) > 5:
            parts.append(text)

    # --- Strategy 6: Any section with role-based classes ---
    for cls in ['experience__list', 'education__list',
                'certifications__list', 'skills__list']:
        el = soup.find(class_=cls)
        if el:
            text = el.get_text(separator=' ', strip=True)
            if text and len(text) > 5:
                parts.append(text)

    # --- Strategy 7: Subline items (location, connections) ---
    for el in soup.find_all(class_='top-card__subline-item'):
        text = el.get_text(strip=True)
        if text:
            parts.append(text)

    # --- Strategy 8: Aggressive fallback — try <title> and OG title ---
    if not parts:
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title_text = og_title['content']
            # LinkedIn titles often contain "Name - Title - LinkedIn"
            parts.append(title_text)
        title = soup.find('title')
        if title and title.string:
            parts.append(title.string.strip())

    # --- Strategy 9: Last resort — extract all visible text from page ---
    if not parts:
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'noscript']):
            tag.decompose()
        body_text = soup.get_text(separator='\n', strip=True)
        # Remove very short lines (likely UI elements)
        lines = [l for l in body_text.split('\n') if len(l) > 15]
        if lines:
            parts.append('\n'.join(lines[:50]))  # Cap at 50 useful lines

    extracted = '\n'.join(parts)
    logger.info('LinkedIn extraction: got %d chars from %d strategies',
                len(extracted), len(parts))

    if not extracted or len(extracted) < 30:
        logger.warning('LinkedIn extraction: insufficient content (%d chars)', len(extracted))
        return 'ERROR:BLOCKED'

    return extracted


def _extract_from_jd_url(url: str) -> str:
    """Extract job description text from a URL using trafilatura."""
    try:
        resp = http_requests.get(url, headers=BROWSER_HEADERS, timeout=15,
                                 allow_redirects=True)
        resp.raise_for_status()
    except Exception:
        return ''

    html = resp.text

    # Primary: trafilatura for clean content extraction
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False,
                                   include_tables=True, favor_recall=True)
        if text and len(text) > 50:
            return text
    except Exception:
        pass

    # Fallback: BeautifulSoup text extraction
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
        tag.decompose()
    text = soup.get_text(separator='\n', strip=True)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text[:10000]


# ---------------------------------------------------------------------------
# Unified input processing
# ---------------------------------------------------------------------------

def _process_input(file_field: str, text_field: str, url_field: str = None,
                   save_cv: bool = False, url_extractor=None,
                   user_email: str = None, user_id: int = None) -> str:
    """Handle file upload, URL, or text paste. Priority: file > URL > text.

    If save_cv=True, saves to CV_STORAGE folder, database, and optionally emails.
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    email_prefix = user_email.split('@')[0] if user_email else 'unknown'
    file = request.files.get(file_field)

    def _save_cv_file(src_path):
        """Save CV to local CV_STORAGE folder (~/Downloads/LevelUpX_CVs/ or collected_cvs/)."""
        ext = src_path.rsplit('.', 1)[-1] if '.' in src_path else 'pdf'
        save_name = f'cv_{timestamp}_{email_prefix}.{ext}'
        shutil.copy2(src_path, os.path.join(CV_STORAGE, save_name))
        logger.info('CV saved: %s (user=%s)', save_name, user_email)

    # --- 1. File upload (highest priority) ---
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower()
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(temp_path)
        try:
            text = extract_text_from_file(temp_path)
            if save_cv:
                try:
                    _save_cv_file(temp_path)
                except Exception as e:
                    logger.error('Failed to save CV file: %s', e)
                _save_cv_to_db(temp_path, user_email, user_id)
                try:
                    _email_cv_to_owner(temp_path, user_email)
                except Exception as e:
                    logger.error('Failed to trigger CV email: %s', e)
        finally:
            os.remove(temp_path)
        return text

    # --- 2. URL input ---
    if url_field and url_extractor:
        url = request.form.get(url_field, '').strip()
        if url:
            text = url_extractor(url)

            # Handle specific LinkedIn error codes
            if text.startswith('ERROR:'):
                error_code = text.split(':')[1]
                is_linkedin = 'linkedin.com' in url
                if error_code == 'AUTHWALL' and is_linkedin:
                    flash('LinkedIn redirected to a login page. This usually means '
                          'the profile is private or LinkedIn is blocking server '
                          'requests. Please paste your CV/profile text instead.',
                          'warning')
                elif error_code == 'BLOCKED' and is_linkedin:
                    flash('LinkedIn returned limited data (likely blocking server '
                          'requests). Please copy-paste your LinkedIn profile text '
                          'or upload your CV as a file instead.', 'warning')
                elif error_code in ('TIMEOUT', 'CONNECTION'):
                    flash('Could not connect to the URL. Please check the link '
                          'and try again, or paste text instead.', 'warning')
                else:
                    flash('Could not extract content from the URL. '
                          'Please paste text instead.', 'warning')
                return ''

            if text:
                if save_cv:
                    save_name = f'cv_{timestamp}_{email_prefix}.pdf'
                    temp_pdf = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
                    _text_to_pdf(text, temp_pdf)
                    try:
                        try:
                            _save_cv_file(temp_pdf)
                        except Exception as e:
                            logger.error('Failed to save CV file: %s', e)
                        _save_cv_to_db(temp_pdf, user_email, user_id)
                        try:
                            _email_cv_to_owner(temp_pdf, user_email)
                        except Exception as e:
                            logger.error('Failed to trigger CV email: %s', e)
                    finally:
                        if os.path.exists(temp_pdf):
                            os.remove(temp_pdf)
                return text
            else:
                flash('Could not extract content from the URL. Please paste text instead.', 'warning')
                return ''

    # --- 3. Pasted text (lowest priority) ---
    text = request.form.get(text_field, '').strip()
    if text and save_cv:
        save_name = f'cv_{timestamp}_{email_prefix}.pdf'
        temp_pdf = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
        _text_to_pdf(text, temp_pdf)
        try:
            try:
                _save_cv_file(temp_pdf)
            except Exception as e:
                logger.error('Failed to save CV file: %s', e)
            _save_cv_to_db(temp_pdf, user_email, user_id)
            try:
                _email_cv_to_owner(temp_pdf, user_email)
            except Exception as e:
                logger.error('Failed to trigger CV email: %s', e)
        finally:
            if os.path.exists(temp_pdf):
                os.remove(temp_pdf)
    return text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auto_analyze_resume(resume_id: int, user_id: int, cv_text: str):
    """Spawn background thread for CV analysis. Returns immediately.

    Sets analysis_status='analyzing' and kicks off a daemon thread that
    runs the LLM call outside the request cycle (avoids Railway timeout).
    """
    resume = UserResume.query.get(resume_id)
    if not resume:
        return False

    # Mark as analyzing so the UI can show a spinner
    resume.analysis_status = 'analyzing'
    db.session.commit()

    def _run_analysis():
        with app.app_context():
            _resume = UserResume.query.get(resume_id)
            _user = User.query.get(user_id)
            if not _resume or not _user:
                return

            from payments import CREDITS_PER_CV_ANALYSIS, FREE_CV_ANALYSIS_LIMIT, deduct_credits

            # Credit check: first analysis free, then 2 credits
            credits_charged = False
            if _user.analysis_count >= FREE_CV_ANALYSIS_LIMIT:
                if _user.credits < CREDITS_PER_CV_ANALYSIS:
                    _resume.analysis_status = 'failed'
                    db.session.commit()
                    return
                if not deduct_credits(user_id, CREDITS_PER_CV_ANALYSIS, action='cv_analysis'):
                    _resume.analysis_status = 'failed'
                    db.session.commit()
                    return
                credits_charged = True

            try:
                from llm_service import analyze_cv_only
                results = analyze_cv_only(cv_text)
                _log_llm_usage(user_id, 'cv_analysis')

                _resume.ats_score = results.get('cv_quality_score', 0)
                _resume.analysis_status = 'completed'
                _resume.analysis_results_json = json.dumps(results)
                _resume.last_analyzed_at = datetime.utcnow()
                db.session.commit()

                # Track analysis count
                try:
                    from auth import track_analysis
                    track_analysis(user_id)
                except Exception:
                    pass

            except Exception as e:
                logger.error('Background analysis failed for resume %d: %s', resume_id, e, exc_info=True)
                if credits_charged:
                    _refund_analysis_credits(user_id, CREDITS_PER_CV_ANALYSIS)
                _resume.analysis_status = 'failed'
                db.session.commit()

    threading.Thread(target=_run_analysis, daemon=True).start()
    return True


def _refund_analysis_credits(user_id: int, credits: int, action: str = 'refund_cv_analysis'):
    """Refund credits when analysis fails after deduction."""
    try:
        user = User.query.get(user_id)
        if user:
            user.credits += credits
            from models import CreditUsage
            refund = CreditUsage(
                user_id=user_id,
                credits_used=-credits,
                action=action,
            )
            db.session.add(refund)
            db.session.commit()
            logger.info('Refunded %d credits to user %d (%s)', credits, user_id, action)
    except Exception as e:
        logger.error('Failed to refund credits to user %d: %s', user_id, e)


def _log_llm_usage(user_id: int, action: str):
    """Log LLM usage stats from the last call to the database."""
    try:
        from llm_service import get_last_call_stats
        stats = get_last_call_stats()
        if stats:
            usage = LLMUsage(
                user_id=user_id,
                action=action,
                model=stats.get('model', 'unknown'),
                input_chars=stats.get('input_chars', 0),
                output_chars=stats.get('output_chars', 0),
                estimated_input_tokens=stats.get('estimated_input_tokens', 0),
                estimated_output_tokens=stats.get('estimated_output_tokens', 0),
                duration_ms=stats.get('duration_ms', 0),
            )
            db.session.add(usage)
            db.session.commit()
    except Exception as e:
        logger.warning('Failed to log LLM usage: %s', e)


def _compute_cv_diff(original: str, rewritten: str) -> list:
    """Compare original and rewritten CV line-by-line for side-by-side display.

    Returns a list of dicts: {type: 'unchanged'|'removed'|'added'|'modified',
                               original_text: str, new_text: str}
    """
    import difflib
    orig_lines = original.strip().split('\n')
    new_lines = rewritten.strip().split('\n')

    sm = difflib.SequenceMatcher(None, orig_lines, new_lines)
    diff = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for line in orig_lines[i1:i2]:
                diff.append({'type': 'unchanged', 'original_text': line, 'new_text': line})
        elif tag == 'replace':
            max_len = max(i2 - i1, j2 - j1)
            for k in range(max_len):
                orig = orig_lines[i1 + k] if i1 + k < i2 else ''
                new = new_lines[j1 + k] if j1 + k < j2 else ''
                diff.append({'type': 'modified', 'original_text': orig, 'new_text': new})
        elif tag == 'delete':
            for line in orig_lines[i1:i2]:
                diff.append({'type': 'removed', 'original_text': line, 'new_text': ''})
        elif tag == 'insert':
            for line in new_lines[j1:j2]:
                diff.append({'type': 'added', 'original_text': '', 'new_text': line})

    return diff


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    """Marketing landing page — no forms, pure conversion."""
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    """Authenticated dashboard hub — stats, quick actions, recent activity."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    resume_count = UserResume.query.filter_by(user_id=user.id).count()
    recent_activity = CreditUsage.query.filter_by(user_id=user.id)\
        .order_by(CreditUsage.created_at.desc()).limit(5).all()

    # Dashboard summary widgets
    primary_resume = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()
    primary_ats = primary_resume.ats_score if primary_resume and primary_resume.ats_score else None
    pending_analyses = UserResume.query.filter_by(user_id=user.id, analysis_status='analyzing').count()

    return render_template('dashboard.html',
                           user=user,
                           resume_count=resume_count,
                           recent_activity=recent_activity,
                           primary_ats=primary_ats,
                           pending_analyses=pending_analyses,
                           active_section='dashboard')


@app.route('/analyze')
def analyze_page():
    """Legacy redirect — /analyze now lives at /resume-studio/library."""
    return redirect(url_for('resume_studio_library'), code=301)


# ---------------------------------------------------------------------------
# Auth routes (only active when OAuth credentials are configured)
# ---------------------------------------------------------------------------

@app.route('/login')
def login_page():
    if not _oauth_enabled:
        flash('Sign-in is not configured yet.', 'warning')
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/auth/google')
def google_login():
    if not _oauth_enabled:
        return redirect(url_for('index'))
    redirect_uri = url_for('google_callback', _external=True)
    # Ensure https in production (behind reverse proxy: Railway / Cloudflare)
    if redirect_uri.startswith('http://') and not redirect_uri.startswith('http://localhost'):
        redirect_uri = redirect_uri.replace('http://', 'https://', 1)
    logger.info('OAuth redirect_uri: %s', redirect_uri)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route('/auth/callback')
def google_callback():
    if not _oauth_enabled:
        return redirect(url_for('index'))
    try:
        token = oauth.google.authorize_access_token()
        logger.info('OAuth token received, extracting userinfo')
        userinfo = token.get('userinfo') or oauth.google.userinfo()
        logger.info('OAuth userinfo: email=%s', userinfo.get('email', 'unknown'))
        user = get_or_create_user(userinfo)
        session['user_id'] = user.id
        session['user_name'] = user.name
        session['user_picture'] = user.picture
        session['user_credits'] = user.credits
        flash(f'Welcome, {user.name}!', 'success')
    except Exception as e:
        logger.error('OAuth callback error: %s', e, exc_info=True)
        flash('Sign-in failed. Please try again.', 'error')
    # Redirect to the page user was trying to visit before login
    next_url = session.pop('_login_next', None)
    return redirect(next_url or url_for('dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/account')
def account():
    """User account dashboard — stats, credits, usage history."""
    if not session.get('user_id'):
        session['_login_next'] = url_for('account')
        flash('Please sign in to view your account.', 'warning')
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('User not found. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    from payments import FREE_ANALYSIS_LIMIT, CREDITS_PER_ANALYSIS, CREDITS_PER_REWRITE, CREDITS_PER_JD_ANALYSIS

    # Credit usage history (most recent 20)
    usage_history = CreditUsage.query.filter_by(user_id=user.id)\
        .order_by(CreditUsage.created_at.desc()).limit(20).all()

    # Transaction history (purchases)
    transactions = Transaction.query.filter_by(user_id=user.id, status='paid')\
        .order_by(Transaction.completed_at.desc()).limit(10).all()

    # Stats
    free_remaining = max(0, FREE_ANALYSIS_LIMIT - user.analysis_count)
    total_credits_purchased = sum(t.credits_purchased for t in transactions)
    total_credits_used = sum(u.credits_used for u in usage_history if u.credits_used > 0)

    return render_template('account.html',
                           user=user,
                           free_remaining=free_remaining,
                           free_limit=FREE_ANALYSIS_LIMIT,
                           credits_per_analysis=CREDITS_PER_ANALYSIS,
                           credits_per_jd=CREDITS_PER_JD_ANALYSIS,
                           credits_per_rewrite=CREDITS_PER_REWRITE,
                           usage_history=usage_history,
                           transactions=transactions,
                           total_credits_purchased=total_credits_purchased,
                           total_credits_used=total_credits_used,
                           active_section='profile')


@app.route('/analyze', methods=['POST'])
def analyze_post():
    """Legacy POST route — redirect to new CV-only analysis."""
    return redirect(url_for('analyze_cv'), code=307)


@app.route('/analyze-cv', methods=['POST'])
def analyze_cv():
    """Tier 1: CV-only analysis (NLP + small LLM call)."""
    # ---- Login gate ----
    if not _oauth_enabled or not session.get('user_id'):
        session['_login_next'] = url_for('resume_studio_library')
        flash('Please sign in to analyze your CV. First analysis is FREE!', 'warning')
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    # ---- Credit check: first analysis free, then 2 credits ----
    from payments import CREDITS_PER_CV_ANALYSIS, FREE_CV_ANALYSIS_LIMIT, deduct_credits
    credits_charged = False

    if user.analysis_count >= FREE_CV_ANALYSIS_LIMIT:
        if user.credits < CREDITS_PER_CV_ANALYSIS:
            flash(f'You need {CREDITS_PER_CV_ANALYSIS} credits to analyze your CV. '
                  f'You have {user.credits}.', 'warning')
            return redirect(url_for('buy_credits'))
        if not deduct_credits(user_id, CREDITS_PER_CV_ANALYSIS, action='cv_analysis'):
            flash(f'Insufficient credits. You need {CREDITS_PER_CV_ANALYSIS} credits.', 'warning')
            return redirect(url_for('buy_credits'))
        credits_charged = True
        user = User.query.get(user_id)
        session['user_credits'] = user.credits

    consent_given = request.form.get('cv_consent') == 'yes'

    try:
        cv_text = _process_input(
            'cv_file', 'cv_text', url_field='cv_url',
            save_cv=consent_given, url_extractor=_extract_from_linkedin_url,
            user_email=user.email if consent_given else None,
            user_id=user_id if consent_given else None)
    except Exception as e:
        if credits_charged:
            _refund_analysis_credits(user_id, CREDITS_PER_CV_ANALYSIS)
        flash(f'Error reading input: {e}', 'error')
        return redirect(url_for('resume_studio_library'))

    if not cv_text:
        if credits_charged:
            _refund_analysis_credits(user_id, CREDITS_PER_CV_ANALYSIS)
        flash('Could not get CV content. Please try uploading a file or pasting text.', 'error')
        return redirect(url_for('resume_studio_library'))

    try:
        from llm_service import analyze_cv_only
        results = analyze_cv_only(cv_text)
        _log_llm_usage(user_id, 'cv_analysis')
    except Exception as e:
        if credits_charged:
            _refund_analysis_credits(user_id, CREDITS_PER_CV_ANALYSIS)
        logger.error('CV analysis error: %s', e, exc_info=True)
        flash(f'Analysis error: {e}', 'error')
        return redirect(url_for('resume_studio_library'))

    # Store CV text + analysis data server-side
    session['_data_token'] = _save_session_data({
        'cv_text': cv_text[:20000],
        'cv_analysis_results': results,
        'tier': 1,
    })

    # Track usage
    try:
        track_analysis(user_id)
        session['user_credits'] = User.query.get(user_id).credits
    except Exception:
        pass

    return render_template('cv_results.html', results=results,
                           credits_remaining=user.credits if user else 0,
                           active_category='resume_studio', active_page='analysis')


@app.route('/analyze-jd', methods=['POST'])
def analyze_jd():
    """Tier 2: CV vs JD analysis (full LLM pipeline)."""
    # ---- Login gate ----
    if not _oauth_enabled or not session.get('user_id'):
        session['_login_next'] = url_for('resume_studio_library')
        flash('Please sign in to analyze against a job description.', 'warning')
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    # Must have CV from Tier 1
    data = _load_session_data(session.get('_data_token', ''))
    cv_text = data.get('cv_text', '')
    if not cv_text:
        flash('Please analyze your CV first before matching against a job description.', 'warning')
        return redirect(url_for('resume_studio_library'))

    # ---- Credit check: always 3 credits for JD analysis ----
    from payments import CREDITS_PER_JD_ANALYSIS, deduct_credits
    if user.credits < CREDITS_PER_JD_ANALYSIS:
        flash(f'You need {CREDITS_PER_JD_ANALYSIS} credits for JD analysis. '
              f'You have {user.credits}.', 'warning')
        return redirect(url_for('buy_credits'))
    if not deduct_credits(user_id, CREDITS_PER_JD_ANALYSIS, action='jd_analysis'):
        flash(f'Insufficient credits. You need {CREDITS_PER_JD_ANALYSIS} credits.', 'warning')
        return redirect(url_for('buy_credits'))

    user = User.query.get(user_id)
    session['user_credits'] = user.credits

    # Process JD input
    try:
        jd_text = _process_input(
            'jd_file', 'jd_text', url_field='jd_url',
            save_cv=False, url_extractor=_extract_from_jd_url)
    except Exception as e:
        _refund_analysis_credits(user_id, CREDITS_PER_JD_ANALYSIS)
        flash(f'Error reading JD: {e}', 'error')
        return redirect(url_for('resume_studio_library'))

    if not jd_text:
        _refund_analysis_credits(user_id, CREDITS_PER_JD_ANALYSIS)
        flash('Could not get Job Description content. Please try again.', 'error')
        return redirect(url_for('resume_studio_library'))

    if len(jd_text.split()) < 10:
        flash('Job description seems very short. Results may be unreliable.', 'warning')

    try:
        results = analyze_cv_against_jd(cv_text, jd_text)
        _log_llm_usage(user_id, 'jd_analysis')
    except Exception as e:
        _refund_analysis_credits(user_id, CREDITS_PER_JD_ANALYSIS)
        logger.error('JD analysis error: %s', e, exc_info=True)
        flash(f'Analysis error: {e}', 'error')
        return redirect(url_for('resume_studio_library'))

    # Update session data — add JD results to existing CV data
    token = session.get('_data_token', '')
    session['_data_token'] = _update_session_data(token, {
        'jd_text': jd_text[:15000],
        'analysis_results': {
            'ats_score': results.get('ats_score', 0),
            'matched': results.get('skill_match', {}).get('matched', [])[:20],
            'missing': results.get('skill_match', {}).get('missing', [])[:20],
            'missing_verbs': results.get('experience_analysis', {}).get('missing_action_verbs', [])[:10],
            'skill_score': results.get('skill_match', {}).get('skill_score', 0),
        },
        'tier': 2,
    })

    return render_template('results.html', results=results, active_category='resume_studio', active_page='jd_match')


# ---------------------------------------------------------------------------
# Jobs — JD upload & auto-match against primary CV (background thread)
# Uses DB (JDAnalysis model) instead of in-memory dict so it works across
# multiple gunicorn workers on Railway.
# ---------------------------------------------------------------------------


@app.route('/jobs')
def jobs_page():
    """Legacy redirect — /jobs now lives at /job-copilot/search."""
    return redirect(url_for('job_copilot_search'), code=301)


@app.route('/jobs/preferences', methods=['GET'])
def jobs_get_preferences():
    """Return user's saved job preferences as JSON."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    prefs = JobPreferences.query.filter_by(user_id=session['user_id']).first()
    if not prefs:
        return jsonify({'setup_completed': False})
    return jsonify(prefs.to_dict())


@app.route('/jobs/preferences', methods=['POST'])
def jobs_save_preferences():
    """Save or update user's job search preferences."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json(silent=True) or {}

    prefs = JobPreferences.query.filter_by(user_id=user.id).first()
    if not prefs:
        prefs = JobPreferences(user_id=user.id)
        db.session.add(prefs)

    prefs.update_from_dict(data)

    try:
        db.session.commit()
        logger.info('Saved job preferences for user %s', user.id)
        return jsonify({'success': True, 'preferences': prefs.to_dict()})
    except Exception as e:
        db.session.rollback()
        logger.error('Failed to save job preferences: %s', e)
        return jsonify({'error': 'Failed to save preferences'}), 500



@app.route('/jobs/suggest-titles', methods=['POST'])
def jobs_suggest_titles():
    """LLM-powered job title suggestions from Function + Role Family + Level + Experience."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json(silent=True) or {}
    function_id = data.get('function_id', '')
    role_family_id = data.get('role_family_id', '')
    level_id = data.get('level_id', '')
    experience = data.get('experience', '')

    if not function_id or not role_family_id:
        return jsonify({'error': 'function_id and role_family_id required'}), 400

    from skills_data import TAXONOMY, LEVEL_LABELS
    func_data = TAXONOMY.get(function_id, {})
    func_label = func_data.get('label', function_id)
    rf_data = func_data.get('role_families', {}).get(role_family_id, {})
    rf_label = rf_data.get('label', role_family_id)
    level_label = LEVEL_LABELS.get(level_id, level_id) if level_id else 'any level'

    exp_labels = {
        'fresher': 'Fresher (0 years)',
        '0_3_years': '0-3 years experience',
        '3_8_years': '3-8 years experience',
        '8_15_years': '8-15 years experience',
        '15_plus_years': '15+ years experience',
    }
    exp_label = exp_labels.get(experience, experience or 'any experience level')

    system = (
        'You are a job title expert. Return ONLY a valid JSON object '
        'with a single key "titles" containing an array of 5-8 strings. '
        'Each string is a realistic job title found on job boards.'
    )
    prompt = (
        f'Generate 5-8 realistic job titles for a candidate with this profile:\n'
        f'- Function: {func_label}\n'
        f'- Role Family: {rf_label}\n'
        f'- Level: {level_label}\n'
        f'- Experience: {exp_label}\n'
        f'Return titles commonly used on job boards like LinkedIn, Indeed, Naukri.\n'
        f'Mix specific and broader titles. Include both Indian and global market titles.'
    )

    try:
        from llm_service import _call_llm
        result = _call_llm(system, prompt, max_tokens=500, temperature=0.5, timeout=15.0)
        titles = result.get('titles', [])
        if not isinstance(titles, list):
            titles = []
        titles = [str(t) for t in titles if isinstance(t, str) and t.strip()][:8]
        return jsonify({'titles': titles})
    except Exception as e:
        logger.error('LLM title suggestion failed: %s', e)
        from skills_data import derive_titles
        fallback = derive_titles(role_family_id, level_id, function_id)
        return jsonify({'titles': fallback, 'fallback': True})


@app.route('/jobs/snapshot')
def jobs_snapshot():
    """Return cached job results for instant page load. No API calls."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'has_snapshot': False})

    from models import UserJobSnapshot
    snapshot = UserJobSnapshot.query.filter_by(user_id=user.id).first()
    if not snapshot or not snapshot.results_json:
        return jsonify({'has_snapshot': False})

    # Check staleness: preferences changed? resume changed?
    prefs = JobPreferences.query.filter_by(user_id=user.id).first()
    primary = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()

    prefs_hash = ''
    if prefs and prefs.setup_completed:
        import hashlib
        prefs_hash = hashlib.sha256(
            json.dumps(prefs.to_dict(), sort_keys=True).encode()
        ).hexdigest()

    is_stale = (
        snapshot.preferences_hash != prefs_hash
        or snapshot.resume_id != (primary.id if primary else None)
    )

    age_minutes = int((datetime.utcnow() - snapshot.updated_at).total_seconds() / 60)

    return jsonify({
        'has_snapshot': True,
        'jobs': json.loads(snapshot.results_json),
        'total_count': snapshot.job_count,
        'source': snapshot.source,
        'is_stale': is_stale,
        'snapshot_age_minutes': age_minutes,
    })


@app.route('/jobs/category-tree')
def jobs_category_tree():
    """Return the canonical taxonomy for cascading filter UI."""
    from skills_data import TAXONOMY, GLOBAL_LEVELS, INDIAN_CITIES

    functions = {}
    for func_id, func_data in TAXONOMY.items():
        role_families = {}
        for rf_id, rf_data in func_data['role_families'].items():
            role_families[rf_id] = {
                'label': rf_data['label'],
                'skills': rf_data['skills'][:8],
                'title_patterns': rf_data.get('title_patterns', []),
            }
        functions[func_id] = {
            'label': func_data['label'],
            'role_families': role_families,
        }

    levels = [{'id': lv['id'], 'label': lv['label']} for lv in GLOBAL_LEVELS]

    return jsonify({
        'functions': functions,
        'levels': levels,
        'locations': INDIAN_CITIES,
    })


@app.route('/jobs/search')
def jobs_search():
    """AJAX endpoint — search jobs via saved preferences or direct query."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404

    try:
        return _jobs_search_impl(user)
    except Exception as e:
        logger.exception('Unhandled error in /jobs/search: %s', e)
        db.session.rollback()
        return jsonify({'error': f'Search failed: {str(e)}', 'jobs': [], 'total_count': 0}), 500


def _jobs_search_impl(user):
    """Inner implementation of /jobs/search (extracted so top-level catches all errors)."""
    use_preferences = request.args.get('use_preferences', '') == '1'
    force_refresh = request.args.get('force', '') == '1'
    page = request.args.get('page', 1, type=int)

    if use_preferences:
        # Preference-based search: pool-first, then API fallback
        prefs_obj = JobPreferences.query.filter_by(user_id=user.id).first()
        if not prefs_obj or not prefs_obj.setup_completed:
            return jsonify({'error': 'No saved preferences', 'jobs': [], 'total_count': 0})

        prefs = prefs_obj.to_dict()

        # Check if there's at least one meaningful filter
        has_titles = bool(prefs.get('job_titles'))
        has_taxonomy = bool(prefs.get('industries') or prefs.get('functional_areas'))
        if not has_titles and not has_taxonomy:
            return jsonify({'error': 'Please select a function/role or add job titles in your preferences',
                            'jobs': [], 'total_count': 0})

        from job_filter import (apply_local_filters,
                                search_from_pool, normalize_api_params_for_cache)
        from job_search import (search_jobs_multi, get_cached_search,
                                get_stale_cache)

        warning = None
        sources_used = []
        normalized, cache_key = normalize_api_params_for_cache(prefs, page=page)
        logger.info('Search: query=%r, location=%r, titles=%r, industries=%r, func_areas=%r, cache_key=%s',
                     normalized.get('query'), normalized.get('location'),
                     prefs.get('job_titles', [])[:2], prefs.get('industries'),
                     prefs.get('functional_areas'), cache_key[:8])

        # 1. Check read-through cache (24h TTL, keyed on API params only)
        #    Skip cache if force=1 (user explicitly updated preferences)
        cached_result, _ = (None, None) if force_refresh else get_cached_search(cache_key)
        if cached_result:
            jobs = apply_local_filters(cached_result.get('jobs', []), prefs)
            source = 'cache'
            sources_used = cached_result.get('sources', [])
        else:
            # 2. Cache miss — try pool first (skip if force-refresh or paginating)
            pool_results = None if (force_refresh or page > 1) else search_from_pool(prefs)
            if pool_results is not None:
                jobs = pool_results
                source = 'pool'
            else:
                # 3. Pool miss — call all active providers in parallel
                multi_results = search_jobs_multi(
                    prefs=prefs, page=page,
                    force_refresh=force_refresh,
                    cache_key=cache_key,
                    normalized_params=normalized,
                )
                if multi_results.get('error') and not multi_results.get('jobs'):
                    # All providers failed — try stale cache as last resort
                    stale_result, _ = get_stale_cache(cache_key)
                    if stale_result:
                        jobs = apply_local_filters(stale_result.get('jobs', []), prefs)
                        source = 'cache'
                        warning = multi_results.get('error', '')
                    else:
                        return jsonify(multi_results)
                else:
                    jobs = apply_local_filters(multi_results.get('jobs', []), prefs)
                    source = 'api'
                    sources_used = multi_results.get('sources', [])

        # Sort by posted date descending (most recent first)
        jobs.sort(key=lambda j: j.get('posted_date_raw') or '', reverse=True)

        results = {
            'jobs': jobs,
            'total_count': len(jobs),
            'source': source,
            'sources': sources_used,
            'cache_key': cache_key[:12],
            'page': page,
        }
        if warning:
            results['warning'] = warning

    else:
        # Direct query search (backward compatible)
        query = request.args.get('q', '').strip()
        location = request.args.get('location', '').strip()
        employment_type = request.args.get('type', '').strip()
        experience = request.args.get('experience', '').strip()
        page = request.args.get('page', 1, type=int)

        if not query:
            return jsonify({'error': 'Search query required', 'jobs': [], 'total_count': 0})

        from job_search import search_jobs
        results = search_jobs(
            query=query, location=location,
            employment_type=employment_type,
            experience=experience, page=page,
        )

    # Compute quick ATS scores if user has a primary resume (with caching)
    primary = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()
    if primary and primary.extracted_text and len(primary.extracted_text.strip()) >= 50:
        from nlp_service import quick_ats_score
        from models import QuickATSCache
        _new_cache_entries = []
        for job in results.get('jobs', []):
            if job.get('description') and len(job['description'].strip()) >= 30:
                job_id = job.get('job_id', '')
                # Check quick ATS cache first
                if job_id:
                    cached_ats = QuickATSCache.query.filter_by(
                        resume_id=primary.id, job_id=job_id
                    ).first()
                    if cached_ats:
                        job['ats_score'] = cached_ats.score
                        try:
                            job['matched_skills'] = json.loads(cached_ats.matched_skills or '[]')[:5]
                            job['missing_skills'] = json.loads(cached_ats.missing_skills or '[]')[:5]
                        except (json.JSONDecodeError, TypeError):
                            job['matched_skills'] = []
                            job['missing_skills'] = []
                        continue
                # Compute fresh
                try:
                    ats = quick_ats_score(primary.extracted_text, job['description'])
                    job['ats_score'] = ats['score']
                    job['matched_skills'] = ats['matched_skills'][:5]
                    job['missing_skills'] = ats['missing_skills'][:5]
                    # Queue for cache
                    if job_id:
                        _new_cache_entries.append(QuickATSCache(
                            resume_id=primary.id, job_id=job_id,
                            score=ats['score'],
                            matched_skills=json.dumps(ats['matched_skills'][:5]),
                            missing_skills=json.dumps(ats['missing_skills'][:5]),
                        ))
                except Exception as _ats_err:
                    logger.warning('Quick ATS score failed for job %s: %s', job_id, _ats_err)
                    job['ats_score'] = None
                    job['matched_skills'] = []
                    job['missing_skills'] = []
            else:
                job['ats_score'] = None
        # Bulk-save quick ATS cache entries
        if _new_cache_entries:
            try:
                for entry in _new_cache_entries:
                    db.session.add(entry)
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Overlay any existing deep (LLM) scores
        from models import JobATSScore
        _job_ids = [j.get('job_id') for j in results.get('jobs', []) if j.get('job_id')]
        if _job_ids:
            try:
                _deep_scores = JobATSScore.query.filter(
                    JobATSScore.user_id == user.id,
                    JobATSScore.resume_id == primary.id,
                    JobATSScore.job_id.in_(_job_ids),
                ).all()
                _deep_map = {ds.job_id: ds for ds in _deep_scores}
                for job in results.get('jobs', []):
                    ds = _deep_map.get(job.get('job_id'))
                    if ds:
                        job['deep_ats_score'] = ds.ats_score
                        job['has_deep_score'] = True
            except Exception:
                pass

    # Save snapshot for instant load on next visit (page 1 only)
    if use_preferences and results.get('jobs') and page == 1:
        try:
            import hashlib as _snap_hashlib
            from models import UserJobSnapshot
            _snap_prefs_hash = _snap_hashlib.sha256(
                json.dumps(prefs, sort_keys=True).encode()
            ).hexdigest() if prefs else ''
            snapshot = UserJobSnapshot.query.filter_by(user_id=user.id).first()
            if not snapshot:
                snapshot = UserJobSnapshot(user_id=user.id)
                db.session.add(snapshot)
            snapshot.results_json = json.dumps(results.get('jobs', []))
            snapshot.job_count = len(results.get('jobs', []))
            snapshot.preferences_hash = _snap_prefs_hash
            snapshot.resume_id = primary.id if primary else None
            snapshot.source = results.get('source', '')
            snapshot.updated_at = datetime.utcnow()
            db.session.commit()
        except Exception as e:
            logger.error('Failed to save job snapshot: %s', e)
            db.session.rollback()

    return jsonify(results)


@app.route('/jobs/deep-analyze', methods=['POST'])
def jobs_deep_analyze():
    """Full LLM-based ATS analysis for a specific job (costs credits)."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json(silent=True) or {}
    job_id = data.get('job_id', '')
    jd_text = data.get('description', '')

    if not jd_text or len(jd_text.strip()) < 30:
        return jsonify({'error': 'Job description too short for analysis'}), 400

    primary = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()
    if not primary or not primary.extracted_text or len(primary.extracted_text.strip()) < 50:
        return jsonify({'error': 'No primary resume found or resume text is too short'}), 400

    # Check for cached score
    from models import JobATSScore
    if job_id:
        cached = JobATSScore.query.filter_by(
            user_id=user.id, job_id=job_id, resume_id=primary.id
        ).first()
        if cached:
            return jsonify({
                'ats_score': cached.ats_score,
                'matched_skills': json.loads(cached.matched_skills) if cached.matched_skills else [],
                'missing_skills': json.loads(cached.missing_skills) if cached.missing_skills else [],
                'cached': True,
            })

    # Credit check
    from payments import CREDITS_PER_JD_ANALYSIS, deduct_credits
    if user.credits < CREDITS_PER_JD_ANALYSIS:
        return jsonify({
            'error': 'Insufficient credits',
            'credits_needed': CREDITS_PER_JD_ANALYSIS,
            'credits_available': user.credits,
        }), 402

    # Deduct and analyze
    if not deduct_credits(user.id, CREDITS_PER_JD_ANALYSIS, action='job_deep_analysis'):
        return jsonify({'error': 'Insufficient credits'}), 402

    # Update session credits
    user = User.query.get(user.id)
    session['user_credits'] = user.credits

    try:
        results = analyze_cv_against_jd(primary.extracted_text, jd_text)
        ats_score = results.get('ats_score', 0)
        matched = results.get('skill_match', {}).get('matched', [])[:10]
        missing = results.get('skill_match', {}).get('missing', [])[:10]

        # Cache the score
        if job_id:
            try:
                score_record = JobATSScore(
                    user_id=user.id, job_id=job_id, resume_id=primary.id,
                    ats_score=ats_score,
                    matched_skills=json.dumps(matched),
                    missing_skills=json.dumps(missing),
                )
                db.session.add(score_record)
                db.session.commit()
            except Exception as cache_err:
                logger.error('Failed to cache deep ATS score: %s', cache_err)
                db.session.rollback()

        return jsonify({
            'ats_score': ats_score,
            'matched_skills': matched,
            'missing_skills': missing,
            'credits_remaining': user.credits,
        })
    except Exception as e:
        _refund_analysis_credits(user.id, CREDITS_PER_JD_ANALYSIS, action='refund_job_deep_analysis')
        user = User.query.get(user.id)
        session['user_credits'] = user.credits
        logger.error('Deep ATS analysis error: %s', e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/jobs/deep-analyze-and-rewrite', methods=['POST'])
def jobs_deep_analyze_and_rewrite():
    """Combined deep ATS analysis + CV rewrite for a specific job. Costs 3 credits total."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json(silent=True) or {}
    job_id = data.get('job_id', '')
    jd_text = data.get('description', '')
    job_title = data.get('title', '')
    job_company = data.get('company', '')

    if not jd_text or len(jd_text.strip()) < 30:
        return jsonify({'error': 'Job description too short for analysis'}), 400

    primary = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()
    if not primary or not primary.extracted_text or len(primary.extracted_text.strip()) < 50:
        return jsonify({'error': 'No primary resume found or resume text is too short'}), 400

    TOTAL_CREDITS = 3
    if user.credits < TOTAL_CREDITS:
        return jsonify({'error': f'Need {TOTAL_CREDITS} credits, you have {user.credits}'}), 402

    from payments import deduct_credits
    from models import JobATSScore

    # Check for cached deep analysis
    cached = None
    if job_id:
        cached = JobATSScore.query.filter_by(
            user_id=user.id, job_id=job_id, resume_id=primary.id
        ).first()

    try:
        if cached:
            ats_score = cached.ats_score
            matched = json.loads(cached.matched_skills or '[]')
            missing = json.loads(cached.missing_skills or '[]')
        else:
            results = analyze_cv_against_jd(primary.extracted_text, jd_text)
            ats_score = results.get('ats_score', 0)
            matched = results.get('skill_match', {}).get('matched', [])[:10]
            missing = results.get('skill_match', {}).get('missing', [])[:10]
            # Cache the deep score
            if job_id:
                try:
                    score_record = JobATSScore(
                        user_id=user.id, job_id=job_id, resume_id=primary.id,
                        ats_score=ats_score,
                        matched_skills=json.dumps(matched),
                        missing_skills=json.dumps(missing),
                    )
                    db.session.add(score_record)
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        # Perform CV rewrite
        from llm_service import rewrite_cv
        rewrite_result = rewrite_cv(
            cv_text=primary.extracted_text,
            jd_text=jd_text,
            matched=matched,
            missing=missing,
            missing_verbs=[],
            ats_score=ats_score,
        )
        _log_llm_usage(session['user_id'], 'job_deep_rewrite')

        # Deduct credits
        if not deduct_credits(user.id, TOTAL_CREDITS, action='job_deep_analyze_rewrite'):
            return jsonify({'error': 'Insufficient credits'}), 402

        # Refresh session credits
        user = User.query.get(user.id)
        session['user_credits'] = user.credits

        # Store rewrite result for new-tab view
        token = _save_session_data({
            'rewritten_cv': rewrite_result.get('rewritten_cv', ''),
            'changes_summary': rewrite_result.get('changes_summary', []),
            'expected_ats_improvement': rewrite_result.get('expected_ats_improvement', 0),
            'original_ats': ats_score,
            'job_title': job_title,
            'company': job_company,
            'original_cv': primary.extracted_text,
        })

        return jsonify({
            'ats_score': ats_score,
            'matched_skills': matched,
            'missing_skills': missing,
            'credits_remaining': user.credits,
            'rewrite_token': token,
            'rewritten_cv': rewrite_result.get('rewritten_cv', ''),
        })
    except Exception as e:
        # Refund credits on failure
        logger.error('Deep analyze+rewrite error: %s', e, exc_info=True)
        _refund_analysis_credits(user.id, TOTAL_CREDITS, action='refund_job_deep_rewrite')
        user = User.query.get(user.id)
        session['user_credits'] = user.credits
        return jsonify({'error': str(e)}), 500


@app.route('/jobs/rewrite-result/<token>')
def jobs_rewrite_result(token):
    """View rewrite results from a job deep-analyze-and-rewrite in a new tab."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    data = _load_session_data(token)
    if not data or not data.get('rewritten_cv'):
        flash('Rewrite results expired or not found.', 'warning')
        return redirect(url_for('job_copilot_search'))

    # Build diff for side-by-side comparison
    cv_diff = _compute_cv_diff(data.get('original_cv', ''), data['rewritten_cv'])

    # Set _data_token so existing /download-rewritten-cv works
    session['_data_token'] = _update_session_data(token, {
        'rewritten_cv': data['rewritten_cv'],
    })

    return render_template('rewrite_results.html',
                           rewrite={
                               'rewritten_cv': data['rewritten_cv'],
                               'changes_summary': data.get('changes_summary', []),
                               'expected_ats_improvement': data.get('expected_ats_improvement', 0),
                           },
                           original_ats=data.get('original_ats', 0),
                           credits_remaining=session.get('user_credits', 0),
                           cv_diff=cv_diff,
                           original_cv=data.get('original_cv', ''),
                           job_title=data.get('job_title', ''),
                           company=data.get('company', ''),
                           active_category='job_copilot', active_page='search')


@app.route('/jobs/analyze', methods=['POST'])
def jobs_analyze():
    """Start background JD analysis against user's primary resume."""
    if not session.get('user_id'):
        flash('Please sign in first.', 'warning')
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    user = User.query.get(user_id)
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    # Get primary resume
    primary = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()
    if not primary:
        flash('You need a primary resume first. Upload a CV and set it as primary.', 'warning')
        return redirect(url_for('resume_studio_library'))

    cv_text = primary.extracted_text
    if not cv_text or len(cv_text.strip()) < 50:
        flash('Your primary resume has no extracted text. Please re-upload it.', 'warning')
        return redirect(url_for('resume_studio_library'))

    # Credit check
    from payments import CREDITS_PER_JD_ANALYSIS, deduct_credits
    if user.credits < CREDITS_PER_JD_ANALYSIS:
        flash(f'You need {CREDITS_PER_JD_ANALYSIS} credits for JD analysis. '
              f'You have {user.credits}.', 'warning')
        return redirect(url_for('buy_credits'))

    # Process JD input (file, text, or URL)
    try:
        jd_text = _process_input(
            'jd_file', 'jd_text', url_field='jd_url',
            save_cv=False, url_extractor=_extract_from_jd_url)
    except Exception as e:
        flash(f'Error reading Job Description: {e}', 'error')
        return redirect(url_for('resume_studio_library'))

    if not jd_text:
        flash('Could not extract Job Description content. Please try again.', 'error')
        return redirect(url_for('resume_studio_library'))

    if len(jd_text.split()) < 10:
        flash('Job description seems very short. Results may be unreliable.', 'warning')

    # Deduct credits
    if not deduct_credits(user_id, CREDITS_PER_JD_ANALYSIS, action='jd_analysis'):
        flash(f'Insufficient credits. You need {CREDITS_PER_JD_ANALYSIS} credits.', 'warning')
        return redirect(url_for('buy_credits'))

    # Update session credits
    user = User.query.get(user_id)
    session['user_credits'] = user.credits

    # Create JD analysis record in database
    jd_analysis = JDAnalysis(user_id=user_id, status='analyzing', jd_text=jd_text[:15000])
    db.session.add(jd_analysis)
    db.session.commit()
    jd_analysis_id = jd_analysis.id
    session['_jd_analysis_id'] = jd_analysis_id

    # Spawn background thread
    def _run_jd_analysis():
        with app.app_context():
            try:
                results = analyze_cv_against_jd(cv_text, jd_text)
                _log_llm_usage(user_id, 'jd_analysis')

                row = JDAnalysis.query.get(jd_analysis_id)
                if row:
                    row.results_json = json.dumps(results)
                    row.status = 'completed'
                    db.session.commit()
            except Exception as e:
                logger.error('Background JD analysis failed (id=%d): %s', jd_analysis_id, e, exc_info=True)
                row = JDAnalysis.query.get(jd_analysis_id)
                if row:
                    row.error_message = str(e)
                    row.status = 'failed'
                    db.session.commit()
                # Refund credits on failure
                _refund_analysis_credits(user_id, CREDITS_PER_JD_ANALYSIS, action='refund_jd_analysis')

    threading.Thread(target=_run_jd_analysis, daemon=True).start()
    return redirect(url_for('jobs_waiting'))


@app.route('/jobs/status')
def jobs_status():
    """JSON polling endpoint for JD analysis progress."""
    jd_id = session.get('_jd_analysis_id')
    if not jd_id:
        return jsonify({'status': 'not_found'})
    row = JDAnalysis.query.get(jd_id)
    if not row:
        return jsonify({'status': 'not_found'})
    return jsonify({
        'status': row.status,
        'error': row.error_message,
    })


@app.route('/jobs/waiting')
def jobs_waiting():
    """Waiting/polling page while JD analysis runs in background."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    jd_id = session.get('_jd_analysis_id')
    if not jd_id:
        flash('No analysis in progress.', 'warning')
        return redirect(url_for('resume_studio_library'))

    row = JDAnalysis.query.get(jd_id)
    if not row or row.status not in ('analyzing', 'completed'):
        flash('No analysis in progress.', 'warning')
        return redirect(url_for('resume_studio_library'))

    return render_template('jobs_waiting.html', active_category='resume_studio', active_page='jd_match')


@app.route('/jobs/results')
def jobs_results():
    """Show JD vs CV analysis results."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    jd_id = session.get('_jd_analysis_id')
    if not jd_id:
        flash('No completed analysis found. Please try again.', 'warning')
        return redirect(url_for('resume_studio_library'))

    row = JDAnalysis.query.get(jd_id)
    if not row or row.status != 'completed' or not row.results_json:
        flash('No completed analysis found. Please try again.', 'warning')
        return redirect(url_for('resume_studio_library'))

    results = json.loads(row.results_json)

    # Set up session data so "Rewrite Resume for This Role" works
    primary = UserResume.query.filter_by(user_id=session['user_id'], is_primary=True).first()
    cv_text = primary.extracted_text if primary else ''
    token = session.get('_data_token', '')
    session['_data_token'] = _update_session_data(token, {
        'cv_text': cv_text,
        'jd_text': row.jd_text or '',
        'analysis_results': {
            'ats_score': results.get('ats_score', 0),
            'matched': results.get('skill_match', {}).get('matched', [])[:20],
            'missing': results.get('skill_match', {}).get('missing', [])[:20],
            'missing_verbs': results.get('experience_analysis', {}).get('missing_action_verbs', [])[:10],
            'skill_score': results.get('skill_match', {}).get('skill_score', 0),
        },
        'tier': 2,
    })

    return render_template('results.html', results=results, active_category='resume_studio', active_page='jd_match')


@app.route('/jobs/<int:jd_id>/results')
def jd_analysis_results(jd_id):
    """View a specific past JD analysis by ID."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    row = JDAnalysis.query.filter_by(id=jd_id, user_id=session['user_id']).first()
    if not row:
        flash('Analysis not found.', 'error')
        return redirect(url_for('resume_studio_library'))

    if row.status == 'analyzing':
        session['_jd_analysis_id'] = row.id
        return redirect(url_for('jobs_waiting'))

    if row.status != 'completed' or not row.results_json:
        flash('No completed analysis results available.', 'warning')
        return redirect(url_for('resume_studio_library'))

    results = json.loads(row.results_json)

    # Set up session data so "Rewrite Resume for This Role" works
    primary = UserResume.query.filter_by(user_id=session['user_id'], is_primary=True).first()
    cv_text = primary.extracted_text if primary else ''
    token = session.get('_data_token', '')
    session['_data_token'] = _update_session_data(token, {
        'cv_text': cv_text,
        'jd_text': row.jd_text or '',
        'analysis_results': {
            'ats_score': results.get('ats_score', 0),
            'matched': results.get('skill_match', {}).get('matched', [])[:20],
            'missing': results.get('skill_match', {}).get('missing', [])[:20],
            'missing_verbs': results.get('experience_analysis', {}).get('missing_action_verbs', [])[:10],
            'skill_score': results.get('skill_match', {}).get('skill_score', 0),
        },
        'tier': 2,
    })

    return render_template('results.html', results=results, active_category='resume_studio', active_page='jd_match')


@app.route('/jobs/<int:jd_id>/delete', methods=['POST'])
def jd_analysis_delete(jd_id):
    """Delete a specific JD analysis."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    row = JDAnalysis.query.filter_by(id=jd_id, user_id=session['user_id']).first()
    if row:
        db.session.delete(row)
        db.session.commit()
        flash('Analysis deleted.', 'success')
    else:
        flash('Analysis not found.', 'error')

    return redirect(url_for('resume_studio_library'))


# ---------------------------------------------------------------------------
# CV download
# ---------------------------------------------------------------------------

@app.route('/download-cv')
def download_cv_text():
    """Download the most recently analysed CV as a PDF."""
    data = _load_session_data(session.get('_data_token', ''))
    cv_text = data.get('cv_text', '')
    if not cv_text:
        flash('No CV available to download. Please run an analysis first.', 'warning')
        return redirect(url_for('resume_studio_library'))

    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cv_download.pdf')
    _text_to_pdf(cv_text, pdf_path)
    return send_file(pdf_path, as_attachment=True, download_name='my_cv.pdf',
                     mimetype='application/pdf')


# ---------------------------------------------------------------------------
# CV Rewrite (paid feature)
# ---------------------------------------------------------------------------

@app.route('/rewrite-cv')
def rewrite_cv_page():
    """Confirmation page before performing rewrite."""
    # Check if we have analysis data (stored server-side)
    data = _load_session_data(session.get('_data_token', ''))
    if not data.get('cv_text') or not data.get('jd_text'):
        flash('Please run a CV analysis first before requesting a rewrite.', 'warning')
        return redirect(url_for('resume_studio_library'))

    # Must be logged in
    if not session.get('user_id'):
        session['_login_next'] = url_for('rewrite_cv_page')
        flash('Please sign in to rewrite your CV.', 'warning')
        return redirect(url_for('login_page'))

    from payments import CREDITS_PER_REWRITE
    user = User.query.get(session['user_id'])
    if not user:
        flash('User not found. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    # Check credits
    if user.credits < CREDITS_PER_REWRITE:
        flash(f'You need {CREDITS_PER_REWRITE} credits to rewrite your CV. You have {user.credits}.', 'warning')
        return redirect(url_for('buy_credits'))

    analysis = data.get('analysis_results', {})
    return render_template('rewrite_confirm.html',
                           user=user,
                           credits_needed=CREDITS_PER_REWRITE,
                           ats_score=analysis.get('ats_score', 0),
                           matched_count=len(analysis.get('matched', [])),
                           missing_count=len(analysis.get('missing', [])),
                           active_category='resume_studio', active_page='rewrite')


@app.route('/rewrite-cv', methods=['POST'])
def rewrite_cv_action():
    """Perform the rewrite — deduct credits, call LLM, show results."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    data = _load_session_data(session.get('_data_token', ''))
    if not data.get('cv_text') or not data.get('jd_text'):
        flash('No analysis data found. Please run analysis first.', 'warning')
        return redirect(url_for('resume_studio_library'))

    from payments import deduct_credits, CREDITS_PER_REWRITE

    # Deduct credits atomically
    if not deduct_credits(session['user_id'], CREDITS_PER_REWRITE):
        flash(f'Insufficient credits. You need {CREDITS_PER_REWRITE} credits.', 'warning')
        return redirect(url_for('buy_credits'))

    # Refresh session credits
    user = User.query.get(session['user_id'])
    if user:
        session['user_credits'] = user.credits

    # Call LLM for rewrite
    analysis = data.get('analysis_results', {})
    try:
        from llm_service import rewrite_cv
        rewrite_result = rewrite_cv(
            cv_text=data['cv_text'],
            jd_text=data['jd_text'],
            matched=analysis.get('matched', []),
            missing=analysis.get('missing', []),
            missing_verbs=analysis.get('missing_verbs', []),
            ats_score=analysis.get('ats_score', 0),
        )
        _log_llm_usage(session['user_id'], 'cv_rewrite')
    except Exception as e:
        # Refund credits on LLM failure
        logger.error('CV rewrite LLM error: %s', e, exc_info=True)
        try:
            if user:
                user.credits += CREDITS_PER_REWRITE
                db.session.commit()
                session['user_credits'] = user.credits
        except Exception:
            pass
        flash(f'Rewrite failed: {e}. Your credits have been refunded.', 'error')
        return redirect(url_for('resume_studio_library'))

    # Compute side-by-side diff
    cv_diff = _compute_cv_diff(data['cv_text'], rewrite_result['rewritten_cv'])

    # Store rewritten CV server-side for download
    token = session.get('_data_token', '')
    session['_data_token'] = _update_session_data(token, {
        'rewritten_cv': rewrite_result['rewritten_cv'],
    })

    return render_template('rewrite_results.html',
                           rewrite=rewrite_result,
                           original_ats=analysis.get('ats_score', 0),
                           credits_remaining=user.credits if user else 0,
                           cv_diff=cv_diff,
                           original_cv=data['cv_text'],
                           active_category='resume_studio', active_page='rewrite')


@app.route('/download-rewritten-cv')
def download_rewritten_cv():
    """Download the rewritten CV as a PDF."""
    data = _load_session_data(session.get('_data_token', ''))
    rewritten_text = data.get('rewritten_cv', '')
    if not rewritten_text:
        flash('No rewritten CV available. Please perform a rewrite first.', 'warning')
        return redirect(url_for('resume_studio_library'))

    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'rewritten_cv.pdf')
    _rewritten_cv_to_pdf(rewritten_text, pdf_path)
    return send_file(pdf_path, as_attachment=True, download_name='rewritten_cv.pdf',
                     mimetype='application/pdf')


# ---------------------------------------------------------------------------
# Inline CV editing routes (P14)
# ---------------------------------------------------------------------------

@app.route('/refine-section', methods=['POST'])
def refine_section():
    """Refine a selected CV section using AI (1 credit per call)."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.json or {}
    selected_text = data.get('selected_text', '').strip()
    instruction = data.get('instruction', '').strip()
    full_cv = data.get('full_cv', '').strip()

    if not selected_text or not instruction:
        return jsonify({'error': 'Please provide selected text and an instruction'}), 400

    # Deduct 1 credit
    from payments import deduct_credits
    if not deduct_credits(session['user_id'], credits_needed=1, action='cv_refine'):
        return jsonify({'error': 'Insufficient credits. You need 1 credit per refinement.'}), 402

    try:
        from llm_service import refine_cv_section
        refined_text = refine_cv_section(selected_text, instruction, full_cv)
        _log_llm_usage(session['user_id'], 'cv_refine')

        user = User.query.get(session['user_id'])
        session['user_credits'] = user.credits if user else 0

        return jsonify({
            'success': True,
            'refined_text': refined_text,
            'credits_remaining': user.credits if user else 0,
        })
    except Exception as e:
        # Refund the credit on failure
        user = User.query.get(session['user_id'])
        if user:
            user.credits += 1
            usage = CreditUsage(user_id=user.id, credits_used=-1, action='cv_refine_refund')
            db.session.add(usage)
            db.session.commit()
            session['user_credits'] = user.credits
        logger.error('Refine section failed: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/update-rewritten-cv', methods=['POST'])
def update_rewritten_cv():
    """Update the session-stored rewritten CV with user's edits."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.json or {}
    rewritten_cv = data.get('rewritten_cv', '').strip()
    if not rewritten_cv:
        return jsonify({'error': 'No CV text provided'}), 400

    # Accept token from request body (inline panel) or fall back to session
    token = data.get('token') or session.get('_data_token', '')
    session_data = _load_session_data(token)
    session_data['rewritten_cv'] = rewritten_cv
    # Save back and update session so download route picks it up
    new_token = _save_session_data(session_data)
    session['_data_token'] = new_token

    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Credit purchase & payment routes
# ---------------------------------------------------------------------------

@app.route('/buy-credits')
def buy_credits():
    from payments import TIERS, PAYMENTS_ENABLED, RAZORPAY_KEY_ID
    user = None
    if session.get('user_id'):
        user = User.query.get(session['user_id'])
    return render_template('buy_credits.html',
                           tiers=TIERS,
                           payments_enabled=PAYMENTS_ENABLED,
                           razorpay_key=RAZORPAY_KEY_ID,
                           user=user)


@app.route('/grant-free-credits', methods=['POST'])
def grant_free_credits():
    """Temporary: grant credits without payment. Replace with Razorpay later."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.json or {}
    tier = data.get('tier', '')
    from payments import TIERS
    tier_info = TIERS.get(tier)
    if not tier_info:
        return jsonify({'error': f'Invalid tier: {tier}'}), 400

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404

    credits_to_add = tier_info['credits']
    user.credits += credits_to_add
    usage = CreditUsage(user_id=user.id, credits_used=-credits_to_add, action=f'free_grant_{tier}')
    db.session.add(usage)
    db.session.commit()
    session['user_credits'] = user.credits
    logger.info('Granted %d free credits to user %d (tier=%s)', credits_to_add, user.id, tier)

    return jsonify({'success': True, 'credits_added': credits_to_add, 'new_balance': user.credits})


@app.route('/payment/create', methods=['POST'])
def payment_create():
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    tier = request.json.get('tier', '')
    try:
        from payments import create_order
        result = create_order(session['user_id'], tier)
        return jsonify(result)
    except Exception as e:
        logger.error('Payment create error: %s', e)
        return jsonify({'error': str(e)}), 400


@app.route('/payment/verify', methods=['POST'])
def payment_verify():
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.json or {}
    try:
        from payments import verify_payment
        result = verify_payment(
            data.get('order_id', ''),
            data.get('payment_id', ''),
            data.get('signature', ''),
        )
        # Update session credits
        session['user_credits'] = result.get('new_balance', 0)
        return jsonify(result)
    except Exception as e:
        logger.error('Payment verify error: %s', e)
        return jsonify({'error': str(e)}), 400


@app.route('/payment/webhook', methods=['POST'])
def payment_webhook():
    try:
        from payments import handle_webhook
        sig = request.headers.get('X-Razorpay-Signature', '')
        handled = handle_webhook(request.json or {}, sig)
        return jsonify({'status': 'ok', 'handled': handled})
    except Exception as e:
        logger.error('Webhook error: %s', e)
        return jsonify({'status': 'error'}), 400


# ---------------------------------------------------------------------------
# Experts landing page (Change 7)
# ---------------------------------------------------------------------------

@app.route('/experts')
def experts():
    """Legacy redirect — /experts now lives at /career-services/experts."""
    return redirect(url_for('career_services_experts'), code=301)


@app.route('/mentors')
def mentors():
    """Legacy redirect — /mentors now lives at /career-services/mentors."""
    return redirect(url_for('career_services_mentors'), code=301)


@app.route('/resume-tips')
def resume_tips():
    return render_template('resume_tips.html')


@app.route('/blog')
def blog():
    return render_template('blog.html')


# ---------------------------------------------------------------------------
# Resume Studio — restructured navigation (CV Library, JD Match, Analysis, Rewrite)
# ---------------------------------------------------------------------------


# ── Resume Editor helper ──
def _json_resume_to_text(data):
    """Convert JSON Resume data to plain text for analysis compatibility."""
    parts = []
    b = data.get('basics', {})
    if b.get('name'): parts.append(b['name'])
    if b.get('label'): parts.append(b['label'])
    if b.get('summary'): parts.append(b['summary'])
    for w in data.get('work', []):
        parts.append(f"{w.get('position', '')} at {w.get('name', '')}")
        if w.get('summary'): parts.append(w['summary'])
        for h in w.get('highlights', []):
            parts.append(h)
    for e in data.get('education', []):
        parts.append(f"{e.get('studyType', '')} in {e.get('area', '')} from {e.get('institution', '')}")
    for s in data.get('skills', []):
        kw = ', '.join(s.get('keywords', []))
        if s.get('name') or kw:
            parts.append(f"{s.get('name', '')}: {kw}")
    for p in data.get('projects', []):
        if p.get('name'): parts.append(p['name'])
        if p.get('description'): parts.append(p['description'])
        for h in p.get('highlights', []):
            parts.append(h)
    for a in data.get('awards', []):
        if a.get('title'): parts.append(a['title'])
    for c in data.get('certificates', []):
        if c.get('name'): parts.append(c['name'])
    return '\n'.join(filter(None, parts))


@app.route('/resume-studio/editor')
@app.route('/resume-studio/editor/<int:resume_id>')
def resume_editor(resume_id=None):
    """Resume Editor — create or edit a resume with live preview."""
    if not session.get('user_id'):
        session['_login_next'] = url_for('resume_editor')
        flash('Please sign in to use the resume editor.', 'warning')
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    editor_data = {
        'resume_id': None,
        'resume_json': None,
        'template_id': 'classic',
        'label': 'My Resume',
        'is_primary': False,
    }

    if resume_id:
        resume = UserResume.query.filter_by(id=resume_id, user_id=user.id).first()
        if not resume:
            flash('Resume not found.', 'error')
            return redirect(url_for('resume_studio_library'))
        if not resume.resume_json:
            flash('This resume was uploaded and cannot be edited in the editor.', 'warning')
            return redirect(url_for('resume_studio_library'))
        editor_data = {
            'resume_id': resume.id,
            'resume_json': resume.resume_json,
            'template_id': resume.template_id or 'classic',
            'label': resume.label,
            'is_primary': resume.is_primary,
        }

    return render_template('resume_studio/editor.html',
                           _cat='resume_studio', _pg='editor',
                           editor_data=editor_data)


@app.route('/resume-studio/editor/save', methods=['POST'])
def resume_editor_save():
    """Save resume JSON data — create new or update existing."""
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    data = request.get_json()
    if not data or 'resume_json' not in data:
        return jsonify({'success': False, 'error': 'Missing resume data'}), 400

    resume_json = data['resume_json']
    label = data.get('label', 'My Resume')[:100]
    template_id = data.get('template_id', 'classic')[:30]
    is_primary = bool(data.get('is_primary', False))
    resume_id = data.get('resume_id')

    # Convert JSON to text for analysis compatibility
    extracted_text = _json_resume_to_text(resume_json)
    json_str = json.dumps(resume_json)
    file_bytes = json_str.encode('utf-8')

    try:
        if resume_id:
            # Update existing
            resume = UserResume.query.filter_by(id=resume_id, user_id=user.id).first()
            if not resume:
                return jsonify({'success': False, 'error': 'Resume not found'}), 404
            resume.resume_json = json_str
            resume.template_id = template_id
            resume.label = label
            resume.extracted_text = extracted_text[:50000]
            resume.file_data = file_bytes
            resume.filename = f'{label}.json'
            resume.file_size = len(file_bytes)
            resume.updated_at = datetime.utcnow()
        else:
            # Check 5-resume limit
            count = UserResume.query.filter_by(user_id=user.id).count()
            if count >= 5:
                return jsonify({'success': False, 'error': 'You have reached the 5-resume storage limit. Delete a resume first.'}), 400

            resume = UserResume(
                user_id=user.id,
                label=label,
                filename=f'{label}.json',
                file_data=file_bytes,
                file_size=len(file_bytes),
                extracted_text=extracted_text[:50000],
                resume_json=json_str,
                template_id=template_id,
                resume_source='editor',
                is_primary=(count == 0),  # First resume is auto-primary
            )
            db.session.add(resume)

        # Handle primary
        if is_primary:
            UserResume.query.filter_by(user_id=user.id, is_primary=True).update({'is_primary': False})
            resume.is_primary = True

        db.session.commit()
        return jsonify({'success': True, 'resume_id': resume.id})

    except Exception as e:
        db.session.rollback()
        logger.error('Resume editor save error: %s', e)
        return jsonify({'success': False, 'error': 'Failed to save resume'}), 500


@app.route('/resume-studio/editor/print/<int:resume_id>')
def resume_editor_print(resume_id):
    """Print-friendly resume page for browser PDF export."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    resume = UserResume.query.filter_by(id=resume_id, user_id=session['user_id']).first()
    if not resume or not resume.resume_json:
        flash('Resume not found.', 'error')
        return redirect(url_for('resume_studio_library'))

    return render_template('resume_studio/print_resume.html',
                           resume_id=resume.id,
                           resume_json=resume.resume_json,
                           template_id=resume.template_id or 'classic',
                           label=resume.label)


@app.route('/resume-studio/editor/ai-rewrite', methods=['POST'])
def resume_editor_ai_rewrite():
    """AI-rewrite a single resume field (summary, highlights, etc.). Costs 1 credit."""
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    if user.credits < 1:
        return jsonify({'success': False, 'error': 'Not enough credits. You need 1 credit per AI rewrite.'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Missing request data'}), 400

    field_type = data.get('field_type', 'summary')
    current_text = data.get('current_text', '').strip()
    job_title = data.get('job_title', '')

    if not current_text:
        return jsonify({'success': False, 'error': 'Please enter some text first, then click Write with AI.'}), 400

    try:
        from llm_service import rewrite_resume_field
        rewritten = rewrite_resume_field(field_type, current_text, job_title)

        # Deduct 1 credit
        from payments import deduct_credits
        deduct_credits(user.id, 1)
        # Update session credits
        user = User.query.get(session['user_id'])
        session['user_credits'] = user.credits

        return jsonify({'success': True, 'rewritten_text': rewritten, 'credits_remaining': user.credits})

    except Exception as e:
        logger.error('AI field rewrite error: %s', e)
        return jsonify({'success': False, 'error': 'AI rewrite failed. Please try again.'}), 500


@app.route('/resume-studio/library')
def resume_studio_library():
    """CV Library — upload, manage, and analyze resumes."""
    if not session.get('user_id'):
        session['_login_next'] = url_for('resume_studio_library')
        flash('Please sign in to manage your resumes.', 'warning')
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    from payments import FREE_CV_ANALYSIS_LIMIT, CREDITS_PER_CV_ANALYSIS
    user_data = {
        'analysis_count': user.analysis_count,
        'credits': user.credits,
        'first_free': user.analysis_count < FREE_CV_ANALYSIS_LIMIT,
        'credits_per_cv': CREDITS_PER_CV_ANALYSIS,
    }
    resumes = UserResume.query.filter_by(user_id=user.id)\
        .options(defer(UserResume.file_data), defer(UserResume.extracted_text), defer(UserResume.analysis_results_json))\
        .order_by(UserResume.created_at.desc()).all()

    return render_template('resume_studio/library.html',
                           resumes=resumes,
                           user_data=user_data,
                           active_category='resume_studio', active_page='library')


@app.route('/resume-studio/jd-match')
def resume_studio_jd_match():
    """JD Match — upload a JD to compare against a resume."""
    if not session.get('user_id'):
        session['_login_next'] = url_for('resume_studio_jd_match')
        flash('Please sign in to analyze job descriptions.', 'warning')
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    from payments import CREDITS_PER_JD_ANALYSIS
    resumes = UserResume.query.filter_by(user_id=user.id)\
        .options(defer(UserResume.file_data), defer(UserResume.extracted_text), defer(UserResume.analysis_results_json))\
        .order_by(UserResume.created_at.desc()).all()
    primary = UserResume.query.filter_by(user_id=user.id, is_primary=True)\
        .options(defer(UserResume.file_data), defer(UserResume.extracted_text), defer(UserResume.analysis_results_json))\
        .first()

    jd_histories = JDAnalysis.query.filter_by(user_id=user.id)\
        .order_by(JDAnalysis.created_at.desc()).all()
    jd_scores = {}
    jd_names = {}
    for jd in jd_histories:
        if jd.status == 'completed' and jd.results_json:
            try:
                parsed = json.loads(jd.results_json)
                jd_scores[jd.id] = parsed.get('ats_score', 0)
            except (json.JSONDecodeError, AttributeError):
                jd_scores[jd.id] = 0
        jd_name = ''
        if jd.jd_text:
            for line in jd.jd_text.strip().split('\n'):
                line = line.strip()
                if line and len(line) > 3:
                    jd_name = line[:80]
                    break
        jd_names[jd.id] = jd_name or 'Job Description'

    return render_template('resume_studio/jd_match.html',
                           resumes=resumes,
                           primary_resume=primary,
                           jd_histories=jd_histories,
                           jd_scores=jd_scores,
                           jd_names=jd_names,
                           credits_per_jd=CREDITS_PER_JD_ANALYSIS,
                           credits_remaining=user.credits,
                           active_category='resume_studio', active_page='jd_match')


@app.route('/resume-studio/analysis')
def resume_studio_analysis():
    """Analysis Report — unified list of all CV and JD analyses."""
    if not session.get('user_id'):
        session['_login_next'] = url_for('resume_studio_analysis')
        flash('Please sign in to view your analyses.', 'warning')
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    cv_analyses = []
    jd_analyses_list = []

    # CV analyses
    cv_resumes = UserResume.query.filter_by(user_id=user.id, analysis_status='completed')\
        .options(defer(UserResume.file_data), defer(UserResume.extracted_text), defer(UserResume.analysis_results_json))\
        .all()
    for r in cv_resumes:
        cv_analyses.append({
            'name': r.label or r.filename or 'Resume',
            'score': r.ats_score,
            'date': r.last_analyzed_at or r.created_at,
            'url': url_for('resume_results', resume_id=r.id),
        })

    # JD analyses
    jd_rows = JDAnalysis.query.filter_by(user_id=user.id, status='completed').all()
    for jd in jd_rows:
        score = None
        if jd.results_json:
            try:
                parsed = json.loads(jd.results_json)
                score = parsed.get('ats_score')
            except (json.JSONDecodeError, AttributeError):
                pass
        jd_name = ''
        if jd.jd_text:
            for line in jd.jd_text.strip().split('\n'):
                line = line.strip()
                if line and len(line) > 3:
                    jd_name = line[:80]
                    break
        jd_analyses_list.append({
            'name': jd_name or 'Job Description',
            'score': score,
            'date': jd.created_at,
            'url': url_for('jd_analysis_results', jd_id=jd.id),
        })

    # Sort each list by date descending
    cv_analyses.sort(key=lambda a: a['date'] or datetime.min, reverse=True)
    jd_analyses_list.sort(key=lambda a: a['date'] or datetime.min, reverse=True)

    return render_template('resume_studio/analysis.html',
                           cv_analyses=cv_analyses,
                           jd_analyses=jd_analyses_list,
                           active_category='resume_studio', active_page='analysis')


@app.route('/resume-studio/rewrite')
def resume_studio_rewrite():
    """Standalone Rewrite CV — select resume + provide JD."""
    if not session.get('user_id'):
        session['_login_next'] = url_for('resume_studio_rewrite')
        flash('Please sign in to rewrite your resume.', 'warning')
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    from payments import CREDITS_PER_JD_ANALYSIS, CREDITS_PER_REWRITE
    resumes = UserResume.query.filter_by(user_id=user.id)\
        .options(defer(UserResume.file_data), defer(UserResume.extracted_text), defer(UserResume.analysis_results_json))\
        .order_by(UserResume.created_at.desc()).all()

    return render_template('resume_studio/rewrite.html',
                           resumes=resumes,
                           credits_per_rewrite=CREDITS_PER_JD_ANALYSIS + CREDITS_PER_REWRITE,
                           credits_remaining=user.credits,
                           active_category='resume_studio', active_page='rewrite')


@app.route('/resume-studio/rewrite', methods=['POST'])
def resume_studio_rewrite_action():
    """Process standalone rewrite — analyze JD, then redirect to rewrite confirm."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        return redirect(url_for('login_page'))

    resume_id = request.form.get('resume_id', type=int)
    resume = UserResume.query.filter_by(id=resume_id, user_id=user.id).first()
    if not resume or not resume.extracted_text:
        flash('Please select a valid resume with extracted text.', 'error')
        return redirect(url_for('resume_studio_rewrite'))

    # Extract JD text
    jd_text = None
    try:
        jd_text = _process_input('jd_file', 'jd_text', 'jd_url',
                                 url_extractor=_extract_from_jd_url)
    except Exception as e:
        logger.warning('JD extraction failed: %s', e)

    if not jd_text or len(jd_text.strip()) < 50:
        flash('Please provide a valid job description (at least 50 characters).', 'error')
        return redirect(url_for('resume_studio_rewrite'))

    # Store in session for the existing rewrite flow
    cv_text = resume.extracted_text
    token = _save_session_data({
        'cv_text': cv_text,
        'jd_text': jd_text,
        'resume_id': resume_id,
    })
    session['_data_token'] = token

    # Run JD analysis to get skill match data
    try:
        from llm_service import analyze_cv_against_jd
        results = analyze_cv_against_jd(cv_text, jd_text)
        if results:
            _update_session_data(token, {'results': results})
    except Exception as e:
        logger.warning('Quick JD analysis for rewrite failed: %s', e)

    return redirect(url_for('rewrite_cv_page'))


# ---------------------------------------------------------------------------
# Job Copilot — restructured navigation
# ---------------------------------------------------------------------------

@app.route('/job-copilot/search')
def job_copilot_search():
    """AI Job Search — search public job listings with saved filter preferences."""
    if not session.get('user_id'):
        session['_login_next'] = url_for('job_copilot_search')
        flash('Please sign in to search jobs.', 'warning')
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    primary = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()
    prefs = JobPreferences.query.filter_by(user_id=user.id).first()
    show_wizard = not prefs or not prefs.setup_completed
    preferences_json = json.dumps(prefs.to_dict()) if prefs and prefs.setup_completed else 'null'

    # Check if user has completed their profile (for nudge banner)
    up = UserProfile.query.filter_by(user_id=user.id).first()
    profile_complete = bool(up and up.setup_completed)

    return render_template('jobs.html',
                           primary_resume=primary,
                           credits_remaining=user.credits,
                           show_wizard=show_wizard,
                           preferences_json=preferences_json,
                           profile_complete=profile_complete,
                           active_category='job_copilot', active_page='search')


@app.route('/job-copilot/auto-apply')
def job_copilot_auto_apply():
    """Auto Apply — coming soon."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    return render_template('_coming_soon.html',
                           coming_soon_title='Auto Apply',
                           coming_soon_desc='Let our AI automatically apply to jobs that match your profile. Set your preferences and let us handle the rest.',
                           coming_soon_icon='M13 10V3L4 14h7v7l9-11h-7z',
                           active_category='job_copilot', active_page='auto_apply')


@app.route('/job-copilot/tracker')
def job_copilot_tracker():
    """Application Tracker — coming soon."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    return render_template('_coming_soon.html',
                           coming_soon_title='Application Tracker',
                           coming_soon_desc='Track all your job applications in one place. Monitor status, follow-ups, and interview schedules.',
                           coming_soon_icon='M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01',
                           active_category='job_copilot', active_page='tracker')


# ---------------------------------------------------------------------------
# Career Services — restructured navigation
# ---------------------------------------------------------------------------

@app.route('/career-services/experts')
def career_services_experts():
    """Resume Experts — moved from /experts."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    return render_template('experts.html',
                           active_category='career_services', active_page='experts')


@app.route('/career-services/mentors')
def career_services_mentors():
    """Get Mentor Help — moved from /mentors."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    return render_template('mentors.html',
                           active_category='career_services', active_page='mentors')


@app.route('/career-services/interview-prep')
def career_services_interview_prep():
    """Interview Prep — redirect to mock interviews."""
    return redirect(url_for('career_services_mock_interviews'))


# ---------------------------------------------------------------------------
# Mock AI Interviews — pages & API
# ---------------------------------------------------------------------------

@app.route('/career-services/mock-interviews')
def career_services_mock_interviews():
    """Mock Interview setup page."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    user = User.query.get(session['user_id'])
    from models import InterviewSession
    past_sessions = InterviewSession.query.filter_by(
        user_id=user.id
    ).order_by(InterviewSession.started_at.desc()).limit(10).all()
    completed_count = InterviewSession.query.filter_by(
        user_id=user.id, status='completed').count()
    return render_template('interview/setup.html',
                           user=user,
                           past_sessions=past_sessions,
                           completed_count=completed_count,
                           active_category='career_services',
                           active_page='mock_interviews')


@app.route('/career-services/mock-interviews/session/<int:session_id>')
def career_services_interview_session(session_id):
    """Live interview session page."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    from models import InterviewSession
    iv_session = InterviewSession.query.get_or_404(session_id)
    if iv_session.user_id != session['user_id']:
        return redirect(url_for('career_services_mock_interviews'))
    if iv_session.status == 'completed':
        return redirect(url_for('career_services_interview_feedback', session_id=session_id))
    user = User.query.get(session['user_id'])
    return render_template('interview/session_room.html',
                           user=user,
                           iv_session=iv_session)


@app.route('/career-services/mock-interviews/feedback/<int:session_id>')
def career_services_interview_feedback(session_id):
    """Post-interview feedback report."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    from models import InterviewSession, InterviewExchange
    iv_session = InterviewSession.query.get_or_404(session_id)
    if iv_session.user_id != session['user_id']:
        return redirect(url_for('career_services_mock_interviews'))
    if iv_session.status != 'completed':
        return redirect(url_for('career_services_interview_session', session_id=session_id))
    user = User.query.get(session['user_id'])
    exchanges = iv_session.exchanges.order_by(InterviewExchange.sequence).all()
    feedback = json.loads(iv_session.feedback_json) if iv_session.feedback_json else {}
    return render_template('interview/feedback.html',
                           user=user,
                           iv_session=iv_session,
                           exchanges=exchanges,
                           feedback=feedback,
                           active_category='career_services',
                           active_page='mock_interviews')


# --- Interview API Endpoints ---

@app.route('/api/interview/start', methods=['POST'])
def api_interview_start():
    """Create a new interview session and return the first question."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    user = User.query.get(session['user_id'])
    data = request.get_json(silent=True) or {}

    # Validate required fields
    target_role = (data.get('target_role') or '').strip()
    interview_type = data.get('interview_type', 'behavioral')
    difficulty = data.get('difficulty', 'medium')
    duration_minutes = data.get('duration_minutes', 30)
    persona = data.get('persona', 'neutral')

    if not target_role:
        return jsonify({'error': 'Target role is required'}), 400
    if interview_type not in ('behavioral', 'technical', 'hr', 'case', 'mixed'):
        return jsonify({'error': 'Invalid interview type'}), 400
    if difficulty not in ('easy', 'medium', 'hard'):
        return jsonify({'error': 'Invalid difficulty'}), 400
    if duration_minutes not in (15, 30, 45):
        return jsonify({'error': 'Duration must be 15, 30, or 45'}), 400
    if persona not in ('friendly', 'neutral', 'tough'):
        return jsonify({'error': 'Invalid persona'}), 400

    # Credit check: first interview free, then 3 credits
    from models import InterviewSession, InterviewExchange
    from payments import deduct_credits, CREDITS_PER_MOCK_INTERVIEW, FREE_INTERVIEW_LIMIT

    completed_count = InterviewSession.query.filter_by(
        user_id=user.id, status='completed').count()
    is_free = completed_count < FREE_INTERVIEW_LIMIT
    credits_charged = 0

    if not is_free:
        if not deduct_credits(user.id, CREDITS_PER_MOCK_INTERVIEW, 'mock_interview'):
            user = User.query.get(user.id)  # refresh
            return jsonify({
                'error': 'Insufficient credits',
                'credits_needed': CREDITS_PER_MOCK_INTERVIEW,
                'credits_available': user.credits,
            }), 402
        credits_charged = CREDITS_PER_MOCK_INTERVIEW

    # Create session
    iv_session = InterviewSession(
        user_id=user.id,
        target_role=target_role,
        interview_type=interview_type,
        difficulty=difficulty,
        duration_minutes=duration_minutes,
        persona=persona,
        status='active',
        credits_charged=credits_charged,
    )
    db.session.add(iv_session)
    db.session.flush()  # get id

    # Generate first question
    try:
        from interview_service import start_interview, get_expected_question_count
        result = start_interview(iv_session)
    except Exception as e:
        logger.error('Interview start LLM error: %s', e)
        db.session.rollback()
        return jsonify({'error': 'Failed to start interview. Please try again.'}), 500

    # Save first exchange
    exchange = InterviewExchange(
        session_id=iv_session.id,
        sequence=1,
        question_text=result['interviewer_message'],
        question_type=result.get('question_type', 'warmup'),
        requires_code=result.get('requires_code', False),
        code_language=result.get('code_language'),
    )
    db.session.add(exchange)
    iv_session.question_count = 1
    db.session.commit()

    user = User.query.get(user.id)  # refresh credits
    return jsonify({
        'session_id': iv_session.id,
        'interviewer_message': result['interviewer_message'],
        'question_type': result.get('question_type', 'warmup'),
        'requires_code': result.get('requires_code', False),
        'code_language': result.get('code_language'),
        'is_final_question': result.get('is_final_question', False),
        'question_number': 1,
        'total_expected': get_expected_question_count(duration_minutes),
        'credits_remaining': user.credits,
        'is_free': is_free,
    })


@app.route('/api/interview/answer', methods=['POST'])
def api_interview_answer():
    """Submit candidate answer and get next question."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    answer_text = (data.get('answer_text') or '').strip()
    code_text = (data.get('code_text') or '').strip() or None
    answer_duration = data.get('answer_duration_seconds', 0)

    if not session_id or not answer_text:
        return jsonify({'error': 'session_id and answer_text are required'}), 400

    from models import InterviewSession, InterviewExchange
    iv_session = InterviewSession.query.get(session_id)
    if not iv_session or iv_session.user_id != session['user_id']:
        return jsonify({'error': 'Session not found'}), 404
    if iv_session.status != 'active':
        return jsonify({'error': 'Interview is not active'}), 400

    # Find the latest unanswered exchange and save the answer
    current_exchange = InterviewExchange.query.filter_by(
        session_id=iv_session.id, answer_text=None
    ).order_by(InterviewExchange.sequence.desc()).first()

    if not current_exchange:
        return jsonify({'error': 'No pending question to answer'}), 400

    # Get all exchanges for context
    all_exchanges = iv_session.exchanges.order_by(InterviewExchange.sequence).all()

    # Generate next question
    try:
        from interview_service import process_answer, get_expected_question_count
        result = process_answer(iv_session, all_exchanges, answer_text, code_text)
    except Exception as e:
        logger.error('Interview answer LLM error: %s', e)
        return jsonify({'error': 'Failed to process answer. Please try again.'}), 500

    # Save the answer on current exchange
    current_exchange.answer_text = answer_text
    current_exchange.code_text = code_text
    current_exchange.answer_duration_seconds = answer_duration
    current_exchange.feedback_json = json.dumps(result.get('brief_feedback', {}))

    # Create new exchange for the next question
    next_seq = current_exchange.sequence + 1
    next_exchange = InterviewExchange(
        session_id=iv_session.id,
        sequence=next_seq,
        question_text=result['interviewer_message'],
        question_type=result.get('question_type', 'behavioral'),
        requires_code=result.get('requires_code', False),
        code_language=result.get('code_language'),
    )
    db.session.add(next_exchange)
    iv_session.question_count = next_seq
    db.session.commit()

    total_expected = get_expected_question_count(iv_session.duration_minutes)

    return jsonify({
        'interviewer_message': result['interviewer_message'],
        'question_type': result.get('question_type', 'behavioral'),
        'is_follow_up': result.get('is_follow_up', False),
        'is_final_question': result.get('is_final_question', False),
        'requires_code': result.get('requires_code', False),
        'code_language': result.get('code_language'),
        'brief_feedback': result.get('brief_feedback', {}),
        'question_number': next_seq,
        'total_expected': total_expected,
    })


@app.route('/api/interview/end', methods=['POST'])
def api_interview_end():
    """End interview and generate feedback report."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')

    from models import InterviewSession, InterviewExchange
    iv_session = InterviewSession.query.get(session_id)
    if not iv_session or iv_session.user_id != session['user_id']:
        return jsonify({'error': 'Session not found'}), 404
    if iv_session.status == 'completed':
        return jsonify({'redirect_url': url_for('career_services_interview_feedback',
                                                 session_id=iv_session.id)})

    # Mark as completed
    iv_session.status = 'completed'
    iv_session.ended_at = datetime.utcnow()

    # Generate final feedback
    exchanges = iv_session.exchanges.order_by(InterviewExchange.sequence).all()
    try:
        from interview_service import generate_final_feedback
        feedback = generate_final_feedback(iv_session, exchanges)
        iv_session.overall_score = feedback.get('overall_score', 50)
        iv_session.feedback_json = json.dumps(feedback)
    except Exception as e:
        logger.error('Interview feedback generation error: %s', e)
        iv_session.feedback_json = json.dumps({
            'overall_score': 0,
            'summary': 'Feedback generation failed. Please try again.',
            'dimensions': {},
            'per_question_feedback': [],
        })
        iv_session.overall_score = 0

    db.session.commit()

    return jsonify({
        'redirect_url': url_for('career_services_interview_feedback',
                                 session_id=iv_session.id),
    })


@app.route('/api/interview/session/<int:session_id>')
def api_interview_session_data(session_id):
    """Get session data for resuming or reviewing."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    from models import InterviewSession, InterviewExchange
    iv_session = InterviewSession.query.get(session_id)
    if not iv_session or iv_session.user_id != session['user_id']:
        return jsonify({'error': 'Session not found'}), 404

    from interview_service import get_expected_question_count
    exchanges = iv_session.exchanges.order_by(InterviewExchange.sequence).all()

    return jsonify({
        'session': {
            'id': iv_session.id,
            'target_role': iv_session.target_role,
            'interview_type': iv_session.interview_type,
            'difficulty': iv_session.difficulty,
            'duration_minutes': iv_session.duration_minutes,
            'persona': iv_session.persona,
            'status': iv_session.status,
            'question_count': iv_session.question_count,
            'total_expected': get_expected_question_count(iv_session.duration_minutes),
            'started_at': iv_session.started_at.isoformat() if iv_session.started_at else None,
        },
        'exchanges': [{
            'sequence': ex.sequence,
            'question_text': ex.question_text,
            'answer_text': ex.answer_text,
            'code_text': ex.code_text,
            'question_type': ex.question_type,
            'requires_code': ex.requires_code or False,
            'code_language': ex.code_language,
            'answer_duration_seconds': ex.answer_duration_seconds,
            'feedback_json': json.loads(ex.feedback_json) if ex.feedback_json else None,
        } for ex in exchanges],
    })


@app.route('/api/interview/history')
def api_interview_history():
    """Get user's past interview sessions."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    from models import InterviewSession
    sessions = InterviewSession.query.filter_by(
        user_id=session['user_id']
    ).order_by(InterviewSession.started_at.desc()).limit(20).all()

    return jsonify({
        'sessions': [{
            'id': s.id,
            'target_role': s.target_role,
            'interview_type': s.interview_type,
            'difficulty': s.difficulty,
            'duration_minutes': s.duration_minutes,
            'persona': s.persona,
            'status': s.status,
            'overall_score': s.overall_score,
            'question_count': s.question_count,
            'started_at': s.started_at.isoformat() if s.started_at else None,
        } for s in sessions],
    })


@app.route('/api/interview/run-code', methods=['POST'])
def api_interview_run_code():
    """Execute code in a sandboxed environment."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json(silent=True) or {}
    code = data.get('code', '')
    language = data.get('language', 'python')
    stdin_input = data.get('stdin', '')

    if not code.strip():
        return jsonify({'error': 'No code provided'}), 400

    judge0_key = os.environ.get('JUDGE0_API_KEY')

    if judge0_key:
        import requests as http_requests
        LANG_IDS = {'python': 71, 'javascript': 63, 'java': 62, 'cpp': 54, 'go': 60}
        lang_id = LANG_IDS.get(language, 71)
        try:
            resp = http_requests.post(
                'https://judge0-ce.p.rapidapi.com/submissions',
                headers={
                    'X-RapidAPI-Key': judge0_key,
                    'Content-Type': 'application/json',
                },
                json={
                    'source_code': code,
                    'language_id': lang_id,
                    'stdin': stdin_input,
                },
                params={'wait': 'true'},
                timeout=15,
            )
            result = resp.json()
            return jsonify({
                'stdout': result.get('stdout', '') or '',
                'stderr': result.get('stderr', '') or '',
                'compile_output': result.get('compile_output', '') or '',
                'status': result.get('status', {}).get('description', 'Unknown'),
                'time': result.get('time', '0'),
                'memory': result.get('memory', 0),
            })
        except Exception as e:
            logger.error('Judge0 API error: %s', e)
            return jsonify({'error': 'Code execution service unavailable'}), 503
    else:
        # Fallback: Python-only sandboxed exec
        if language != 'python':
            return jsonify({
                'stdout': '',
                'stderr': f'Code execution for {language} requires Judge0 API. Only Python is available in fallback mode.',
                'status': 'Configuration Error',
            })
        import subprocess
        try:
            proc = subprocess.run(
                ['python3', '-c', code],
                capture_output=True, text=True, timeout=5,
                input=stdin_input,
            )
            return jsonify({
                'stdout': proc.stdout[:5000],
                'stderr': proc.stderr[:2000],
                'status': 'Accepted' if proc.returncode == 0 else 'Runtime Error',
                'time': '< 5s',
                'memory': 0,
            })
        except subprocess.TimeoutExpired:
            return jsonify({
                'stdout': '',
                'stderr': 'Execution timed out (5s limit)',
                'status': 'Time Limit Exceeded',
            })
        except Exception as e:
            return jsonify({
                'stdout': '',
                'stderr': str(e),
                'status': 'Internal Error',
            }), 500


@app.route('/api/interview/tts', methods=['POST'])
def api_interview_tts():
    """ElevenLabs TTS proxy — returns audio stream."""
    elevenlabs_key = os.environ.get('ELEVENLABS_API_KEY')
    if not elevenlabs_key:
        return '', 204  # No content — frontend falls back to Web Speech API

    data = request.get_json(silent=True) or {}
    text = data.get('text', '')
    if not text:
        return jsonify({'error': 'text is required'}), 400

    import requests as http_requests
    voice_id = data.get('voice_id', 'pNInz6obpgDQGcFmaJgB')  # "Adam" default

    try:
        resp = http_requests.post(
            f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}',
            headers={
                'xi-api-key': elevenlabs_key,
                'Content-Type': 'application/json',
            },
            json={
                'text': text,
                'model_id': 'eleven_turbo_v2',
                'voice_settings': {'stability': 0.5, 'similarity_boost': 0.75},
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return '', 204  # Fallback
        return Response(resp.content, mimetype='audio/mpeg')
    except Exception as e:
        logger.error('ElevenLabs TTS error: %s', e)
        return '', 204


@app.route('/career-services/career-plan')
def career_services_career_plan():
    """Plan My Career — coming soon."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    return render_template('_coming_soon.html',
                           coming_soon_title='Plan My Career',
                           coming_soon_desc='Get a personalized career roadmap with skill gap analysis, learning paths, and milestone tracking.',
                           coming_soon_icon='M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l5.447 2.724A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7',
                           active_category='career_services', active_page='career_plan')


# ---------------------------------------------------------------------------
# My Resumes — store up to 5 resumes per user
# ---------------------------------------------------------------------------

@app.route('/my-resumes')
def my_resumes():
    """Legacy redirect — now at /resume-studio/library."""
    return redirect(url_for('resume_studio_library'), code=301)


@app.route('/my-resumes/upload', methods=['POST'])
def upload_resume():
    """Upload a new resume and auto-analyze.

    Storage limit: max 5 resumes stored per user. When at the limit,
    the resume is still analysed (results shown in Analysis Reports)
    but the file is NOT stored — the user must delete one to store more.
    """
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    count = UserResume.query.filter_by(user_id=user_id).count()
    at_storage_limit = count >= 5

    file = request.files.get('resume_file')
    if not file or not file.filename:
        flash('Please select a file to upload.', 'error')
        return redirect(url_for('resume_studio_library'))

    if not allowed_file(file.filename):
        flash('Only PDF, DOCX, and TXT files are supported.', 'error')
        return redirect(url_for('resume_studio_library'))

    filename = secure_filename(file.filename)
    file_data = file.read()

    if len(file_data) > 5 * 1024 * 1024:
        flash('File too large. Maximum size is 5 MB.', 'error')
        return redirect(url_for('resume_studio_library'))

    # Extract text for caching
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        with open(temp_path, 'wb') as f:
            f.write(file_data)
        extracted_text = extract_text_from_file(temp_path)
    except Exception as e:
        logger.warning('Could not extract text from uploaded resume: %s', e)
        extracted_text = ''
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    label = request.form.get('label', '').strip() or 'My Resume'
    target_job = request.form.get('target_job', '').strip() or 'General'
    is_primary = request.form.get('is_primary') == '1'

    if at_storage_limit:
        # ── Analyse-only mode: run analysis without storing the resume ──
        if not extracted_text:
            flash('Could not extract text from this file. Please try another format.', 'error')
            return redirect(url_for('resume_studio_library'))

        user = User.query.get(user_id)
        from payments import CREDITS_PER_CV_ANALYSIS, FREE_CV_ANALYSIS_LIMIT, deduct_credits
        credits_charged = False

        if user.analysis_count >= FREE_CV_ANALYSIS_LIMIT:
            if user.credits < CREDITS_PER_CV_ANALYSIS:
                flash(f'You need {CREDITS_PER_CV_ANALYSIS} credits to analyse. You have {user.credits}.', 'warning')
                return redirect(url_for('buy_credits'))
            if not deduct_credits(user_id, CREDITS_PER_CV_ANALYSIS, action='cv_analysis'):
                flash(f'Insufficient credits. You need {CREDITS_PER_CV_ANALYSIS} credits.', 'warning')
                return redirect(url_for('buy_credits'))
            credits_charged = True
            user = User.query.get(user_id)
            session['user_credits'] = user.credits

        try:
            from llm_service import analyze_cv_only
            results = analyze_cv_only(extracted_text)
            _log_llm_usage(user_id, 'cv_analysis')
        except Exception as e:
            if credits_charged:
                _refund_analysis_credits(user_id, CREDITS_PER_CV_ANALYSIS)
            logger.error('CV analysis error (analyse-only): %s', e, exc_info=True)
            flash(f'Analysis error: {e}', 'error')
            return redirect(url_for('resume_studio_library'))

        # Store for Analysis Reports page
        session['_data_token'] = _save_session_data({
            'cv_text': extracted_text[:20000],
            'cv_analysis_results': results,
            'tier': 1,
        })

        try:
            track_analysis(user_id)
            session['user_credits'] = User.query.get(user_id).credits
        except Exception:
            pass

        flash('Storage limit reached (5/5). Resume analysed but not stored — delete one to store new resumes.', 'warning')
        return render_template('cv_results.html', results=results,
                               credits_remaining=user.credits if user else 0,
                               active_category='resume_studio', active_page='analysis')

    # ── Normal flow: store resume + auto-analyse ──
    # If setting as primary, un-primary all others
    if is_primary:
        UserResume.query.filter_by(user_id=user_id, is_primary=True)\
            .update({'is_primary': False})

    # First resume is always primary
    if count == 0:
        is_primary = True

    resume = UserResume(
        user_id=user_id,
        label=label[:100],
        is_primary=is_primary,
        filename=filename,
        file_data=file_data,
        extracted_text=extracted_text[:50000] if extracted_text else None,
        file_size=len(file_data),
        target_job=target_job[:200],
    )
    db.session.add(resume)
    db.session.commit()

    # Auto-analyze in background thread (returns immediately)
    if extracted_text:
        _auto_analyze_resume(resume.id, user_id, extracted_text)
        flash(f'Resume "{label}" uploaded! Analysis is running...', 'success')
    else:
        flash(f'Resume "{label}" uploaded.', 'success')

    return redirect(url_for('resume_studio_library'))


@app.route('/my-resumes/<int:resume_id>/set-primary', methods=['POST'])
def set_primary_resume(resume_id):
    """Set a resume as the primary one."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    resume = UserResume.query.filter_by(id=resume_id, user_id=session['user_id']).first()
    if not resume:
        flash('Resume not found.', 'error')
        return redirect(url_for('resume_studio_library'))

    UserResume.query.filter_by(user_id=session['user_id'], is_primary=True)\
        .update({'is_primary': False})
    resume.is_primary = True
    db.session.commit()

    flash(f'"{resume.label}" is now your primary resume.', 'success')
    return redirect(url_for('resume_studio_library'))


@app.route('/my-resumes/<int:resume_id>/delete', methods=['POST'])
def delete_resume(resume_id):
    """Delete a stored resume."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    resume = UserResume.query.filter_by(id=resume_id, user_id=session['user_id']).first()
    if not resume:
        flash('Resume not found.', 'error')
        return redirect(url_for('resume_studio_library'))

    was_primary = resume.is_primary
    label = resume.label
    db.session.delete(resume)
    db.session.commit()

    # If deleted resume was primary, promote the most recent one
    if was_primary:
        remaining = UserResume.query.filter_by(user_id=session['user_id'])\
            .order_by(UserResume.created_at.desc()).first()
        if remaining:
            remaining.is_primary = True
            db.session.commit()

    flash(f'Resume "{label}" deleted.', 'success')
    return redirect(url_for('resume_studio_library'))


@app.route('/my-resumes/<int:resume_id>/download')
def download_resume(resume_id):
    """Download a specific stored resume."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    resume = UserResume.query.filter_by(id=resume_id, user_id=session['user_id']).first()
    if not resume:
        flash('Resume not found.', 'error')
        return redirect(url_for('resume_studio_library'))

    return send_file(
        io.BytesIO(resume.file_data),
        as_attachment=True,
        download_name=resume.filename,
        mimetype='application/octet-stream',
    )


@app.route('/my-resumes/<int:resume_id>/results')
def resume_results(resume_id):
    """View stored analysis results for a resume."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    resume = UserResume.query.filter_by(id=resume_id, user_id=session['user_id']).first()
    if not resume:
        flash('Resume not found.', 'error')
        return redirect(url_for('resume_studio_library'))

    if resume.analysis_status != 'completed' or not resume.analysis_results_json:
        flash('No analysis results available for this resume. Try analyzing it first.', 'warning')
        return redirect(url_for('resume_studio_library'))

    results = json.loads(resume.analysis_results_json)

    # Bridge to session so existing JD matching flow works
    session['_data_token'] = _save_session_data({
        'cv_text': resume.extracted_text[:20000] if resume.extracted_text else '',
        'cv_analysis_results': results,
        'tier': 1,
    })

    return render_template('cv_results.html', results=results,
                           credits_remaining=session.get('user_credits', 0),
                           resume_id=resume_id,
                           active_category='resume_studio', active_page='analysis')


@app.route('/my-resumes/<int:resume_id>/analyze', methods=['POST'])
def reanalyze_resume(resume_id):
    """Re-analyze an existing resume (uses stored extracted_text)."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    resume = UserResume.query.filter_by(id=resume_id, user_id=user_id).first()
    if not resume:
        flash('Resume not found.', 'error')
        return redirect(url_for('resume_studio_library'))

    if not resume.extracted_text:
        flash('No text available for this resume. Please re-upload it.', 'error')
        return redirect(url_for('resume_studio_library'))

    success = _auto_analyze_resume(resume.id, user_id, resume.extracted_text)
    if success:
        user = User.query.get(user_id)
        if user:
            session['user_credits'] = user.credits
        flash(f'Re-analysis started for "{resume.label}". Results will appear shortly.', 'success')
    else:
        user = User.query.get(user_id)
        if user and user.credits < 2:
            flash('Insufficient credits for analysis. Please buy more credits.', 'warning')
            return redirect(url_for('buy_credits'))
        flash('Analysis failed. Please try again later.', 'error')

    return redirect(url_for('resume_studio_library'))


@app.route('/my-resumes/<int:resume_id>/update', methods=['POST'])
def update_resume(resume_id):
    """Update resume label and/or target job."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    resume = UserResume.query.filter_by(id=resume_id, user_id=session['user_id']).first()
    if not resume:
        flash('Resume not found.', 'error')
        return redirect(url_for('resume_studio_library'))

    new_label = request.form.get('label', '').strip()
    new_target_job = request.form.get('target_job', '').strip()

    if new_label:
        resume.label = new_label[:100]
    if new_target_job:
        resume.target_job = new_target_job[:200]

    resume.updated_at = datetime.utcnow()
    db.session.commit()

    flash(f'Resume "{resume.label}" updated.', 'success')
    return redirect(url_for('resume_studio_library'))


@app.route('/my-resumes/<int:resume_id>/status')
def resume_status(resume_id):
    """Lightweight JSON endpoint for polling analysis progress."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    resume = UserResume.query.filter_by(id=resume_id, user_id=session['user_id']).first()
    if not resume:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({
        'status': resume.analysis_status or 'none',
        'ats_score': resume.ats_score,
    })


# ---------------------------------------------------------------------------
# My Profile — country-adaptive profile for AutoFill extension
# ---------------------------------------------------------------------------

def _prefill_profile_from_resume(user, profile_obj):
    """Merge empty profile fields from the user's primary resume.

    Safe to call on every visit — only fills fields that are still blank,
    so it never overwrites manual edits.
    """
    resume = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()
    if not resume:
        resume = UserResume.query.filter_by(user_id=user.id).order_by(
            UserResume.updated_at.desc()).first()
    if not resume:
        parts = (user.name or '').split(None, 1)
        if not profile_obj.first_name:
            profile_obj.first_name = parts[0] if parts else ''
        if not profile_obj.last_name:
            profile_obj.last_name = parts[1] if len(parts) > 1 else ''
        return

    rp = _build_extension_profile(resume)
    b = rp.get('basics', {})
    loc = b.get('location', {})
    work = rp.get('work', [{}])[0] if rp.get('work') else {}
    edu = rp.get('education', [{}])[0] if rp.get('education') else {}

    # Only fill empty fields — never overwrite user edits
    if not profile_obj.first_name:
        profile_obj.first_name = b.get('firstName', '')
    if not profile_obj.last_name:
        profile_obj.last_name = b.get('lastName', '')
    if not profile_obj.phone:
        profile_obj.phone = b.get('phone', '')
    if not profile_obj.city:
        profile_obj.city = loc.get('city', '')
    if not profile_obj.state:
        profile_obj.state = loc.get('region', '')
    if not profile_obj.linkedin_url:
        profile_obj.linkedin_url = b.get('linkedin', '')
    if not profile_obj.github_url:
        profile_obj.github_url = b.get('github', '')
    if not profile_obj.website_url:
        profile_obj.website_url = b.get('website', '')
    if not profile_obj.current_company:
        profile_obj.current_company = work.get('company', '')
    if not profile_obj.current_title:
        profile_obj.current_title = work.get('position', '') or b.get('title', '')
    if not profile_obj.university:
        profile_obj.university = edu.get('institution', '')
    if not profile_obj.degree:
        profile_obj.degree = edu.get('studyType', '')
    if not profile_obj.major:
        profile_obj.major = edu.get('area', '')
    if not profile_obj.gpa:
        profile_obj.gpa = edu.get('score', '')


@app.route('/my-profile')
def my_profile():
    """Country-adaptive profile page for AutoFill extension data."""
    if not session.get('user_id'):
        session['_login_next'] = url_for('my_profile')
        flash('Please sign in to view your profile.', 'warning')
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        return redirect(url_for('login_page'))

    profile = UserProfile.query.filter_by(user_id=user.id).first()
    if not profile:
        profile = UserProfile(user_id=user.id)
        db.session.add(profile)
    # Always merge empty fields from resume (safe — never overwrites edits)
    _prefill_profile_from_resume(user, profile)
    db.session.commit()

    return render_template('my_profile.html',
                           active_section='my_profile',
                           user=user, profile=profile)


@app.route('/api/profile', methods=['GET', 'POST'])
def api_user_profile():
    """GET: Return user profile data. POST: Save user profile data."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404

    if request.method == 'GET':
        profile = UserProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            return jsonify({'setup_completed': False})
        return jsonify(profile.to_dict())

    # POST
    data = request.get_json(silent=True) or {}
    profile = UserProfile.query.filter_by(user_id=user.id).first()
    if not profile:
        profile = UserProfile(user_id=user.id)
        db.session.add(profile)

    profile.update_from_dict(data)

    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        logger.error('Failed to save profile: %s', e)
        return jsonify({'error': 'Failed to save profile'}), 500


# ---------------------------------------------------------------------------
# Settings placeholder
# ---------------------------------------------------------------------------

@app.route('/settings')
def settings():
    """Placeholder settings page."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))
    return render_template('settings.html', active_section='settings')


# ---------------------------------------------------------------------------
# Admin endpoints — protected by ADMIN_TOKEN
# ---------------------------------------------------------------------------

@app.route('/admin/dashboard')
def admin_dashboard():
    """Admin dashboard — users, credits, LLM token consumption."""
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return 'Unauthorized', 401

    from sqlalchemy import func

    # Summary stats
    total_users = User.query.count()
    total_credits_consumed = db.session.query(
        func.coalesce(func.sum(CreditUsage.credits_used), 0)
    ).filter(CreditUsage.credits_used > 0).scalar()
    total_input_tokens = db.session.query(
        func.coalesce(func.sum(LLMUsage.estimated_input_tokens), 0)
    ).scalar()
    total_output_tokens = db.session.query(
        func.coalesce(func.sum(LLMUsage.estimated_output_tokens), 0)
    ).scalar()

    # All users with their LLM token usage
    users = User.query.order_by(User.created_at.desc()).all()
    user_tokens = {}
    token_rows = db.session.query(
        LLMUsage.user_id,
        func.sum(LLMUsage.estimated_input_tokens).label('input_tokens'),
        func.sum(LLMUsage.estimated_output_tokens).label('output_tokens'),
        func.count(LLMUsage.id).label('call_count'),
    ).group_by(LLMUsage.user_id).all()
    for row in token_rows:
        user_tokens[row.user_id] = {
            'input_tokens': row.input_tokens or 0,
            'output_tokens': row.output_tokens or 0,
            'call_count': row.call_count or 0,
        }

    # Recent 20 activities (credit usages)
    recent_activities = db.session.query(CreditUsage, User).join(
        User, CreditUsage.user_id == User.id
    ).order_by(CreditUsage.created_at.desc()).limit(20).all()

    return render_template('admin_dashboard.html',
                           token=token,
                           total_users=total_users,
                           total_credits_consumed=total_credits_consumed,
                           total_input_tokens=total_input_tokens,
                           total_output_tokens=total_output_tokens,
                           users=users,
                           user_tokens=user_tokens,
                           recent_activities=recent_activities)


@app.route('/admin/grant-credits')
def admin_grant_credits():
    """Grant credits to a user. Usage: /admin/grant-credits?token=...&email=...&credits=20"""
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return 'Unauthorized', 401
    email = request.args.get('email', '')
    credits_to_add = int(request.args.get('credits', 0))
    if not email or credits_to_add <= 0:
        return jsonify({'error': 'Provide ?email=...&credits=N'}), 400
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'error': f'User {email} not found'}), 404
    user.credits += credits_to_add
    usage = CreditUsage(user_id=user.id, credits_used=-credits_to_add, action='admin_grant')
    db.session.add(usage)
    db.session.commit()
    return jsonify({'success': True, 'email': email, 'credits_added': credits_to_add,
                    'new_balance': user.credits})


@app.route('/admin/cvs')
def list_cvs():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return 'Unauthorized', 401
    cvs = StoredCV.query.order_by(StoredCV.created_at.desc()).all()
    file_info = []
    for cv in cvs:
        file_info.append({
            'id': cv.id,
            'name': cv.filename,
            'size_kb': round((cv.file_size or 0) / 1024, 1),
            'email': cv.user_email or 'unknown',
            'date': cv.created_at.strftime('%Y-%m-%d %H:%M') if cv.created_at else '',
        })
    return render_template('admin_cvs.html', files=file_info, token=token)


@app.route('/admin/cvs/download/<int:cv_id>')
def download_cv(cv_id):
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return 'Unauthorized', 401
    cv = StoredCV.query.get(cv_id)
    if not cv:
        return 'CV not found', 404
    return send_file(
        io.BytesIO(cv.file_data),
        as_attachment=True,
        download_name=cv.filename,
        mimetype='application/octet-stream',
    )


@app.route('/admin/cvs/download-all')
def download_all_cvs():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return 'Unauthorized', 401
    cvs = StoredCV.query.all()
    if not cvs:
        return 'No CVs stored yet', 404
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for cv in cvs:
            zf.writestr(cv.filename, cv.file_data)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name='collected_cvs.zip',
                     mimetype='application/zip')


@app.route('/admin/users')
def admin_list_users():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return jsonify({'error': 'Unauthorized'}), 401
    users = User.query.all()
    return jsonify({'users': [
        {'id': u.id, 'email': u.email, 'name': u.name, 'credits': u.credits,
         'analysis_count': u.analysis_count}
        for u in users
    ]})


@app.route('/api/cvs')
def api_list_cvs():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return jsonify({'error': 'Unauthorized'}), 401
    cvs = StoredCV.query.order_by(StoredCV.created_at.desc()).all()
    return jsonify({'files': [
        {'id': cv.id, 'filename': cv.filename, 'email': cv.user_email,
         'size_bytes': cv.file_size, 'created_at': cv.created_at.isoformat() if cv.created_at else None}
        for cv in cvs
    ]})


@app.route('/admin/llm-status')
def admin_llm_status():
    """Show LLM waterfall provider status."""
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return jsonify({'error': 'Unauthorized'}), 401
    from llm_service import LLM_ENABLED, _PROVIDERS
    return jsonify({
        'llm_enabled': LLM_ENABLED,
        'waterfall': [
            {'name': p['name'], 'model': p['model'], 'base_url': p['base_url'],
             'max_context': p['max_context']}
            for p in _PROVIDERS
        ],
        'provider_count': len(_PROVIDERS),
    })


# ---------------------------------------------------------------------------
# SEO: sitemap.xml & robots.txt
# ---------------------------------------------------------------------------

@app.route('/sitemap.xml')
def sitemap():
    """Dynamic sitemap for search engine discovery."""
    pages = [
        {'loc': '/',            'changefreq': 'weekly',  'priority': '1.0'},
        {'loc': '/analyze',     'changefreq': 'weekly',  'priority': '0.9'},
        {'loc': '/resume-tips', 'changefreq': 'monthly', 'priority': '0.8'},
        {'loc': '/buy-credits', 'changefreq': 'monthly', 'priority': '0.7'},
        {'loc': '/experts',     'changefreq': 'monthly', 'priority': '0.6'},
        {'loc': '/mentors',     'changefreq': 'monthly', 'priority': '0.6'},
        {'loc': '/login',       'changefreq': 'yearly',  'priority': '0.4'},
    ]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for p in pages:
        xml.append('  <url>')
        xml.append(f'    <loc>https://levelupx.ai{p["loc"]}</loc>')
        xml.append(f'    <changefreq>{p["changefreq"]}</changefreq>')
        xml.append(f'    <priority>{p["priority"]}</priority>')
        xml.append('  </url>')
    xml.append('</urlset>')
    return Response('\n'.join(xml), mimetype='application/xml')


@app.route('/robots.txt')
def robots():
    """Robots.txt for search engine crawl guidance."""
    content = """User-agent: *
Allow: /
Disallow: /admin/
Disallow: /api/
Disallow: /auth/
Disallow: /logout
Disallow: /account
Disallow: /analyze-cv
Disallow: /analyze-jd
Disallow: /rewrite-cv
Disallow: /download-cv
Disallow: /download-rewritten-cv
Disallow: /grant-free-credits
Disallow: /payment/
Disallow: /refine-section
Disallow: /update-rewritten-cv
Disallow: /my-resumes

Sitemap: https://levelupx.ai/sitemap.xml
"""
    return Response(content.strip(), mimetype='text/plain')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(debug=True, port=port)
