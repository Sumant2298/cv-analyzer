"""Local NLP analysis for CV quality scoring — no LLM needed.

Provides section detection, formatting checks, action verb analysis,
quantification scoring, skill extraction, and composite CV quality scoring.
Used by Tier 1 (CV-only analysis) to minimise LLM token consumption.
"""

import logging
import re
from collections import Counter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy NLTK initialisation
# ---------------------------------------------------------------------------
_nltk_ready = False


def _ensure_nltk():
    global _nltk_ready
    if _nltk_ready:
        return
    try:
        import nltk
        # Try to use punkt_tab first, fall back to punkt
        try:
            nltk.data.find('tokenizers/punkt_tab')
        except LookupError:
            try:
                nltk.download('punkt_tab', quiet=True)
            except Exception:
                nltk.download('punkt', quiet=True)
        try:
            nltk.data.find('taggers/averaged_perceptron_tagger_eng')
        except LookupError:
            try:
                nltk.download('averaged_perceptron_tagger_eng', quiet=True)
            except Exception:
                nltk.download('averaged_perceptron_tagger', quiet=True)
        try:
            nltk.data.find('corpora/stopwords')
        except LookupError:
            nltk.download('stopwords', quiet=True)
        _nltk_ready = True
    except Exception as e:
        logger.warning('NLTK init failed: %s', e)
        _nltk_ready = True  # Don't retry endlessly


# ---------------------------------------------------------------------------
# Section Detection
# ---------------------------------------------------------------------------

_SECTION_PATTERNS = {
    'Summary': r'(?i)^[\s#*]*(?:summary|profile|objective|professional\s+summary|career\s+summary|about\s+me|overview)[\s&/|,\-—]*\w*\s*$',
    'Experience': r'(?i)^[\s#*]*(?:experience|work\s+experience|employment|professional\s+experience|work\s+history|career\s+history)[\s&/|,\-—]*\w*\s*$',
    'Education': r'(?i)^[\s#*]*(?:education|academic|qualifications|degrees?|academic\s+background)(?:[\s&/|,\-—]+\w+)*\s*$',
    'Skills': r'(?i)^[\s#*]*(?:skills|technical\s+skills|core\s+competencies|technologies|tech\s+stack|proficiencies|key\s+skills)[\s&/|,\-—]*\w*\s*$',
    'Projects': r'(?i)^[\s#*]*(?:projects|personal\s+projects|key\s+projects|portfolio|side\s+projects)[\s&/|,\-—]*\w*\s*$',
    'Certifications': r'(?i)^[\s#*]*(?:certifications?|licenses?|credentials?|professional\s+certifications?)[\s&/|,\-—]*\w*\s*$',
    'Awards': r'(?i)^[\s#*]*(?:awards?|honors?|achievements?|recognition|accomplishments?)(?:[\s&/|,\-—]+\w+)*\s*$',
    'Publications': r'(?i)^[\s#*]*(?:publications?|papers?|research)[\s&/|,\-—]*\w*\s*$',
    'Hobbies': r'(?i)^[\s#*]*(?:hobbies|interests|activities|extracurricular)[\s&/|,\-—]*\w*\s*$',
    'Volunteer': r'(?i)^[\s#*]*(?:volunteer(?:ing)?|community|social\s+service)[\s&/|,\-—]*\w*\s*$',
    'Contact': r'(?i)^[\s#*]*(?:contact\s*(?:info|information|details)?|personal\s*(?:info|details|information)?)[\s&/|,\-—]*\w*\s*$',
}

_ESSENTIAL_SECTIONS = {'Summary', 'Experience', 'Education', 'Skills'}
_RECOMMENDED_SECTIONS = {'Projects', 'Certifications'}


def detect_sections(cv_text: str) -> dict:
    """Detect standard CV sections using regex patterns."""
    lines = cv_text.split('\n')
    sections_found = []
    section_details = {}
    current_section = None
    current_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 80:
            continue

        for section_name, pattern in _SECTION_PATTERNS.items():
            if re.match(pattern, stripped):
                # Close previous section
                if current_section:
                    section_details[current_section]['end_line'] = i - 1
                    section_details[current_section]['line_count'] = i - current_start

                if section_name not in sections_found:
                    sections_found.append(section_name)
                    section_details[section_name] = {
                        'start_line': i,
                        'end_line': len(lines) - 1,
                        'line_count': 0,
                    }
                    current_section = section_name
                    current_start = i
                break

    # Close last section
    if current_section and current_section in section_details:
        section_details[current_section]['end_line'] = len(lines) - 1
        section_details[current_section]['line_count'] = len(lines) - current_start

    all_known = set(_SECTION_PATTERNS.keys())
    sections_missing = [s for s in _ESSENTIAL_SECTIONS | _RECOMMENDED_SECTIONS
                        if s not in sections_found]

    return {
        'sections_found': sections_found,
        'sections_missing': sections_missing,
        'section_details': section_details,
        'section_count': len(sections_found),
        'has_summary': 'Summary' in sections_found,
        'has_experience': 'Experience' in sections_found,
        'has_education': 'Education' in sections_found,
        'has_skills': 'Skills' in sections_found,
    }


# ---------------------------------------------------------------------------
# Contact Info Extraction
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
_PHONE_RE = re.compile(r'(\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}')
_LINKEDIN_RE = re.compile(r'linkedin\.com/in/[\w-]+', re.I)
_GITHUB_RE = re.compile(r'github\.com/[\w-]+', re.I)
_WEBSITE_RE = re.compile(r'https?://(?!linkedin|github)[\w.-]+\.\w+')

# Patterns that indicate a line is NOT a name (contact info, headers, etc.)
_NOT_NAME_RE = re.compile(
    r'(?i)(?:@|http|www\.|\.com|phone|email|address|linkedin|github'
    r'|resume|curriculum|vitae|cv\b|page\b|objective|summary|experience'
    r'|education|skills|projects?|certifications?|references?)',
)


def extract_candidate_name(cv_text: str) -> str:
    """Extract candidate name from the first few lines of CV text.

    Heuristic: the name is typically the first non-empty line in the top
    10 lines that contains 1-5 alphabetic words, is not a section header,
    and does not contain contact info patterns.
    """
    lines = cv_text.split('\n')[:10]
    for line in lines:
        stripped = line.strip().strip('#*_- \t')
        if not stripped or len(stripped) < 2:
            continue
        # Skip lines with contact info or section headers
        if _NOT_NAME_RE.search(stripped):
            continue
        # Skip lines that are mostly numbers (phone etc.)
        alpha_chars = sum(1 for c in stripped if c.isalpha())
        if alpha_chars < len(stripped) * 0.5:
            continue
        # Name should be 1-5 words, each mostly alphabetic
        words = stripped.split()
        if 1 <= len(words) <= 5:
            all_alpha = all(
                sum(1 for c in w if c.isalpha()) >= len(w) * 0.7
                for w in words
            )
            if all_alpha:
                # Title-case the name
                return ' '.join(w.capitalize() if w.islower() else w for w in words)
    return ''


# ---------------------------------------------------------------------------
# Section Descriptions (static fallbacks for missing sections)
# ---------------------------------------------------------------------------

_SECTION_DESCRIPTIONS = {
    'Summary': 'A brief professional overview that positions your candidacy and highlights key strengths.',
    'Experience': 'Your work history with accomplishments, responsibilities, and impact at each role.',
    'Education': 'Academic qualifications, degrees, and relevant coursework or honors.',
    'Skills': 'Technical and professional competencies that demonstrate your capabilities.',
    'Projects': 'Hands-on work that showcases initiative, technical depth, and problem-solving.',
    'Certifications': 'Professional credentials that validate specialized knowledge and commitment to growth.',
    'Awards': 'Recognition and honors that demonstrate excellence and peer acknowledgment.',
    'Publications': 'Research papers, articles, or technical writing that establish thought leadership.',
    'Hobbies': 'Personal interests that add dimension to your profile and show cultural fit.',
    'Volunteer': 'Community contributions that demonstrate leadership and social responsibility.',
    'Contact': 'Your reachability information — email, phone, LinkedIn, and other professional links.',
}


def extract_contact_info(cv_text: str) -> dict:
    """Extract contact information using regex."""
    # Only search first ~30 lines (contact is usually at top)
    top = '\n'.join(cv_text.split('\n')[:30])

    fields = {
        'email': bool(_EMAIL_RE.search(top)),
        'phone': bool(_PHONE_RE.search(top)),
        'linkedin': bool(_LINKEDIN_RE.search(top)),
        'github': bool(_GITHUB_RE.search(top)),
        'website': bool(_WEBSITE_RE.search(top)),
    }

    # Weighted score: email & phone are most important
    weights = {'email': 30, 'phone': 25, 'linkedin': 25, 'github': 10, 'website': 10}
    score = sum(weights[k] for k, v in fields.items() if v)

    return {
        **{k: 'found' if v else 'missing' for k, v in fields.items()},
        'completeness_score': score,
    }


# ---------------------------------------------------------------------------
# Formatting Score
# ---------------------------------------------------------------------------

def _extract_bullets(cv_text: str) -> list[str]:
    """Extract lines that look like bullet points."""
    bullets = []
    for line in cv_text.split('\n'):
        stripped = line.strip()
        if re.match(r'^[\u2022\u2023\u25E6\u25AA\u25AB*\-\u2013\u2014]\s', stripped):
            bullets.append(stripped)
        elif re.match(r'^\d+[.)]\s', stripped):
            bullets.append(stripped)
    return bullets


def compute_formatting_score(cv_text: str, sections: dict) -> dict:
    """Assess CV formatting quality."""
    words = cv_text.split()
    word_count = len(words)
    lines = cv_text.split('\n')
    bullets = _extract_bullets(cv_text)
    bullet_count = len(bullets)

    issues = []
    strengths = []

    # Section presence (key 4 sections)
    found_essential = sum(1 for s in _ESSENTIAL_SECTIONS
                          if s in sections.get('sections_found', []))

    if found_essential == 4:
        strengths.append('All essential sections present (Summary, Experience, Education, Skills)')
    elif found_essential >= 2:
        missing = [s for s in _ESSENTIAL_SECTIONS if s not in sections.get('sections_found', [])]
        issues.append(f'Missing sections: {", ".join(missing)}')
    else:
        issues.append('CV is missing most standard sections — add Summary, Experience, Education, Skills')

    # Word count
    if 300 <= word_count <= 1200:
        strengths.append(f'CV length is within ideal range ({word_count} words)')
    elif word_count < 200:
        issues.append(f'CV is very short ({word_count} words) — aim for 300-800 words')
    elif word_count > 1500:
        issues.append(f'CV is very long ({word_count} words) — consider trimming to under 1200 words')

    # Bullet points
    if bullet_count >= 10:
        strengths.append(f'Good use of bullet points ({bullet_count} bullets)')
    elif bullet_count >= 5:
        strengths.append(f'Reasonable bullet usage ({bullet_count} bullets)')
    elif bullet_count < 3:
        issues.append('Very few bullet points — use bullets to list achievements and responsibilities')

    # Bullet length
    if bullets:
        avg_bullet_words = sum(len(b.split()) for b in bullets) / len(bullets)
        long_bullets = sum(1 for b in bullets if len(b.split()) > 30)
        if long_bullets > 3:
            issues.append(f'{long_bullets} bullet points exceed 30 words — be more concise')
    else:
        avg_bullet_words = 0

    # Long lines (wall of text)
    long_lines = sum(1 for l in lines if len(l.strip()) > 120)
    if long_lines > 5:
        issues.append('Several very long lines — break text into shorter, readable chunks')

    # Compute score
    score = 0
    # Sections: max 35
    score += min(35, found_essential * 8 + sections.get('section_count', 0) * 1)
    # Length: max 20
    if 300 <= word_count <= 1200:
        score += 20
    elif 200 <= word_count <= 1500:
        score += 12
    else:
        score += 5
    # Bullets: max 25
    score += min(25, bullet_count * 2)
    # Readability: max 20
    readability = 20
    if long_lines > 5:
        readability -= 5
    if long_bullets if bullets else 0 > 3:
        readability -= 5
    score += max(0, readability)

    return {
        'formatting_score': min(100, score),
        'word_count': word_count,
        'bullet_count': bullet_count,
        'avg_bullet_length': round(avg_bullet_words, 1),
        'issues': issues,
        'strengths': strengths,
    }


# ---------------------------------------------------------------------------
# Action Verb Analysis
# ---------------------------------------------------------------------------

STRONG_VERBS = {
    'achieved', 'architected', 'accelerated', 'automated', 'built', 'championed',
    'consolidated', 'coordinated', 'created', 'decreased', 'delivered', 'designed',
    'developed', 'directed', 'drove', 'eliminated', 'enabled', 'engineered',
    'enhanced', 'established', 'exceeded', 'executed', 'expanded', 'forged',
    'generated', 'grew', 'headed', 'implemented', 'improved', 'increased',
    'influenced', 'initiated', 'innovated', 'integrated', 'introduced', 'launched',
    'led', 'maximized', 'mentored', 'migrated', 'modernized', 'negotiated',
    'optimized', 'orchestrated', 'overhauled', 'pioneered', 'produced',
    'propelled', 'reduced', 'refactored', 'resolved', 'revamped', 'scaled',
    'secured', 'simplified', 'spearheaded', 'streamlined', 'strengthened',
    'surpassed', 'transformed', 'unified', 'upgraded',
}

WEAK_VERBS = {
    'assisted', 'contributed', 'dealt', 'did', 'got', 'had', 'handled',
    'helped', 'involved', 'liaised', 'made', 'managed', 'oversaw',
    'participated', 'performed', 'provided', 'responsible', 'served',
    'supported', 'used', 'utilized', 'was', 'went', 'worked',
}

_VERB_REPLACEMENTS = {
    'managed': ['orchestrated', 'directed', 'led'],
    'worked': ['engineered', 'developed', 'delivered'],
    'helped': ['enabled', 'facilitated', 'drove'],
    'handled': ['executed', 'resolved', 'streamlined'],
    'responsible': ['owned', 'spearheaded', 'led'],
    'used': ['leveraged', 'employed', 'implemented'],
    'utilized': ['leveraged', 'applied', 'implemented'],
    'assisted': ['supported', 'enabled', 'contributed to'],
    'participated': ['contributed', 'collaborated', 'engaged'],
    'made': ['created', 'built', 'developed'],
    'did': ['executed', 'completed', 'delivered'],
    'oversaw': ['directed', 'managed', 'orchestrated'],
}


def analyze_action_verbs(cv_text: str) -> dict:
    """Analyse action verbs in CV bullet points."""
    bullets = _extract_bullets(cv_text)
    strong_found = []
    weak_found = []
    suggestions = []

    for bullet in bullets:
        # Get first 1-3 words
        clean = re.sub(r'^[\u2022\u2023\u25E6\u25AA\u25AB*\-\u2013\u2014\d.)\s]+', '', bullet)
        first_words = clean.lower().split()[:3]

        for word in first_words:
            word_clean = word.strip('.,;:')
            if word_clean in STRONG_VERBS and word_clean not in strong_found:
                strong_found.append(word_clean)
                break
            elif word_clean in WEAK_VERBS and word_clean not in weak_found:
                weak_found.append(word_clean)
                replacements = _VERB_REPLACEMENTS.get(word_clean)
                if replacements:
                    snippet = clean[:50] + ('...' if len(clean) > 50 else '')
                    suggestions.append(
                        f'Replace \'{word_clean}\' in "{snippet}" with '
                        f'\'{replacements[0]}\' or \'{replacements[1]}\''
                    )
                break

    total = len(bullets) or 1
    strong_ratio = len(strong_found) / total
    weak_ratio = len(weak_found) / total

    # Score: 100 if all strong, 0 if all weak
    score = int(min(100, max(0, (strong_ratio * 100) + ((1 - weak_ratio) * 30))))
    # Cap at reasonable levels
    if not bullets:
        score = 20
    elif len(strong_found) == 0:
        score = min(score, 30)

    return {
        'action_verb_score': min(100, score),
        'strong_verbs_found': strong_found[:15],
        'weak_verbs_found': weak_found[:15],
        'strong_verb_count': len(strong_found),
        'weak_verb_count': len(weak_found),
        'total_bullets_analyzed': len(bullets),
        'suggestions': suggestions[:5],
    }


# ---------------------------------------------------------------------------
# Quantification Check
# ---------------------------------------------------------------------------

_METRICS_RE = re.compile(
    r'\d+\s*%'           # percentages
    r'|\$\s*[\d,.]+'     # dollar amounts
    r'|\u20b9\s*[\d,.]+'  # rupee amounts
    r'|\d+[KMBkmb]\b'    # scale: 5K, 2M
    r'|\d+\s*(?:users?|customers?|clients?|employees?|people|members?|teams?'
    r'|transactions?|requests?|servers?|endpoints?|projects?|repos?|applications?'
    r'|databases?|queries|records|rows|documents?|pages?|orders?|daily|monthly'
    r'|annually|weekly|x\b)',
    re.I
)


def check_quantification(cv_text: str) -> dict:
    """Check how many bullet points contain metrics/numbers."""
    bullets = _extract_bullets(cv_text)
    with_metrics = 0
    metric_examples = []

    for bullet in bullets:
        matches = _METRICS_RE.findall(bullet)
        if matches:
            with_metrics += 1
            if len(metric_examples) < 5:
                metric_examples.append(matches[0].strip())

    total = len(bullets) or 1
    ratio = with_metrics / total
    score = int(min(100, ratio * 150))  # 67% with metrics = 100

    if not bullets:
        suggestion = 'Add bullet points with quantified achievements to strengthen your CV.'
    elif ratio < 0.3:
        suggestion = (f'Only {int(ratio * 100)}% of your bullet points contain metrics. '
                      f'Aim for 50%+ — add numbers, percentages, and scale indicators.')
    elif ratio < 0.5:
        suggestion = (f'{int(ratio * 100)}% of bullets have metrics — good start. '
                      f'Try to quantify more achievements.')
    else:
        suggestion = f'Strong quantification — {int(ratio * 100)}% of bullets contain metrics.'

    return {
        'quantification_score': score,
        'bullets_with_metrics': with_metrics,
        'bullets_without_metrics': len(bullets) - with_metrics,
        'total_bullets': len(bullets),
        'metric_examples': metric_examples,
        'suggestion': suggestion,
    }


# ---------------------------------------------------------------------------
# Keyword / Skill Extraction
# ---------------------------------------------------------------------------

def extract_keywords(text: str, top_n: int = 20) -> list[dict]:
    """Extract keywords using RAKE algorithm."""
    _ensure_nltk()
    keywords = []
    try:
        from rake_nltk import Rake
        r = Rake(min_length=1, max_length=3)
        r.extract_keywords_from_text(text)
        ranked = r.get_ranked_phrases_with_scores()
        for score, phrase in ranked[:top_n]:
            keywords.append({'phrase': phrase, 'score': round(score, 2)})
    except Exception as e:
        logger.warning('RAKE extraction failed: %s', e)
        # Fallback: simple word frequency
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        from collections import Counter
        common = Counter(words).most_common(top_n)
        for word, count in common:
            keywords.append({'phrase': word, 'score': count})

    return keywords


def extract_skills_from_cv(cv_text: str) -> dict:
    """Extract skills by fuzzy matching against known skill categories."""
    from skills_data import SKILL_CATEGORIES, ALL_KNOWN_SKILLS

    cv_lower = cv_text.lower()
    skills_found = []
    by_category = {}
    category_coverage = {}

    # Direct matching first (faster)
    for category, skill_set in SKILL_CATEGORIES.items():
        matched = []
        for skill in skill_set:
            # Word boundary check to avoid partial matches
            pattern = r'\b' + re.escape(skill) + r'\b'
            if re.search(pattern, cv_lower):
                matched.append(skill.title() if len(skill) > 3 else skill.upper())
        by_category[category] = matched
        category_coverage[category] = len(matched)
        skills_found.extend(matched)

    # Fuzzy matching for skills not caught by exact match
    try:
        from rapidfuzz import fuzz, process
        # Extract potential skill phrases from CV (1-3 word sequences)
        words = cv_lower.split()
        potential = set()
        for i in range(len(words)):
            for n in range(1, 4):
                if i + n <= len(words):
                    phrase = ' '.join(words[i:i+n])
                    if 2 < len(phrase) < 40:
                        potential.add(phrase)

        for phrase in potential:
            for skill in ALL_KNOWN_SKILLS:
                if skill.lower() in [s.lower() for s in skills_found]:
                    continue
                score = fuzz.ratio(phrase, skill)
                if score >= 85 and skill.lower() != phrase:
                    display = skill.title() if len(skill) > 3 else skill.upper()
                    if display not in skills_found:
                        skills_found.append(display)
                        # Find category
                        for cat, cat_skills in SKILL_CATEGORIES.items():
                            if skill in cat_skills:
                                by_category.setdefault(cat, []).append(display)
                                category_coverage[cat] = len(by_category[cat])
                                break
    except ImportError:
        pass  # rapidfuzz not available, skip fuzzy matching

    return {
        'skills_found': skills_found,
        'by_category': by_category,
        'total_skills': len(skills_found),
        'category_coverage': category_coverage,
    }


def quick_ats_score(cv_text: str, jd_text: str) -> dict:
    """Fast keyword-based ATS score (no LLM).

    Extracts skills from both CV and JD using the skill dictionary,
    then computes overlap percentage. Also uses RAKE keywords as fallback.

    Returns dict with: score (0-100), matched_skills, missing_skills.
    """
    cv_skills = extract_skills_from_cv(cv_text)
    jd_skills = extract_skills_from_cv(jd_text)

    cv_skill_set = set(s.lower() for s in cv_skills.get('skills_found', []))
    jd_skill_set = set(s.lower() for s in jd_skills.get('skills_found', []))

    if jd_skill_set:
        matched = cv_skill_set & jd_skill_set
        missing = jd_skill_set - cv_skill_set
        score = min(100, int(len(matched) / max(len(jd_skill_set), 1) * 100))
        return {
            'score': score,
            'matched_skills': [s.title() for s in sorted(matched)][:10],
            'missing_skills': [s.title() for s in sorted(missing)][:10],
        }

    # Fallback: use RAKE keywords from JD
    try:
        from rake_nltk import Rake
        _ensure_nltk()
        rake = Rake(min_length=1, max_length=3)
        rake.extract_keywords_from_text(jd_text)
        jd_keywords = set(kw.lower() for kw in rake.get_ranked_phrases()[:30])
        cv_lower = cv_text.lower()
        matched_kw = [kw for kw in jd_keywords if kw in cv_lower]
        missing_kw = [kw for kw in jd_keywords if kw not in cv_lower]
        score = min(100, int(len(matched_kw) / max(len(jd_keywords), 1) * 100))
        return {
            'score': score,
            'matched_skills': [kw.title() for kw in matched_kw[:10]],
            'missing_skills': [kw.title() for kw in missing_kw[:10]],
        }
    except (ImportError, Exception):
        # Last resort: simple word overlap
        jd_words = set(w.lower() for w in jd_text.split() if len(w) > 3)
        cv_words = set(w.lower() for w in cv_text.split() if len(w) > 3)
        overlap = jd_words & cv_words
        score = min(100, int(len(overlap) / max(len(jd_words), 1) * 100))
        return {'score': score, 'matched_skills': [], 'missing_skills': []}


# ---------------------------------------------------------------------------
# CV Quality Score (Composite)
# ---------------------------------------------------------------------------

def compute_cv_quality_score(
    formatting: dict,
    contact: dict,
    sections: dict,
    verbs: dict,
    quantification: dict,
    skills: dict,
) -> tuple[int, list]:
    """Compute weighted composite CV quality score.

    Returns (score, breakdown) where breakdown matches the format
    used by the ATS breakdown in results templates.
    """
    # Section structure: 25%
    found = sections.get('section_count', 0)
    essential = sum(1 for s in _ESSENTIAL_SECTIONS
                    if s in sections.get('sections_found', []))
    section_score = min(100, essential * 20 + min(found, 8) * 5)

    # Formatting quality: 20%
    fmt_score = formatting.get('formatting_score', 50)

    # Action verb quality: 15%
    verb_score = verbs.get('action_verb_score', 30)

    # Quantification: 15%
    quant_score = quantification.get('quantification_score', 20)

    # Contact completeness: 10%
    contact_score = contact.get('completeness_score', 30)

    # Skills diversity: 10%
    total_skills = skills.get('total_skills', 0)
    categories_covered = sum(1 for v in skills.get('category_coverage', {}).values() if v > 0)
    skill_div_score = min(100, total_skills * 5 + categories_covered * 10)

    # Length appropriateness: 5%
    wc = formatting.get('word_count', 0)
    if 300 <= wc <= 1000:
        length_score = 100
    elif 200 <= wc <= 1500:
        length_score = 70
    elif 100 <= wc <= 2000:
        length_score = 40
    else:
        length_score = 15

    # Weighted composite
    weights = [
        ('section_structure', 'Section Structure', section_score, 0.25),
        ('formatting_quality', 'Formatting Quality', fmt_score, 0.20),
        ('action_verbs', 'Action Verb Quality', verb_score, 0.15),
        ('quantification', 'Quantification', quant_score, 0.15),
        ('contact_info', 'Contact Completeness', contact_score, 0.10),
        ('skills_diversity', 'Skills Diversity', skill_div_score, 0.10),
        ('length', 'Length Appropriateness', length_score, 0.05),
    ]

    composite = sum(score * weight for _, _, score, weight in weights)
    composite = int(min(100, max(0, round(composite))))

    breakdown = []
    for key, label, score, weight in weights:
        rationale = _generate_rationale(key, score, formatting, contact,
                                         sections, verbs, quantification, skills)
        breakdown.append({
            'key': key,
            'label': label,
            'score': score,
            'weight': int(weight * 100),
            'weighted': round(score * weight, 1),
            'rationale': rationale,
        })

    return composite, breakdown


def _generate_rationale(key: str, score: int, formatting: dict, contact: dict,
                        sections: dict, verbs: dict, quantification: dict,
                        skills: dict) -> str:
    """Generate a short rationale for each breakdown component."""
    if key == 'section_structure':
        found = sections.get('sections_found', [])
        missing = [s for s in _ESSENTIAL_SECTIONS if s not in found]
        if not missing:
            return f'All essential sections present ({len(found)} total sections detected)'
        return f'Missing: {", ".join(missing)}. {len(found)} sections detected.'

    if key == 'formatting_quality':
        bc = formatting.get('bullet_count', 0)
        wc = formatting.get('word_count', 0)
        return f'{bc} bullet points, {wc} words. ' + (
            formatting['issues'][0] if formatting.get('issues') else
            formatting['strengths'][0] if formatting.get('strengths') else
            'Formatting is acceptable.')

    if key == 'action_verbs':
        sc = verbs.get('strong_verb_count', 0)
        wc = verbs.get('weak_verb_count', 0)
        if sc > wc:
            return f'{sc} strong verbs vs {wc} weak verbs — good verb usage'
        elif wc > 0:
            return f'{wc} weak verbs found (e.g., {", ".join(verbs.get("weak_verbs_found", [])[:3])}). Replace with stronger alternatives.'
        return f'{sc} strong action verbs detected'

    if key == 'quantification':
        wm = quantification.get('bullets_with_metrics', 0)
        total = quantification.get('total_bullets', 0)
        return f'{wm}/{total} bullet points contain metrics. ' + quantification.get('suggestion', '')

    if key == 'contact_info':
        missing = [k for k in ['email', 'phone', 'linkedin'] if contact.get(k) == 'missing']
        if not missing:
            return 'Email, phone, and LinkedIn all present'
        return f'Missing: {", ".join(missing)}'

    if key == 'skills_diversity':
        total = skills.get('total_skills', 0)
        cats = sum(1 for v in skills.get('category_coverage', {}).values() if v > 0)
        return f'{total} skills across {cats} categories detected'

    if key == 'length':
        wc = formatting.get('word_count', 0)
        if 300 <= wc <= 1000:
            return f'{wc} words — ideal CV length'
        elif wc < 300:
            return f'{wc} words — too short, aim for 300-800 words'
        return f'{wc} words — consider trimming for conciseness'

    return ''


# ---------------------------------------------------------------------------
# Text Statistics
# ---------------------------------------------------------------------------

def compute_text_stats(cv_text: str) -> dict:
    """Basic text statistics."""
    words = cv_text.split()
    sentences = re.split(r'[.!?]+', cv_text)
    sentences = [s.strip() for s in sentences if s.strip()]

    word_count = len(words)
    sentence_count = len(sentences)
    avg_sentence_length = round(word_count / max(sentence_count, 1), 1)
    page_estimate = round(word_count / 500, 1)

    return {
        'word_count': word_count,
        'sentence_count': sentence_count,
        'avg_sentence_length': avg_sentence_length,
        'page_estimate': page_estimate,
        'line_count': len(cv_text.split('\n')),
    }


# ---------------------------------------------------------------------------
# Master Function
# ---------------------------------------------------------------------------

def analyze_cv_standalone(cv_text: str) -> dict:
    """Run all local NLP analysis on a CV. Returns template-ready dict."""
    _ensure_nltk()

    candidate_name = extract_candidate_name(cv_text)
    sections = detect_sections(cv_text)
    contact = extract_contact_info(cv_text)
    formatting = compute_formatting_score(cv_text, sections)
    verbs = analyze_action_verbs(cv_text)
    quantification = check_quantification(cv_text)
    keywords = extract_keywords(cv_text, top_n=20)
    skills = extract_skills_from_cv(cv_text)
    text_stats = compute_text_stats(cv_text)

    cv_quality_score, quality_breakdown = compute_cv_quality_score(
        formatting, contact, sections, verbs, quantification, skills
    )

    # Build section descriptions: LLM will override found sections,
    # static descriptions used for missing sections
    section_descriptions = {}
    for sec in sections.get('sections_found', []):
        section_descriptions[sec] = _SECTION_DESCRIPTIONS.get(sec, '')
    for sec in sections.get('sections_missing', []):
        section_descriptions[sec] = _SECTION_DESCRIPTIONS.get(sec, '')

    return {
        'cv_quality_score': cv_quality_score,
        'quality_breakdown': quality_breakdown,
        'candidate_name': candidate_name,
        'sections': sections,
        'section_descriptions': section_descriptions,
        'contact': contact,
        'formatting': formatting,
        'verbs': verbs,
        'quantification': quantification,
        'keywords': keywords,
        'skills': skills,
        'text_stats': text_stats,
    }
