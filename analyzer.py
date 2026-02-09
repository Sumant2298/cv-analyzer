import os
import re
from collections import Counter

import nltk
import spacy
from rake_nltk import Rake
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from skills_data import SKILL_CATEGORIES

# ---------------------------------------------------------------------------
# Skill example bullet points for actionable suggestions
# ---------------------------------------------------------------------------

SKILL_EXAMPLES = {
    # Programming Languages
    'python': 'Built data processing pipeline in Python handling 1M+ records daily with 99.8% accuracy',
    'java': 'Developed high-throughput Java microservice processing 5K requests/sec with sub-100ms latency',
    'javascript': 'Implemented interactive JavaScript features reducing user task completion time by 35%',
    'typescript': 'Migrated legacy JavaScript codebase to TypeScript, eliminating 200+ runtime type errors',
    'c++': 'Optimized C++ rendering engine achieving 2x performance improvement on complex 3D scenes',
    'go': 'Built concurrent Go service handling 10K simultaneous WebSocket connections with minimal memory footprint',
    'rust': 'Rewrote critical path in Rust reducing memory usage by 60% while maintaining zero-crash uptime',
    'ruby': 'Developed Ruby automation scripts reducing manual data entry by 15 hours per week',
    'scala': 'Implemented Scala-based data pipeline processing 500GB daily on Apache Spark cluster',
    'swift': 'Built native iOS app in Swift with 4.8-star App Store rating and 50K+ downloads',
    'kotlin': 'Developed Android app in Kotlin with offline-first architecture serving 100K+ users',
    'php': 'Optimized PHP backend reducing page load times from 3s to 800ms for e-commerce platform',
    'r': 'Conducted statistical analysis in R across 10M+ data points informing $2M marketing strategy',
    'sql': 'Wrote complex SQL queries and stored procedures optimizing report generation by 70%',
    # Web Frameworks
    'react': 'Developed responsive React dashboard with 15+ interactive components serving 10K+ daily users',
    'angular': 'Built enterprise Angular application with lazy-loaded modules reducing initial bundle size by 45%',
    'vue': 'Created Vue.js single-page application with real-time data visualization for analytics platform',
    'django': 'Architected Django REST API serving 50+ endpoints with comprehensive test coverage of 92%',
    'flask': 'Built Flask microservice with JWT authentication handling 2K concurrent API requests',
    'express': 'Developed Express.js API gateway routing traffic across 8 microservices with circuit breaker patterns',
    'spring': 'Implemented Spring Boot microservices with OAuth2 security serving 1M+ API calls/day',
    'node.js': 'Built real-time Node.js server supporting 5K concurrent WebSocket connections for live collaboration',
    'next.js': 'Developed Next.js application with SSR improving SEO scores from 45 to 95 on Google Lighthouse',
    # Databases
    'mongodb': 'Designed MongoDB schema with sharding strategy handling 500M+ documents with sub-50ms queries',
    'postgresql': 'Optimized PostgreSQL queries reducing average response time from 2s to 200ms',
    'mysql': 'Managed MySQL database cluster with master-slave replication achieving 99.99% uptime',
    'redis': 'Implemented Redis caching layer reducing API response times by 80% and database load by 60%',
    'elasticsearch': 'Built Elasticsearch search engine indexing 10M+ documents with sub-second full-text search',
    # Cloud & DevOps
    'aws': 'Architected cloud infrastructure on AWS (EC2, S3, Lambda) supporting 99.9% uptime SLA',
    'azure': 'Migrated on-premise infrastructure to Azure reducing hosting costs by 40%',
    'gcp': 'Deployed ML models on GCP with auto-scaling serving 100K+ predictions per day',
    'docker': 'Containerized 12 microservices using Docker reducing deployment time by 60%',
    'kubernetes': 'Deployed microservices on Kubernetes clusters managing 50+ pods with zero-downtime rolling updates',
    'terraform': 'Managed infrastructure-as-code using Terraform across 3 cloud environments with drift detection',
    'jenkins': 'Built Jenkins CI/CD pipeline automating testing and deployment for 20+ repositories',
    'ci/cd': 'Implemented CI/CD pipeline with GitHub Actions reducing release cycle from 2 weeks to daily deploys',
    'ansible': 'Automated server provisioning with Ansible playbooks managing 100+ production nodes',
    # Data & ML
    'machine learning': 'Trained and deployed ML classification model achieving 94% accuracy on production data',
    'tensorflow': 'Built TensorFlow deep learning model for image classification with 96% validation accuracy',
    'pytorch': 'Implemented PyTorch NLP model for sentiment analysis processing 50K reviews/hour',
    'pandas': 'Performed data analysis using Pandas on 5M+ row datasets delivering weekly business insights',
    'spark': 'Built Apache Spark ETL pipeline processing 1TB+ data daily with 99.5% job success rate',
    'tableau': 'Created Tableau dashboards tracking 25+ KPIs used by C-suite for quarterly business reviews',
    # Soft Skills
    'leadership': 'Led cross-functional team of 8 engineers delivering project 2 weeks ahead of schedule',
    'communication': 'Presented technical architecture proposals to non-technical stakeholders securing $500K budget approval',
    'agile': 'Facilitated Agile ceremonies for 3 scrum teams delivering 95% of sprint commitments consistently',
    'project management': 'Managed end-to-end delivery of 5 concurrent projects with combined budget of $1.2M',
    # Tools
    'git': 'Established Git branching strategy and code review workflows for team of 15 developers',
    'jira': 'Configured Jira workflows and dashboards improving sprint velocity tracking and team visibility',
    # Testing
    'selenium': 'Built Selenium test automation framework covering 500+ test cases reducing QA cycle by 70%',
    'jest': 'Implemented Jest test suite with 95% code coverage across 200+ React components',
    'pytest': 'Developed pytest-based testing framework with fixtures and parametrized tests covering 300+ scenarios',
    # Security
    'oauth': 'Implemented OAuth 2.0 authentication flow with PKCE supporting SSO across 5 enterprise applications',
    'jwt': 'Designed JWT-based stateless authentication system handling 10K+ concurrent sessions securely',
}


def _generate_skill_example(skill: str) -> str:
    """Generate a realistic resume bullet point example for a given skill."""
    skill_lower = skill.lower()
    if skill_lower in SKILL_EXAMPLES:
        return SKILL_EXAMPLES[skill_lower]
    # Generic but still actionable template
    return f'Implemented {skill} in [project context], resulting in [measurable outcome]'

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

    suggestions = generate_suggestions(skill_match, composite, experience_analysis, jd_text)

    # Quick match summary: experience, education, skills, location
    cv_years = extract_years_of_experience(cv_text)
    jd_years = extract_years_of_experience(jd_text)
    cv_edu = extract_education_level(cv_text)
    jd_edu = extract_education_level(jd_text)
    cv_loc = extract_location(cv_text)
    jd_loc = extract_location(jd_text)

    matched_count = len(skill_match.get('matched', set()))
    total_jd_skills = matched_count + len(skill_match.get('missing', set()))

    quick_match = {
        'experience': compare_experience(cv_years, jd_years),
        'education': compare_education(cv_edu, jd_edu),
        'skills': {
            'cv_value': f'{matched_count}/{total_jd_skills} match',
            'jd_value': f'{total_jd_skills} required',
            'match_quality': ('Strong Match' if skill_score >= 70
                              else 'Good Match' if skill_score >= 40
                              else 'Weak Match'),
        },
        'location': compare_location(cv_loc, jd_loc),
    }

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
        'quick_match': quick_match,
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

    # Compute extra skills grouped by category
    extra_by_category = {}
    for category, cv_cat_skills in cv_skills.items():
        jd_cat_skills = jd_skills.get(category, set())
        cat_extra = cv_cat_skills - jd_cat_skills
        if cat_extra:
            extra_by_category[category] = cat_extra

    skill_score = (len(matched) / len(all_jd) * 100) if all_jd else 0

    return {
        'matched': matched,
        'missing': missing,
        'extra': extra,
        'skill_score': round(skill_score, 1),
        'category_breakdown': category_breakdown,
        'extra_by_category': extra_by_category,
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
# Quick match extraction: experience, education, location
# ---------------------------------------------------------------------------

EDUCATION_HIERARCHY = [
    ('PhD', [r'\bph\.?d\.?\b', r'\bdoctorate\b', r'\bdoctoral\b']),
    ('Masters', [r"\bmaster(?:'?s)?\b", r'\bm\.?s\.?\b(?!\s*office)',
                 r'\bm\.?a\.?\b', r'\bmba\b', r'\bm\.?sc\.?\b', r'\bm\.?eng\.?\b']),
    ('Bachelors', [r"\bbachelor(?:'?s)?\b", r'\bb\.?s\.?\b', r'\bb\.?a\.?\b',
                   r'\bb\.?sc\.?\b', r'\bb\.?eng\.?\b', r'\bundergraduate\b']),
    ('Associate', [r"\bassociate(?:'?s)?\s+degree\b", r'\ba\.?s\.?\b', r'\ba\.?a\.?\b']),
    ('Diploma', [r'\bdiploma\b', r'\bcertificate\b', r'\bcertification\b']),
]


def extract_years_of_experience(text: str) -> int | None:
    """Extract years of experience from text using regex patterns."""
    patterns = [
        r'(\d+)\+?\s*(?:-\s*\d+)?\s*years?\s*(?:of\s+)?(?:experience|expertise|work)',
        r'(?:minimum|at least|min\.?)\s*(\d+)\s*years?',
        r'(\d+)\+?\s*years?\s+(?:in|of|working)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def extract_education_level(text: str) -> str | None:
    """Extract the highest education level mentioned in text."""
    text_lower = text.lower()
    for level_name, patterns in EDUCATION_HIERARCHY:
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return level_name
    return None


def extract_location(text: str) -> str | None:
    """Extract location from text using regex patterns and spaCy NER."""
    # Priority 1: Explicit location patterns
    explicit_patterns = [
        r'(?:location|based in|located in|headquarters?)[:\s]+([A-Z][a-zA-Z\s,]+?)(?:\n|\.|\||$)',
        r'(?:city|region)[:\s]+([A-Z][a-zA-Z\s,]+?)(?:\n|\.|\||$)',
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text)
        if match:
            loc = match.group(1).strip().rstrip(',')
            if 2 < len(loc) < 60:
                return loc

    # Priority 2: Remote / hybrid / on-site keywords
    remote_patterns = [
        (r'\bfully?\s+remote\b', 'Remote'),
        (r'\bremote\s+(?:work|position|role|opportunity)\b', 'Remote'),
        (r'\bwork\s+(?:from\s+)?(?:home|anywhere)\b', 'Remote'),
        (r'\bhybrid\b', 'Hybrid'),
        (r'\bon[\-\s]?site\b', 'On-site'),
    ]
    for pattern, label in remote_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return label

    # Priority 3: spaCy NER for GPE entities
    doc = nlp(text[:3000])  # Limit text length for performance
    for ent in doc.ents:
        if ent.label_ == 'GPE' and len(ent.text) > 2:
            return ent.text
    return None


def compare_experience(cv_years: int | None, jd_years: int | None) -> dict:
    """Compare experience years between CV and JD."""
    cv_display = f'{cv_years} years' if cv_years else 'Not specified'
    jd_display = f'{jd_years}+ years' if jd_years else 'Not specified'

    if jd_years is None:
        quality = 'Good Match'
    elif cv_years is None:
        quality = 'Weak Match'
    elif cv_years >= jd_years:
        quality = 'Strong Match'
    elif cv_years >= jd_years - 1:
        quality = 'Good Match'
    else:
        quality = 'Weak Match'

    return {'cv_value': cv_display, 'jd_value': jd_display, 'match_quality': quality}


def compare_education(cv_edu: str | None, jd_edu: str | None) -> dict:
    """Compare education levels between CV and JD."""
    level_order = [lev[0] for lev in EDUCATION_HIERARCHY]  # PhD, Masters, Bachelors, ...

    cv_display = cv_edu if cv_edu else 'Not specified'
    jd_display = jd_edu if jd_edu else 'Not specified'

    if jd_edu is None:
        quality = 'Good Match'
    elif cv_edu is None:
        quality = 'Weak Match'
    else:
        cv_idx = level_order.index(cv_edu) if cv_edu in level_order else 99
        jd_idx = level_order.index(jd_edu) if jd_edu in level_order else 99
        # Lower index = higher degree (PhD=0, Masters=1, ...)
        if cv_idx <= jd_idx:
            quality = 'Strong Match'
        elif cv_idx == jd_idx + 1:
            quality = 'Good Match'
        else:
            quality = 'Weak Match'

    return {'cv_value': cv_display, 'jd_value': jd_display, 'match_quality': quality}


def compare_location(cv_loc: str | None, jd_loc: str | None) -> dict:
    """Compare locations between CV and JD."""
    cv_display = cv_loc if cv_loc else 'Not specified'
    jd_display = jd_loc if jd_loc else 'Not specified'

    if jd_loc is None and cv_loc is None:
        quality = 'Good Match'
    elif jd_loc and jd_loc.lower() in ('remote', 'work from home', 'work from anywhere'):
        quality = 'Strong Match'
    elif cv_loc is None or jd_loc is None:
        quality = 'Good Match'
    elif cv_loc.lower() in jd_loc.lower() or jd_loc.lower() in cv_loc.lower():
        quality = 'Strong Match'
    else:
        quality = 'Weak Match'

    return {'cv_value': cv_display, 'jd_value': jd_display, 'match_quality': quality}


# ---------------------------------------------------------------------------
# Suggestion generation
# ---------------------------------------------------------------------------

def generate_suggestions(skill_match: dict, composite_score: float,
                         experience_analysis: dict, jd_text: str = '') -> list[dict]:
    """Generate actionable improvement suggestions with examples."""
    suggestions = []

    # General score-based advice
    if composite_score < 30:
        suggestions.append({
            'type': 'general',
            'title': 'Low Overall Relevance',
            'body': 'Your CV has low overall relevance to this job description. '
                    'Consider tailoring your CV significantly for this role.',
            'examples': [
                'Rewrite your summary to directly address the role requirements',
                'Mirror the exact terminology used in the job description',
                'Move your most relevant experience to the top of each section',
            ],
            'priority': 'high',
        })
    elif composite_score < 60:
        suggestions.append({
            'type': 'general',
            'title': 'Moderate Match — Room for Improvement',
            'body': 'Your CV has moderate relevance. Focus on incorporating more '
                    'JD-specific terminology and quantifying your achievements.',
            'examples': [
                'Add specific metrics: numbers, percentages, dollar amounts to your bullet points',
                'Use the same keywords the job description uses instead of synonyms',
            ],
            'priority': 'medium',
        })

    # Missing skills with example bullet points
    missing = skill_match.get('missing', set())
    if missing:
        missing_sorted = sorted(missing)[:10]
        examples = [_generate_skill_example(s) for s in missing_sorted[:3]]
        suggestions.append({
            'type': 'missing_skills',
            'title': 'Add Missing Skills to Your CV',
            'body': f'Your CV is missing {len(missing)} skill(s) mentioned in the JD: '
                    f'{", ".join(missing_sorted)}. Add them with concrete examples.',
            'examples': examples,
            'priority': 'high' if len(missing) > 5 else 'medium',
        })

    # Weak category suggestions
    for category, data in skill_match.get('category_breakdown', {}).items():
        if data['score'] < 50 and data['missing']:
            nice_category = category.replace('_', ' ').title()
            cat_missing = sorted(data['missing'])
            examples = [_generate_skill_example(s) for s in cat_missing[:2]]
            suggestions.append({
                'type': 'weak_category',
                'title': f'Strengthen {nice_category}',
                'body': f'You\'re missing {", ".join(cat_missing)} in {nice_category}. '
                        f'Add relevant experience or projects demonstrating these skills.',
                'examples': examples,
                'priority': 'high' if data['score'] < 25 else 'medium',
            })

    # Action verb suggestions
    if experience_analysis.get('verb_alignment', 0) < 40:
        missing_verbs = experience_analysis.get('missing_action_verbs', [])
        if missing_verbs:
            examples = [
                f'Instead of "Worked on X", write "{verb.capitalize()}d [specific project] '
                f'resulting in [measurable outcome]"'
                for verb in missing_verbs[:3]
            ]
            suggestions.append({
                'type': 'missing_verbs',
                'title': 'Use Stronger Action Verbs',
                'body': f'Your CV is missing key action verbs from the JD: '
                        f'{", ".join(missing_verbs[:5])}. Start bullet points with these verbs.',
                'examples': examples,
                'priority': 'medium',
            })

    # Low section relevance
    for section in experience_analysis.get('section_relevance', []):
        if section['relevance'] < 20:
            suggestions.append({
                'type': 'low_relevance',
                'title': f'Rewrite Your "{section["section"].title()}" Section',
                'body': f'This section has only {section["relevance"]}% relevance to the JD. '
                        f'It needs significant rework to align with the role requirements.',
                'examples': [
                    'Add quantifiable metrics: "Reduced API response time by 40% through query optimization"',
                    'Mirror JD language: use the exact same terminology the job description uses',
                    'Lead each bullet with a strong action verb followed by a specific achievement',
                ],
                'priority': 'high' if section['relevance'] < 10 else 'medium',
            })

    # Positive feedback if no issues
    if not suggestions:
        suggestions.append({
            'type': 'positive',
            'title': 'Great Match!',
            'body': 'Your CV appears well-aligned with this job description. '
                    'Focus on polishing the details.',
            'examples': [
                'Ensure consistent formatting and no typos',
                'Quantify achievements wherever possible for maximum impact',
                'Tailor your summary/objective to mention the company by name',
            ],
            'priority': 'low',
        })

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
        'matched_by_category': {},
        'missing_by_category': {},
        'extra_by_category': {},
    }
    for cat, data in skill_match.get('category_breakdown', {}).items():
        cat_matched = sorted(data.get('matched', set()))
        cat_missing = sorted(data.get('missing', set()))
        result['category_breakdown'][cat] = {
            'matched': cat_matched,
            'missing': cat_missing,
            'score': data.get('score', 0),
        }
        if cat_matched:
            result['matched_by_category'][cat] = cat_matched
        if cat_missing:
            result['missing_by_category'][cat] = cat_missing

    for cat, skills in skill_match.get('extra_by_category', {}).items():
        result['extra_by_category'][cat] = sorted(skills)

    return result
