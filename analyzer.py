import os
import re
from collections import Counter

import nltk
import spacy
from rake_nltk import Rake
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from skills_data import SKILL_CATEGORIES

# Ensure NLTK can find data on Render and locally
_nltk_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nltk_data')
if os.path.isdir(_nltk_path):
    nltk.data.path.insert(0, _nltk_path)
_render_nltk = '/opt/render/project/src/nltk_data'
if os.path.isdir(_render_nltk):
    nltk.data.path.insert(0, _render_nltk)

nlp = spacy.load("en_core_web_sm")


def analyze_cv_against_jd(cv_text: str, jd_text: str) -> dict:
    """Run full analysis pipeline. Returns structured results dict."""
    cv_clean = preprocess(cv_text)
    jd_clean = preprocess(jd_text)

    jd_keywords = extract_keywords(jd_clean)
    jd_skills = extract_known_skills(jd_text)

    cv_keywords = extract_keywords(cv_clean)
    cv_skills = extract_known_skills(cv_text)

    tfidf_score = calculate_tfidf_score(cv_clean, jd_clean)
    skill_match = compute_skill_match(cv_skills, jd_skills)
    experience_analysis = analyze_experience_relevance(cv_text, jd_text)

    # Composite score: 40% TF-IDF + 40% skill match + 20% verb alignment
    skill_score = skill_match.get('skill_score', 0)
    verb_score = experience_analysis.get('verb_alignment', 0)
    composite = round(tfidf_score * 0.4 + skill_score * 0.4 + verb_score * 0.2, 1)

    suggestions = generate_suggestions(skill_match, composite, experience_analysis)

    return {
        'composite_score': composite,
        'tfidf_score': tfidf_score,
        'jd_keywords': jd_keywords,
        'cv_keywords': cv_keywords,
        'jd_skills': _sets_to_lists(jd_skills),
        'cv_skills': _sets_to_lists(cv_skills),
        'skill_match': _serialize_skill_match(skill_match),
        'experience_analysis': experience_analysis,
        'suggestions': suggestions,
    }


# ---------------------------------------------------------------------------
# Text preprocessing
# ---------------------------------------------------------------------------

def preprocess(text: str) -> str:
    """Normalize text for NLP processing."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s\+\#\/\.\-]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ---------------------------------------------------------------------------
# Keyword extraction (RAKE + spaCy noun chunks)
# ---------------------------------------------------------------------------

def extract_keywords(text: str) -> list[dict]:
    """Extract ranked keywords using RAKE + spaCy noun chunks."""
    rake = Rake(min_length=1, max_length=3)
    rake.extract_keywords_from_text(text)
    rake_phrases = rake.get_ranked_phrases_with_scores()

    doc = nlp(text)
    noun_chunks = [chunk.text.strip() for chunk in doc.noun_chunks
                   if len(chunk.text.strip()) > 2]
    chunk_counts = Counter(noun_chunks)

    keyword_scores: dict[str, dict] = {}
    for score, phrase in rake_phrases[:50]:
        keyword_scores[phrase] = {'rake_score': score, 'frequency': 0}
    for chunk, count in chunk_counts.items():
        if chunk in keyword_scores:
            keyword_scores[chunk]['frequency'] = count
        else:
            keyword_scores[chunk] = {'rake_score': 0, 'frequency': count}

    results = []
    for phrase, scores in keyword_scores.items():
        combined = scores['rake_score'] * 0.6 + scores['frequency'] * 0.4
        results.append({'phrase': phrase, 'score': round(combined, 2)})
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:30]


# ---------------------------------------------------------------------------
# Known skill matching against taxonomy
# ---------------------------------------------------------------------------

def extract_known_skills(text: str) -> dict[str, set]:
    """Match text against known skill taxonomy. Returns categorized matches."""
    text_lower = text.lower()
    found: dict[str, set] = {}
    for category, skills in SKILL_CATEGORIES.items():
        matched = set()
        for skill in skills:
            if len(skill) <= 2:
                # For very short skills (R, C, Go), require stronger boundaries
                pattern = r'(?<![a-z])' + re.escape(skill) + r'(?![a-z])'
            else:
                pattern = r'\b' + re.escape(skill) + r'\b'
            if re.search(pattern, text_lower):
                matched.add(skill)
        if matched:
            found[category] = matched
    return found


# ---------------------------------------------------------------------------
# TF-IDF cosine similarity
# ---------------------------------------------------------------------------

def calculate_tfidf_score(cv_text: str, jd_text: str) -> float:
    """Calculate cosine similarity between CV and JD using TF-IDF vectors."""
    vectorizer = TfidfVectorizer(
        stop_words='english',
        ngram_range=(1, 2),
        max_features=5000,
        sublinear_tf=True,
    )
    try:
        tfidf_matrix = vectorizer.fit_transform([jd_text, cv_text])
        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        return round(similarity * 100, 1)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Skill gap analysis
# ---------------------------------------------------------------------------

def compute_skill_match(cv_skills: dict[str, set], jd_skills: dict[str, set]) -> dict:
    """Compare CV skills against JD skills. Identify matches and gaps."""
    all_jd = set()
    all_cv = set()
    for skills in jd_skills.values():
        all_jd.update(skills)
    for skills in cv_skills.values():
        all_cv.update(skills)

    matched = all_jd & all_cv
    missing = all_jd - all_cv
    extra = all_cv - all_jd

    category_breakdown = {}
    for category, jd_cat_skills in jd_skills.items():
        cv_cat_skills = cv_skills.get(category, set())
        cat_matched = jd_cat_skills & cv_cat_skills
        cat_missing = jd_cat_skills - cv_cat_skills
        cat_score = (len(cat_matched) / len(jd_cat_skills) * 100) if jd_cat_skills else 0
        category_breakdown[category] = {
            'matched': cat_matched,
            'missing': cat_missing,
            'score': round(cat_score, 1),
        }

    skill_score = (len(matched) / len(all_jd) * 100) if all_jd else 0

    return {
        'matched': matched,
        'missing': missing,
        'extra': extra,
        'skill_score': round(skill_score, 1),
        'category_breakdown': category_breakdown,
    }


# ---------------------------------------------------------------------------
# Experience relevance analysis
# ---------------------------------------------------------------------------

AUXILIARY_VERBS = {'be', 'have', 'do', 'will', 'would', 'can', 'could',
                   'shall', 'should', 'may', 'might', 'must'}


def analyze_experience_relevance(cv_text: str, jd_text: str) -> dict:
    """Analyze whether CV experience aligns with JD requirements."""
    jd_doc = nlp(jd_text.lower())
    cv_doc = nlp(cv_text.lower())

    cv_verbs = {token.lemma_ for token in cv_doc
                if token.pos_ == 'VERB' and token.lemma_ not in AUXILIARY_VERBS}
    jd_verbs = {token.lemma_ for token in jd_doc
                if token.pos_ == 'VERB' and token.lemma_ not in AUXILIARY_VERBS}

    verb_overlap = cv_verbs & jd_verbs
    verb_alignment = (len(verb_overlap) / len(jd_verbs) * 100) if jd_verbs else 0

    experience_sections = _extract_experience_sections(cv_text)

    section_relevance = []
    for section_name, section_text in experience_sections:
        if not section_text.strip():
            continue
        try:
            vectorizer = TfidfVectorizer(stop_words='english')
            matrix = vectorizer.fit_transform([jd_text.lower(), section_text.lower()])
            sim = cosine_similarity(matrix[0:1], matrix[1:2])[0][0]
            section_relevance.append({
                'section': section_name,
                'relevance': round(sim * 100, 1),
            })
        except ValueError:
            pass

    return {
        'verb_alignment': round(verb_alignment, 1),
        'common_action_verbs': sorted(verb_overlap)[:15],
        'missing_action_verbs': sorted(jd_verbs - cv_verbs)[:10],
        'section_relevance': section_relevance,
    }


def _extract_experience_sections(cv_text: str) -> list[tuple[str, str]]:
    """Split CV into named sections based on common headers."""
    pattern = (
        r'\b(experience|work\s+experience|professional\s+experience|'
        r'employment|work\s+history|projects|education|skills|'
        r'certifications|summary|objective|profile|qualifications|'
        r'achievements|awards|publications|interests)\b'
    )
    parts = re.split(pattern, cv_text, flags=re.IGNORECASE)

    sections = []
    i = 1
    while i < len(parts) - 1:
        header = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ''
        sections.append((header, content))
        i += 2

    if not sections:
        sections.append(('Full CV', cv_text))

    return sections


# ---------------------------------------------------------------------------
# Suggestion generation
# ---------------------------------------------------------------------------

def generate_suggestions(skill_match: dict, composite_score: float,
                         experience_analysis: dict) -> list[str]:
    """Generate actionable improvement suggestions."""
    suggestions = []

    if composite_score < 30:
        suggestions.append(
            'Your CV has low overall relevance to this JD. Consider '
            'tailoring your CV significantly for this role, focusing on '
            'the specific requirements mentioned in the job description.'
        )
    elif composite_score < 60:
        suggestions.append(
            'Your CV has moderate relevance. Focus on incorporating more '
            'JD-specific terminology and highlighting relevant experience.'
        )

    missing = skill_match.get('missing', set())
    if missing:
        missing_list = ', '.join(sorted(missing)[:10])
        suggestions.append(
            f'Add these missing skills/keywords to your CV if you have '
            f'experience with them: {missing_list}.'
        )

    for category, data in skill_match.get('category_breakdown', {}).items():
        if data['score'] < 50 and data['missing']:
            nice_category = category.replace('_', ' ').title()
            missing_in_cat = ', '.join(sorted(data['missing']))
            suggestions.append(
                f'{nice_category}: You are missing {missing_in_cat}. '
                f'Consider adding relevant experience or projects.'
            )

    if experience_analysis.get('verb_alignment', 0) < 40:
        missing_verbs = experience_analysis.get('missing_action_verbs', [])
        if missing_verbs:
            verb_list = ', '.join(missing_verbs[:5])
            suggestions.append(
                f'Consider using action verbs that match the JD: {verb_list}. '
                f'These indicate the type of work expected in this role.'
            )

    for section in experience_analysis.get('section_relevance', []):
        if section['relevance'] < 20:
            suggestions.append(
                f'Your "{section["section"]}" section has low relevance '
                f'({section["relevance"]}%) to this JD. Consider '
                f'rewriting it to emphasize relevant experience.'
            )

    if not suggestions:
        suggestions.append(
            'Your CV appears well-aligned with this JD. '
            'Ensure formatting is clean and proofread carefully.'
        )

    return suggestions


# ---------------------------------------------------------------------------
# Serialization helpers (convert sets to sorted lists for templates)
# ---------------------------------------------------------------------------

def _sets_to_lists(skills_dict: dict[str, set]) -> dict[str, list]:
    return {k: sorted(v) for k, v in skills_dict.items()}


def _serialize_skill_match(skill_match: dict) -> dict:
    result = {
        'matched': sorted(skill_match.get('matched', set())),
        'missing': sorted(skill_match.get('missing', set())),
        'extra': sorted(skill_match.get('extra', set())),
        'skill_score': skill_match.get('skill_score', 0),
        'category_breakdown': {},
    }
    for cat, data in skill_match.get('category_breakdown', {}).items():
        result['category_breakdown'][cat] = {
            'matched': sorted(data.get('matched', set())),
            'missing': sorted(data.get('missing', set())),
            'score': data.get('score', 0),
        }
    return result
