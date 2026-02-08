import os
import shutil
import tempfile
from datetime import datetime

from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   send_file, url_for)
from werkzeug.utils import secure_filename

from analyzer import analyze_cv_against_jd

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()

# Folder to store consented CVs
CV_STORAGE = os.environ.get('CV_STORAGE_PATH',
                            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'collected_cvs'))
os.makedirs(CV_STORAGE, exist_ok=True)

# Admin token for accessing stored CVs (set via env var on Render)
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'change-me-in-production')

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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
    """Convert plain text to a PDF file."""
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Helvetica', size=10)
    for line in text.split('\n'):
        pdf.multi_cell(0, 5, line)
    pdf.output(output_path)


def _process_input(file_field: str, text_field: str, save_cv: bool) -> str:
    """Handle file upload or text paste for a single input.

    1. Save uploaded file to temp dir once.
    2. Extract text from the saved file.
    3. If save_cv is True, copy the file to CV_STORAGE.
    4. Clean up temp file.

    For text-only input, extract text directly and optionally
    convert to PDF for storage.

    Returns extracted text.
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file = request.files.get(file_field)

    # --- File upload path ---
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower()
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(temp_path)

        try:
            # Extract text from the saved temp file
            text = extract_text_from_file(temp_path)

            # If consent given, copy the original file to storage
            if save_cv:
                save_name = f'cv_{timestamp}.{ext}'
                save_path = os.path.join(CV_STORAGE, save_name)
                shutil.copy2(temp_path, save_path)
        finally:
            os.remove(temp_path)

        return text

    # --- Pasted text path ---
    text = request.form.get(text_field, '').strip()
    if text and save_cv:
        save_name = f'cv_{timestamp}.pdf'
        save_path = os.path.join(CV_STORAGE, save_name)
        _text_to_pdf(text, save_path)

    return text


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    consent_given = request.form.get('cv_consent') == 'yes'

    try:
        cv_text = _process_input('cv_file', 'cv_text', save_cv=consent_given)
        jd_text = _process_input('jd_file', 'jd_text', save_cv=False)
    except Exception as e:
        flash(f'Error reading file: {e}')
        return redirect(url_for('index'))

    if not cv_text or not jd_text:
        flash('Please provide both a CV and a Job Description.')
        return redirect(url_for('index'))

    if len(jd_text.split()) < 10:
        flash('Job description seems very short. Results may be unreliable.')

    try:
        results = analyze_cv_against_jd(cv_text, jd_text)
    except Exception as e:
        flash(f'Analysis error: {e}')
        return redirect(url_for('index'))

    return render_template('results.html', results=results)


# ---------------------------------------------------------------------------
# Admin endpoints — protected by ADMIN_TOKEN
# ---------------------------------------------------------------------------

@app.route('/admin/cvs')
def list_cvs():
    """List all stored CVs (requires ?token=...)."""
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
    """Download a single stored CV (requires ?token=...)."""
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
    """Download all stored CVs as a zip (requires ?token=...)."""
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


@app.route('/api/cvs')
def api_list_cvs():
    """JSON API to list stored CVs (for sync script)."""
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return jsonify({'error': 'Unauthorized'}), 401

    files = sorted(os.listdir(CV_STORAGE), reverse=True)
    files = [f for f in files if not f.startswith('.')]
    return jsonify({'files': files})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(debug=True, port=port)
