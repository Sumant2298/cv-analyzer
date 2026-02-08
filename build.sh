#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python -m spacy download en_core_web_sm

# Download NLTK data to a known location inside the project
mkdir -p /opt/render/project/src/nltk_data
python -c "import nltk; nltk.download('stopwords', download_dir='/opt/render/project/src/nltk_data'); nltk.download('punkt_tab', download_dir='/opt/render/project/src/nltk_data')"
