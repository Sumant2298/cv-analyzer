import os
import tempfile

from flask import Flask, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from analyzer import analyze_cv_against_jd

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()

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


def extract_text_from_input(file_field: str, text_field: str) -> str:
    """Try file upload first, then fall back to pasted text."""
    file = request.files.get(file_field)
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        try:
            text = extract_text_from_file(filepath)
        finally:
            os.remove(filepath)
        return text
    return request.form.get(text_field, '').strip()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        cv_text = extract_text_from_input('cv_file', 'cv_text')
        jd_text = extract_text_from_input('jd_file', 'jd_text')
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(debug=True, port=port)
