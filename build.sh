#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -c "import nltk; nltk.download('stopwords'); nltk.download('punkt_tab')"
