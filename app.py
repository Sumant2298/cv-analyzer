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

from analyzer import analyze_cv_against_jd
from models import (db, User, Transaction, CreditUsage, LLMUsage, StoredCV,
                    UserResume, JDAnalysis, JobPreferences, JobPool, ApiUsage)

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
# Context processor — keep credit balance fresh in session
# ---------------------------------------------------------------------------
@app.before_request
def _refresh_user_credits():
    """Refresh user credits from DB into session on every request."""
    if session.get('user_id'):
        try:
            user = User.query.get(session['user_id'])
            if user:
                session['user_credits'] = user.credits
        except Exception:
            pass


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
    return '\n'.join(text_parts)


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
                # Indent bullets
                indent = 8
                pdf.x = pdf.l_margin + indent
                pdf.multi_cell(usable_w - indent, 5, '  ' + bullet_text)
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

    return render_template('dashboard.html',
                           user=user,
                           resume_count=resume_count,
                           recent_activity=recent_activity,
                           active_section='dashboard')


@app.route('/analyze')
def analyze_page():
    """Unified resumes page — table of uploaded CVs with analysis results."""
    if not session.get('user_id'):
        session['_login_next'] = url_for('analyze_page')
        flash('Please sign in to manage and analyze your resumes.', 'warning')
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    from payments import FREE_CV_ANALYSIS_LIMIT, CREDITS_PER_CV_ANALYSIS, CREDITS_PER_JD_ANALYSIS
    user_data = {
        'analysis_count': user.analysis_count,
        'credits': user.credits,
        'first_free': user.analysis_count < FREE_CV_ANALYSIS_LIMIT,
        'credits_per_cv': CREDITS_PER_CV_ANALYSIS,
    }

    resumes = UserResume.query.filter_by(user_id=user.id)\
        .order_by(UserResume.created_at.desc()).all()

    # Get primary resume for JD analysis section
    primary = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()

    # Get JD analysis history with pre-computed ATS scores
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
        # Extract job name from first meaningful line of JD text
        jd_name = ''
        if jd.jd_text:
            for line in jd.jd_text.strip().split('\n'):
                line = line.strip()
                if line and len(line) > 3:
                    jd_name = line[:80]
                    break
        jd_names[jd.id] = jd_name or 'Job Description'

    return render_template('resumes.html',
                           resumes=resumes,
                           user_data=user_data,
                           primary_resume=primary,
                           jd_histories=jd_histories,
                           jd_scores=jd_scores,
                           jd_names=jd_names,
                           credits_per_jd=CREDITS_PER_JD_ANALYSIS,
                           credits_remaining=user.credits,
                           active_section='resumes')


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
        session['_login_next'] = url_for('analyze_page')
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
        return redirect(url_for('analyze_page'))

    if not cv_text:
        if credits_charged:
            _refund_analysis_credits(user_id, CREDITS_PER_CV_ANALYSIS)
        flash('Could not get CV content. Please try uploading a file or pasting text.', 'error')
        return redirect(url_for('analyze_page'))

    try:
        from llm_service import analyze_cv_only
        results = analyze_cv_only(cv_text)
        _log_llm_usage(user_id, 'cv_analysis')
    except Exception as e:
        if credits_charged:
            _refund_analysis_credits(user_id, CREDITS_PER_CV_ANALYSIS)
        logger.error('CV analysis error: %s', e, exc_info=True)
        flash(f'Analysis error: {e}', 'error')
        return redirect(url_for('analyze_page'))

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
                           active_section='resumes')


@app.route('/analyze-jd', methods=['POST'])
def analyze_jd():
    """Tier 2: CV vs JD analysis (full LLM pipeline)."""
    # ---- Login gate ----
    if not _oauth_enabled or not session.get('user_id'):
        session['_login_next'] = url_for('analyze_page')
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
        return redirect(url_for('analyze_page'))

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
        return redirect(url_for('analyze_page'))

    if not jd_text:
        _refund_analysis_credits(user_id, CREDITS_PER_JD_ANALYSIS)
        flash('Could not get Job Description content. Please try again.', 'error')
        return redirect(url_for('analyze_page'))

    if len(jd_text.split()) < 10:
        flash('Job description seems very short. Results may be unreliable.', 'warning')

    try:
        results = analyze_cv_against_jd(cv_text, jd_text)
        _log_llm_usage(user_id, 'jd_analysis')
    except Exception as e:
        _refund_analysis_credits(user_id, CREDITS_PER_JD_ANALYSIS)
        logger.error('JD analysis error: %s', e, exc_info=True)
        flash(f'Analysis error: {e}', 'error')
        return redirect(url_for('analyze_page'))

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

    return render_template('results.html', results=results, active_section='resumes')


# ---------------------------------------------------------------------------
# Jobs — JD upload & auto-match against primary CV (background thread)
# Uses DB (JDAnalysis model) instead of in-memory dict so it works across
# multiple gunicorn workers on Railway.
# ---------------------------------------------------------------------------


@app.route('/jobs')
def jobs_page():
    """Jobs page — search public job listings with saved filter preferences."""
    if not session.get('user_id'):
        session['_login_next'] = url_for('jobs_page')
        flash('Please sign in to search for jobs.', 'warning')
        return redirect(url_for('login_page'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('Session expired. Please sign in again.', 'error')
        return redirect(url_for('login_page'))

    primary = UserResume.query.filter_by(user_id=user.id, is_primary=True).first()

    # Load saved preferences (if any)
    prefs = JobPreferences.query.filter_by(user_id=user.id).first()
    show_wizard = not prefs or not prefs.setup_completed
    preferences_json = json.dumps(prefs.to_dict()) if prefs and prefs.setup_completed else 'null'

    return render_template('jobs.html',
                           primary_resume=primary,
                           credits_remaining=user.credits,
                           show_wizard=show_wizard,
                           preferences_json=preferences_json,
                           active_section='jobs')


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


@app.route('/jobs/skills-suggest')
def jobs_skills_suggest():
    """Lightweight autocomplete endpoint for skills tag input."""
    q = request.args.get('q', '').lower().strip()
    if len(q) < 2:
        return jsonify([])
    from skills_data import ALL_KNOWN_SKILLS
    matches = sorted([s for s in ALL_KNOWN_SKILLS if q in s.lower()])[:10]
    return jsonify(matches)


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


@app.route('/jobs/suggest-skills', methods=['POST'])
def jobs_suggest_skills():
    """LLM-powered skill suggestions from Function + Role Family + Level."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json(silent=True) or {}
    function_id = data.get('function_id', '')
    role_family_id = data.get('role_family_id', '')
    level_id = data.get('level_id', '')

    if not function_id or not role_family_id:
        return jsonify({'error': 'function_id and role_family_id required'}), 400

    from skills_data import TAXONOMY, LEVEL_LABELS
    func_data = TAXONOMY.get(function_id, {})
    func_label = func_data.get('label', function_id)
    rf_data = func_data.get('role_families', {}).get(role_family_id, {})
    rf_label = rf_data.get('label', role_family_id)
    level_label = LEVEL_LABELS.get(level_id, level_id) if level_id else 'any level'

    system = (
        'You are a technical recruiting expert. Return ONLY a valid JSON object '
        'with a single key "skills" containing an array of 8-12 strings. '
        'Each string is a specific technical skill, tool, or technology.'
    )
    prompt = (
        f'List 8-12 in-demand skills/technologies for this role:\n'
        f'- Function: {func_label}\n'
        f'- Role Family: {rf_label}\n'
        f'- Level: {level_label}\n'
        f'Include a mix of core technical skills, tools, and frameworks '
        f'that employers commonly require for this role in 2025-2026.'
    )

    try:
        from llm_service import _call_llm
        result = _call_llm(system, prompt, max_tokens=500, temperature=0.5, timeout=15.0)
        skills = result.get('skills', [])
        if not isinstance(skills, list):
            skills = []
        skills = [str(s) for s in skills if isinstance(s, str) and s.strip()][:12]
        return jsonify({'skills': skills})
    except Exception as e:
        logger.error('LLM skill suggestion failed: %s', e)
        fallback_skills = rf_data.get('skills', [])[:8]
        return jsonify({'skills': fallback_skills, 'fallback': True})


@app.route('/jobs/location-autocomplete')
def jobs_location_autocomplete():
    """Location typeahead using Nominatim (OpenStreetMap) with local fallback."""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401

    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'suggestions': []})

    from skills_data import INDIAN_CITIES
    local_matches = [c for c in INDIAN_CITIES if q.lower() in c.lower()]

    try:
        resp = http_requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={
                'q': q,
                'format': 'json',
                'addressdetails': 1,
                'limit': 8,
                'featuretype': 'city',
            },
            headers={'User-Agent': 'LevelUpX-JobSearch/1.0'},
            timeout=5,
        )
        resp.raise_for_status()
        results = resp.json()

        suggestions = []
        seen = set()

        for city in local_matches:
            key = city.lower()
            if key not in seen:
                seen.add(key)
                suggestions.append({'city': city, 'state': '', 'country': 'India'})

        for r in results:
            addr = r.get('address', {})
            city = (addr.get('city') or addr.get('town')
                    or addr.get('state_district') or r.get('name', ''))
            state = addr.get('state', '')
            country = addr.get('country', '')
            display = city
            if state:
                display += f', {state}'
            key = display.lower()
            if key not in seen and city:
                seen.add(key)
                suggestions.append({'city': display, 'state': state, 'country': country})

        return jsonify({'suggestions': suggestions[:10]})
    except Exception as e:
        logger.warning('Nominatim autocomplete failed: %s, falling back to local', e)
        return jsonify({'suggestions': [
            {'city': c, 'state': '', 'country': 'India'}
            for c in local_matches[:10]
        ]})


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

    use_preferences = request.args.get('use_preferences', '') == '1'

    if use_preferences:
        # Preference-based search: pool-first, then API fallback
        prefs_obj = JobPreferences.query.filter_by(user_id=user.id).first()
        if not prefs_obj or not prefs_obj.setup_completed:
            return jsonify({'error': 'No saved preferences', 'jobs': [], 'total_count': 0})

        prefs = prefs_obj.to_dict()

        # Check if there's at least one meaningful filter
        if not prefs.get('job_titles') and not prefs.get('skills'):
            return jsonify({'error': 'Please add at least one job title or skill in your preferences',
                            'jobs': [], 'total_count': 0})

        from job_filter import (build_jsearch_params, apply_local_filters,
                                search_from_pool, normalize_api_params_for_cache)
        from job_search import (search_jobs, check_quota, get_cached_search,
                                get_stale_cache)

        warning = None
        normalized, cache_key = normalize_api_params_for_cache(prefs)

        # 1. Check read-through cache (24h TTL, keyed on API params only)
        cached_result, _ = get_cached_search(cache_key)
        if cached_result:
            jobs = apply_local_filters(cached_result.get('jobs', []), prefs)
            source = 'cache'
        else:
            # 2. Cache miss — check quota before calling API
            under_limit, calls_made, limit = check_quota()

            if not under_limit:
                # Quota exceeded — try pool, then stale cache
                pool_results = search_from_pool(prefs)
                if pool_results is not None:
                    jobs = pool_results
                    source = 'pool'
                else:
                    stale_result, _ = get_stale_cache(cache_key)
                    if stale_result:
                        jobs = apply_local_filters(stale_result.get('jobs', []), prefs)
                        source = 'cache'
                    else:
                        jobs = []
                        source = 'quota_exceeded'
                warning = f'Monthly API quota reached ({calls_made}/{limit}). Showing cached results.'
            else:
                # 3. Quota OK — try pool first, then API
                pool_results = search_from_pool(prefs)
                if pool_results is not None:
                    jobs = pool_results
                    source = 'pool'
                else:
                    api_params = build_jsearch_params(prefs)
                    api_results = search_jobs(
                        query=api_params.get('query', ''),
                        location=api_params.get('location', ''),
                        employment_type=api_params.get('employment_type', ''),
                        experience=api_params.get('experience', ''),
                        cache_key=cache_key,
                        normalized_params=normalized,
                    )
                    if api_results.get('error'):
                        return jsonify(api_results)
                    jobs = apply_local_filters(api_results.get('jobs', []), prefs)
                    source = 'api'

        # Deduplicate by job_id
        seen_ids = set()
        deduped = []
        for job in jobs:
            jid = job.get('job_id', '')
            if jid and jid in seen_ids:
                continue
            if jid:
                seen_ids.add(jid)
            deduped.append(job)
        jobs = deduped

        results = {
            'jobs': jobs,
            'total_count': len(jobs),
            'source': source,
            'cache_key': cache_key[:12],
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
                        job['matched_skills'] = json.loads(cached_ats.matched_skills or '[]')[:5]
                        job['missing_skills'] = json.loads(cached_ats.missing_skills or '[]')[:5]
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
                except Exception:
                    job['ats_score'] = None
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

    # Save snapshot for instant load on next visit
    if use_preferences and results.get('jobs'):
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
        return redirect(url_for('analyze_page'))

    cv_text = primary.extracted_text
    if not cv_text or len(cv_text.strip()) < 50:
        flash('Your primary resume has no extracted text. Please re-upload it.', 'warning')
        return redirect(url_for('analyze_page'))

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
        return redirect(url_for('analyze_page'))

    if not jd_text:
        flash('Could not extract Job Description content. Please try again.', 'error')
        return redirect(url_for('analyze_page'))

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
        return redirect(url_for('analyze_page'))

    row = JDAnalysis.query.get(jd_id)
    if not row or row.status not in ('analyzing', 'completed'):
        flash('No analysis in progress.', 'warning')
        return redirect(url_for('analyze_page'))

    return render_template('jobs_waiting.html', active_section='resumes')


@app.route('/jobs/results')
def jobs_results():
    """Show JD vs CV analysis results."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    jd_id = session.get('_jd_analysis_id')
    if not jd_id:
        flash('No completed analysis found. Please try again.', 'warning')
        return redirect(url_for('analyze_page'))

    row = JDAnalysis.query.get(jd_id)
    if not row or row.status != 'completed' or not row.results_json:
        flash('No completed analysis found. Please try again.', 'warning')
        return redirect(url_for('analyze_page'))

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

    return render_template('results.html', results=results, active_section='resumes')


@app.route('/jobs/<int:jd_id>/results')
def jd_analysis_results(jd_id):
    """View a specific past JD analysis by ID."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    row = JDAnalysis.query.filter_by(id=jd_id, user_id=session['user_id']).first()
    if not row:
        flash('Analysis not found.', 'error')
        return redirect(url_for('analyze_page'))

    if row.status == 'analyzing':
        session['_jd_analysis_id'] = row.id
        return redirect(url_for('jobs_waiting'))

    if row.status != 'completed' or not row.results_json:
        flash('No completed analysis results available.', 'warning')
        return redirect(url_for('analyze_page'))

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

    return render_template('results.html', results=results, active_section='resumes')


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

    return redirect(url_for('analyze_page'))


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
        return redirect(url_for('analyze_page'))

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
        return redirect(url_for('analyze_page'))

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
                           active_section='resumes')


@app.route('/rewrite-cv', methods=['POST'])
def rewrite_cv_action():
    """Perform the rewrite — deduct credits, call LLM, show results."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    data = _load_session_data(session.get('_data_token', ''))
    if not data.get('cv_text') or not data.get('jd_text'):
        flash('No analysis data found. Please run analysis first.', 'warning')
        return redirect(url_for('analyze_page'))

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
        return redirect(url_for('analyze_page'))

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
                           active_section='resumes')


@app.route('/download-rewritten-cv')
def download_rewritten_cv():
    """Download the rewritten CV as a PDF."""
    data = _load_session_data(session.get('_data_token', ''))
    rewritten_text = data.get('rewritten_cv', '')
    if not rewritten_text:
        flash('No rewritten CV available. Please perform a rewrite first.', 'warning')
        return redirect(url_for('analyze_page'))

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

    # Update session data
    token = session.get('_data_token', '')
    session_data = _load_session_data(token)
    session_data['rewritten_cv'] = rewritten_cv
    # Save back
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
    return render_template('experts.html', active_section='experts')


@app.route('/mentors')
def mentors():
    return render_template('mentors.html', active_section='mentors')


@app.route('/resume-tips')
def resume_tips():
    return render_template('resume_tips.html')


# ---------------------------------------------------------------------------
# My Resumes — store up to 5 resumes per user
# ---------------------------------------------------------------------------

@app.route('/my-resumes')
def my_resumes():
    """Redirect to unified resumes page."""
    return redirect(url_for('analyze_page'))


@app.route('/my-resumes/upload', methods=['POST'])
def upload_resume():
    """Upload a new resume (max 5 per user) and auto-analyze."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    count = UserResume.query.filter_by(user_id=user_id).count()
    if count >= 5:
        flash('You can store up to 5 resumes. Please delete one before uploading a new one.', 'warning')
        return redirect(url_for('analyze_page'))

    file = request.files.get('resume_file')
    if not file or not file.filename:
        flash('Please select a file to upload.', 'error')
        return redirect(url_for('analyze_page'))

    if not allowed_file(file.filename):
        flash('Only PDF, DOCX, and TXT files are supported.', 'error')
        return redirect(url_for('analyze_page'))

    filename = secure_filename(file.filename)
    file_data = file.read()

    if len(file_data) > 5 * 1024 * 1024:
        flash('File too large. Maximum size is 5 MB.', 'error')
        return redirect(url_for('analyze_page'))

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

    return redirect(url_for('analyze_page'))


@app.route('/my-resumes/<int:resume_id>/set-primary', methods=['POST'])
def set_primary_resume(resume_id):
    """Set a resume as the primary one."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    resume = UserResume.query.filter_by(id=resume_id, user_id=session['user_id']).first()
    if not resume:
        flash('Resume not found.', 'error')
        return redirect(url_for('analyze_page'))

    UserResume.query.filter_by(user_id=session['user_id'], is_primary=True)\
        .update({'is_primary': False})
    resume.is_primary = True
    db.session.commit()

    flash(f'"{resume.label}" is now your primary resume.', 'success')
    return redirect(url_for('analyze_page'))


@app.route('/my-resumes/<int:resume_id>/delete', methods=['POST'])
def delete_resume(resume_id):
    """Delete a stored resume."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    resume = UserResume.query.filter_by(id=resume_id, user_id=session['user_id']).first()
    if not resume:
        flash('Resume not found.', 'error')
        return redirect(url_for('analyze_page'))

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
    return redirect(url_for('analyze_page'))


@app.route('/my-resumes/<int:resume_id>/download')
def download_resume(resume_id):
    """Download a specific stored resume."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    resume = UserResume.query.filter_by(id=resume_id, user_id=session['user_id']).first()
    if not resume:
        flash('Resume not found.', 'error')
        return redirect(url_for('analyze_page'))

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
        return redirect(url_for('analyze_page'))

    if resume.analysis_status != 'completed' or not resume.analysis_results_json:
        flash('No analysis results available for this resume. Try analyzing it first.', 'warning')
        return redirect(url_for('analyze_page'))

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
                           active_section='resumes')


@app.route('/my-resumes/<int:resume_id>/analyze', methods=['POST'])
def reanalyze_resume(resume_id):
    """Re-analyze an existing resume (uses stored extracted_text)."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    resume = UserResume.query.filter_by(id=resume_id, user_id=user_id).first()
    if not resume:
        flash('Resume not found.', 'error')
        return redirect(url_for('analyze_page'))

    if not resume.extracted_text:
        flash('No text available for this resume. Please re-upload it.', 'error')
        return redirect(url_for('analyze_page'))

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

    return redirect(url_for('analyze_page'))


@app.route('/my-resumes/<int:resume_id>/update', methods=['POST'])
def update_resume(resume_id):
    """Update resume label and/or target job."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    resume = UserResume.query.filter_by(id=resume_id, user_id=session['user_id']).first()
    if not resume:
        flash('Resume not found.', 'error')
        return redirect(url_for('analyze_page'))

    new_label = request.form.get('label', '').strip()
    new_target_job = request.form.get('target_job', '').strip()

    if new_label:
        resume.label = new_label[:100]
    if new_target_job:
        resume.target_job = new_target_job[:200]

    resume.updated_at = datetime.utcnow()
    db.session.commit()

    flash(f'Resume "{resume.label}" updated.', 'success')
    return redirect(url_for('analyze_page'))


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
