import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()  # Load .env file (GROQ_API_KEY, etc.)

import requests as http_requests
from bs4 import BeautifulSoup
from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from analyzer import analyze_cv_against_jd
from models import db, User, Transaction, CreditUsage

# Configure logging for debugging on Render
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Trust Railway's reverse proxy headers so url_for() generates https:// URLs
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
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

# Folder to store consented CVs
CV_STORAGE = os.environ.get('CV_STORAGE_PATH',
                            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'collected_cvs'))
os.makedirs(CV_STORAGE, exist_ok=True)

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


def _text_to_pdf(text: str, output_path: str):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Helvetica', size=10)
    # Sanitize text: replace unicode chars that Helvetica (Latin-1) can't render
    clean = text
    clean = clean.replace('\u2018', "'").replace('\u2019', "'")   # smart quotes
    clean = clean.replace('\u201c', '"').replace('\u201d', '"')   # smart double quotes
    clean = clean.replace('\u2013', '-').replace('\u2014', '--')  # en/em dash
    clean = clean.replace('\u2022', '-').replace('\u2023', '>')   # bullets
    clean = clean.replace('\u2026', '...')                        # ellipsis
    clean = clean.replace('\u00a0', ' ')                          # non-breaking space
    # Strip any remaining non-latin1 characters
    clean = clean.encode('latin-1', errors='replace').decode('latin-1')
    for line in clean.split('\n'):
        pdf.multi_cell(0, 5, line)
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
                   save_cv: bool = False, url_extractor=None) -> str:
    """Handle file upload, URL, or text paste. Priority: file > URL > text."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file = request.files.get(file_field)

    # --- 1. File upload (highest priority) ---
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower()
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(temp_path)
        try:
            text = extract_text_from_file(temp_path)
            if save_cv:
                save_name = f'cv_{timestamp}.{ext}'
                shutil.copy2(temp_path, os.path.join(CV_STORAGE, save_name))
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
                    save_name = f'cv_{timestamp}.pdf'
                    _text_to_pdf(text, os.path.join(CV_STORAGE, save_name))
                return text
            else:
                flash('Could not extract content from the URL. Please paste text instead.', 'warning')
                return ''

    # --- 3. Pasted text (lowest priority) ---
    text = request.form.get(text_field, '').strip()
    if text and save_cv:
        save_name = f'cv_{timestamp}.pdf'
        _text_to_pdf(text, os.path.join(CV_STORAGE, save_name))
    return text


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


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
    # Ensure https in production (Railway reverse proxy)
    if redirect_uri.startswith('http://') and 'railway.app' in redirect_uri:
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
    return redirect(next_url or url_for('index'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/analyze', methods=['POST'])
def analyze():
    consent_given = request.form.get('cv_consent') == 'yes'

    try:
        cv_text = _process_input(
            'cv_file', 'cv_text', url_field='cv_url',
            save_cv=consent_given, url_extractor=_extract_from_linkedin_url)
        jd_text = _process_input(
            'jd_file', 'jd_text', url_field='jd_url',
            save_cv=False, url_extractor=_extract_from_jd_url)
    except Exception as e:
        flash(f'Error reading input: {e}', 'error')
        return redirect(url_for('index'))

    if not cv_text or not jd_text:
        if not cv_text and not jd_text:
            flash('Please provide both a CV and a Job Description.', 'error')
        elif not cv_text:
            flash('Could not get CV content. Please try uploading a file or pasting text.', 'error')
        else:
            flash('Could not get JD content. Please try uploading a file or pasting text.', 'error')
        return redirect(url_for('index'))

    if len(jd_text.split()) < 10:
        flash('Job description seems very short. Results may be unreliable.', 'warning')

    try:
        results = analyze_cv_against_jd(cv_text, jd_text)
    except Exception as e:
        logger.error('Analysis error: %s', e, exc_info=True)
        flash(f'Analysis error: {e}', 'error')
        return redirect(url_for('index'))

    # Store CV text + JD text + analysis data server-side (too large for cookie session)
    analysis_data = {
        'cv_text': cv_text[:20000],
        'jd_text': jd_text[:15000],
        'analysis_results': {
            'ats_score': results.get('ats_score', 0),
            'matched': results.get('skill_match', {}).get('matched', [])[:20],
            'missing': results.get('skill_match', {}).get('missing', [])[:20],
            'missing_verbs': results.get('experience_analysis', {}).get('missing_action_verbs', [])[:10],
            'skill_score': results.get('skill_match', {}).get('skill_score', 0),
        },
    }
    session['_data_token'] = _save_session_data(analysis_data)

    # Track usage for signed-in users
    if _oauth_enabled and session.get('user_id'):
        try:
            track_analysis(session['user_id'])
        except Exception:
            pass  # non-critical

    return render_template('results.html', results=results)


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
        return redirect(url_for('index'))

    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cv_download.pdf')
    _text_to_pdf(cv_text, pdf_path)
    return send_file(pdf_path, as_attachment=True, download_name='my_cv.pdf')


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
        return redirect(url_for('index'))

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
                           missing_count=len(analysis.get('missing', [])))


@app.route('/rewrite-cv', methods=['POST'])
def rewrite_cv_action():
    """Perform the rewrite — deduct credits, call LLM, show results."""
    if not session.get('user_id'):
        return redirect(url_for('login_page'))

    data = _load_session_data(session.get('_data_token', ''))
    if not data.get('cv_text') or not data.get('jd_text'):
        flash('No analysis data found. Please run analysis first.', 'warning')
        return redirect(url_for('index'))

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
        return redirect(url_for('index'))

    # Store rewritten CV server-side for download
    token = session.get('_data_token', '')
    session['_data_token'] = _update_session_data(token, {
        'rewritten_cv': rewrite_result['rewritten_cv'],
    })

    return render_template('rewrite_results.html',
                           rewrite=rewrite_result,
                           original_ats=analysis.get('ats_score', 0),
                           credits_remaining=user.credits if user else 0)


@app.route('/download-rewritten-cv')
def download_rewritten_cv():
    """Download the rewritten CV as a PDF."""
    data = _load_session_data(session.get('_data_token', ''))
    rewritten_text = data.get('rewritten_cv', '')
    if not rewritten_text:
        flash('No rewritten CV available. Please perform a rewrite first.', 'warning')
        return redirect(url_for('index'))

    # Convert markdown to plain text for PDF (strip markdown formatting)
    import re as regex
    clean_text = rewritten_text
    clean_text = regex.sub(r'^##\s+', '', clean_text, flags=regex.MULTILINE)  # ## headers → plain
    clean_text = regex.sub(r'\*\*(.+?)\*\*', r'\1', clean_text)  # **bold** → plain
    clean_text = regex.sub(r'^\-\s+', '  - ', clean_text, flags=regex.MULTILINE)  # - bullets → indented

    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'rewritten_cv.pdf')
    _text_to_pdf(clean_text, pdf_path)
    return send_file(pdf_path, as_attachment=True, download_name='rewritten_cv.pdf')


# ---------------------------------------------------------------------------
# Credit purchase & payment routes
# ---------------------------------------------------------------------------

@app.route('/buy-credits')
def buy_credits():
    if not session.get('user_id'):
        session['_login_next'] = url_for('buy_credits')
        flash('Please sign in to buy credits.', 'warning')
        return redirect(url_for('login_page'))

    from payments import TIERS, PAYMENTS_ENABLED, RAZORPAY_KEY_ID
    user = User.query.get(session['user_id'])
    return render_template('buy_credits.html',
                           tiers=TIERS,
                           payments_enabled=PAYMENTS_ENABLED,
                           razorpay_key=RAZORPAY_KEY_ID,
                           user=user)


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
# Admin endpoints — protected by ADMIN_TOKEN
# ---------------------------------------------------------------------------

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
    files = sorted(os.listdir(CV_STORAGE), reverse=True)
    files = [f for f in files if not f.startswith('.')]
    file_info = []
    for f in files:
        path = os.path.join(CV_STORAGE, f)
        size_kb = round(os.path.getsize(path) / 1024, 1)
        file_info.append({'name': f, 'size_kb': size_kb})
    return render_template('admin_cvs.html', files=file_info, token=token)


@app.route('/admin/cvs/download/<filename>')
def download_cv(filename):
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return 'Unauthorized', 401
    filename = secure_filename(filename)
    filepath = os.path.join(CV_STORAGE, filename)
    if not os.path.isfile(filepath):
        return 'File not found', 404
    return send_file(filepath, as_attachment=True)


@app.route('/admin/cvs/download-all')
def download_all_cvs():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return 'Unauthorized', 401
    files = [f for f in os.listdir(CV_STORAGE) if not f.startswith('.')]
    if not files:
        return 'No CVs stored yet', 404
    zip_path = os.path.join(tempfile.gettempdir(), 'all_cvs')
    shutil.make_archive(zip_path, 'zip', CV_STORAGE)
    return send_file(zip_path + '.zip', as_attachment=True,
                     download_name='collected_cvs.zip')


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
    files = sorted(os.listdir(CV_STORAGE), reverse=True)
    files = [f for f in files if not f.startswith('.')]
    return jsonify({'files': files})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(debug=True, port=port)
