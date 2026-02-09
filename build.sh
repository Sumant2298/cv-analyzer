#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python -m spacy download en_core_web_sm

# Download NLTK data — try platform-specific path, fall back to default
NLTK_DIR="${NLTK_DATA:-/opt/render/project/src/nltk_data}"
mkdir -p "$NLTK_DIR" 2>/dev/null || true
python -c "
import nltk, os
d = os.environ.get('NLTK_DATA', '$NLTK_DIR')
try:
    os.makedirs(d, exist_ok=True)
    nltk.download('stopwords', download_dir=d)
    nltk.download('punkt_tab', download_dir=d)
except Exception:
    # Fall back to default location
    nltk.download('stopwords')
    nltk.download('punkt_tab')
"
