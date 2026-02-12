"""LLM-powered CV analysis — Google Gemini 2.5 Flash.

Primary LLM: Gemini 2.5 Flash via Google AI Studio (OpenAI-compatible endpoint)
  - 1M token context window, 65K max output tokens
  - $0.30/1M input, $2.50/1M output tokens
  - Excellent structured JSON output

Four LLM calls (three for CV+JD analysis, one lightweight for CV-only):
  0. CV-only review (Tier 1 — uses NLP + small LLM call)
  1. Skills & scoring (Tier 2 — structured extraction)
  2. Recruiter insights (Tier 2 — narrative feedback)
  3. CV rewrite (Tier 3 — on-demand, paid)
"""

import json
import logging
import os
import time
import urllib.parse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Configuration — Google Gemini
# ---------------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')

# Provider list (single provider — Gemini)
_PROVIDERS = []

if GEMINI_API_KEY:
    _PROVIDERS.append({
        'name': 'gemini',
        'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai/',
        'api_key': GEMINI_API_KEY,
        'model': GEMINI_MODEL,
        'max_context': 1048576,  # 1M tokens
    })

# Determine if backend is available
LLM_ENABLED = bool(_PROVIDERS)

if _PROVIDERS:
    logger.info('LLM backend: Gemini (%s)', GEMINI_MODEL)
if not LLM_ENABLED:
    logger.warning('No LLM backend configured — set GEMINI_API_KEY')

# Cache OpenAI clients per provider (lazy init)
_clients = {}


def _get_provider_client(provider: dict):
    """Lazy-initialise an OpenAI-compatible client for a provider."""
    name = provider['name']
    if name in _clients:
        return _clients[name]

    from openai import OpenAI
    client = OpenAI(
        base_url=provider['base_url'],
        api_key=provider['api_key'],
    )
    _clients[name] = client
    logger.info('Initialised %s client', name)
    return client


def _is_rate_limit_error(error) -> bool:
    """Check if an error is a rate limit / quota exceeded error."""
    err_str = str(error).lower()
    return any(keyword in err_str for keyword in [
        'rate_limit', 'rate limit', '429', 'quota', 'too many requests',
        'tokens per minute', 'requests per minute', 'requests per day',
        'resource_exhausted', 'capacity', 'overloaded', 'server_error',
        'service_unavailable', '503', '502', 'timeout', 'timed out',
    ])


def _parse_raw_json(raw: str) -> dict:
    """Strip markdown fences if present, then parse JSON."""
    raw = raw.strip()
    if raw.startswith('```'):
        lines = raw.split('\n')
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        raw = '\n'.join(lines).strip()
    return json.loads(raw)


def _call_provider(provider: dict, system: str, prompt: str,
                   max_tokens: int, temperature: float, timeout: float) -> str:
    """Call LLM provider via OpenAI-compatible API and return raw response text."""
    client = _get_provider_client(provider)

    response = client.chat.completions.create(
        model=provider['model'],
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={'type': 'json_object'},
        timeout=timeout,
    )
    return response.choices[0].message.content


def _call_llm(system: str, prompt: str, max_tokens: int = 3000,
              temperature: float = 0.3, timeout: float = 120.0,
              _retries: int = 2) -> dict:
    """Call Gemini LLM with retry on failure.

    Retries up to _retries times on JSON validation failures.
    On rate limit errors, waits and retries with exponential backoff.
    """
    if not _PROVIDERS:
        raise RuntimeError('No LLM backend configured — set GEMINI_API_KEY')

    provider = _PROVIDERS[0]  # Gemini
    name = provider['name']
    last_error = None

    for attempt in range(_retries + 1):
        try:
            # Decrease temperature on retry for more deterministic JSON
            retry_temp = max(temperature - 0.1 * attempt, 0.1)
            retry_system = system
            if attempt > 0:
                retry_system = (system +
                    '\n\nREMINDER: Output ONLY a valid JSON object. '
                    'Do NOT output any CV or JD text.')
                logger.info('[%s] retry %d/%d (temp=%.1f)',
                            name, attempt, _retries, retry_temp)

            t0 = time.time()
            raw = _call_provider(provider, retry_system, prompt,
                                 max_tokens, retry_temp, timeout)
            elapsed = time.time() - t0

            logger.info('[%s] response in %.1fs: %d chars (attempt %d)',
                        name, elapsed, len(raw), attempt)

            return _parse_raw_json(raw)

        except Exception as e:
            last_error = e
            error_str = str(e)

            # JSON parse failure → retry with lower temp
            if ('json' in error_str.lower() or
                    'Expecting' in error_str or
                    'json_validate_failed' in error_str or
                    'failed_generation' in error_str):
                logger.warning('[%s] JSON parse failed (attempt %d/%d): %s',
                               name, attempt + 1, _retries + 1, error_str[:200])
                if attempt < _retries:
                    time.sleep(1)
                    continue

            # Rate limit → exponential backoff retry
            if _is_rate_limit_error(e):
                wait_time = 5 * (attempt + 1)  # 5s, 10s, 15s
                logger.warning('[%s] rate limited (attempt %d/%d), waiting %ds: %s',
                               name, attempt + 1, _retries + 1, wait_time, error_str[:200])
                if attempt < _retries:
                    time.sleep(wait_time)
                    continue

            # Other error → retry once
            logger.warning('[%s] error (attempt %d/%d): %s',
                           name, attempt + 1, _retries + 1, error_str[:200])
            if attempt < _retries:
                time.sleep(2)
                continue

    raise RuntimeError(f'Gemini LLM failed after {_retries + 1} attempts: {str(last_error)[:200]}')


# ---------------------------------------------------------------------------
# Call 1: Skills & Scoring
# ---------------------------------------------------------------------------

# [7h] Stronger JSON enforcement + [7e] alias mappings
_SKILLS_SYSTEM = """You are an ATS (Applicant Tracking System) JSON API. You analyse CVs against job descriptions and return ONLY structured JSON.

CRITICAL RULES:
- Your response must be a single valid JSON object. Nothing else.
- Your output must parse with json.loads(). No trailing commas, no comments, no extra text.
- All numeric scores must be integers (not strings). Example: "score": 55, NOT "score": "55".
- All string values must be properly escaped. No literal newlines inside strings.
- NEVER output any text from the CV or JD in your response — only structured analysis.
- NEVER echo, quote, or reproduce the CV content. Only reference it in short rationale strings.
- If you start writing CV text instead of JSON, STOP and restart with the JSON object.
- Be thorough: check skill aliases and abbreviations:
  JS=JavaScript, TS=TypeScript, K8s=Kubernetes, Postgres=PostgreSQL, Mongo=MongoDB,
  GCP=Google Cloud Platform, ML=Machine Learning, DL=Deep Learning, NLP=Natural Language Processing,
  CI/CD=Continuous Integration/Deployment, OOP=Object-Oriented Programming, REST=RESTful API,
  React.js=React, Node.js=Node, Next.js=NextJS, Vue.js=Vue, .NET=dotnet, C#=CSharp,
  AWS=Amazon Web Services, AI=Artificial Intelligence, DS=Data Science, DE=Data Engineering,
  DevOps=Development Operations, SRE=Site Reliability Engineering, QA=Quality Assurance
- Be realistic with scores — most unoptimized CVs score 30-50 ATS."""


def _build_skills_prompt(cv_text: str, jd_text: str) -> str:
    return f"""I will give you a CV and JD to analyse. Read them, then respond with ONLY the JSON structure specified below. Do NOT repeat or echo any CV/JD content.

--- BEGIN JD ---
{jd_text[:4000]}
--- END JD ---

--- BEGIN CV ---
{cv_text[:6000]}
--- END CV ---

Now analyse the above and return ONLY this JSON (replace example values with real analysis):
{{
  "ats_breakdown": {{
    "skill_coverage": {{"score": 55, "rationale": "Covers 8/12 required skills but missing critical ones like Kubernetes and Terraform"}},
    "experience_alignment": {{"score": 60, "rationale": "5 years experience meets the 3+ requirement; senior-level project work aligns well"}},
    "keyword_optimization": {{"score": 40, "rationale": "CV uses generic terms; missing JD-specific phrases like 'CI/CD pipeline' and 'microservices'"}},
    "education_match": {{"score": 80, "rationale": "BS Computer Science matches the required Bachelors in CS or related field"}},
    "action_verb_quality": {{"score": 45, "rationale": "Uses basic verbs like 'managed' and 'worked on'; missing impact verbs like 'architected' and 'scaled'"}},
    "section_structure": {{"score": 70, "rationale": "Has standard sections but summary is missing; bullet points are well-formatted"}},
    "overall_relevance": {{"score": 50, "rationale": "Moderate fit — strong backend skills but weak on the DevOps/cloud focus of this role"}}
  }},
  "quick_match": {{
    "experience": {{"cv_value": "5 years", "jd_value": "3+ years", "match_quality": "Strong Match"}},
    "education": {{"cv_value": "Bachelors", "jd_value": "Bachelors", "match_quality": "Strong Match"}},
    "skills": {{"cv_value": "8/12 key skills", "jd_value": "12 required", "match_quality": "Good Match"}},
    "location": {{"cv_value": "New York, NY", "jd_value": "Remote / US-based", "match_quality": "Strong Match"}}
  }},
  "skill_match": {{
    "matched": ["Python", "AWS"],
    "missing": ["Kubernetes"],
    "extra": ["Vue.js"],
    "skill_score": 66.7,
    "matched_by_category": {{"Programming Languages": ["Python"]}},
    "missing_by_category": {{"Cloud & DevOps": ["Kubernetes"]}},
    "extra_by_category": {{"Frameworks": ["Vue.js"]}},
    "category_breakdown": {{
      "Programming Languages": {{"matched": ["Python"], "missing": ["Go"], "score": 50.0}}
    }}
  }},
  "top_skill_groups": [
    {{
      "category": "Programming Languages",
      "importance": "Must-have",
      "skills": [{{"skill": "Python", "found": true}}, {{"skill": "Go", "found": false}}],
      "matched": 1,
      "total": 2
    }}
  ],
  "experience_analysis": {{
    "verb_alignment": 55.0,
    "common_action_verbs": ["develop", "manage"],
    "missing_action_verbs": ["architect", "scale"],
    "section_relevance": [
      {{"section": "Experience", "relevance": 65.0}},
      {{"section": "Summary", "relevance": 50.0}},
      {{"section": "Education", "relevance": 40.0}},
      {{"section": "Skills", "relevance": 70.0}},
      {{"section": "Soft Skills", "relevance": 35.0}},
      {{"section": "Future-Ready Skills", "relevance": 25.0}}
    ]
  }},
  "role_relevancy_score": 55,
  "jd_keywords": ["keyword1", "keyword2"],
  "cv_keywords": ["keyword1", "keyword2"]
}}

Instructions:
- ats_breakdown: Score each of the 7 components 0-100. Be REALISTIC — most unoptimized CVs score 30-50 per component. Each rationale must be 1 sentence referencing specific CV/JD content.
  - skill_coverage (weight 30%): % of required JD skills found in CV
  - experience_alignment (weight 20%): years + seniority + domain fit
  - keyword_optimization (weight 15%): JD term density, placement, exact phrasing
  - education_match (weight 10%): degree, field, certifications alignment
  - action_verb_quality (weight 10%): achievement-oriented language vs passive/generic
  - section_structure (weight 10%): ATS-parsable format, standard sections, readability
  - overall_relevance (weight 5%): holistic fit — would a recruiter shortlist this candidate?
- quick_match: Extract REAL values from the CV and JD. match_quality: "Strong Match"/"Good Match"/"Weak Match"
  - location: Extract the candidate's location from the CV (look for city, state, country, or "Remote" mentions near the top or in contact info). Extract the job location from the JD (look for "Location:", "Based in:", or remote/hybrid/onsite mentions). If the CV doesn't mention location, use "Not mentioned" for cv_value. If the JD doesn't mention location, use "Not mentioned" for jd_value. Compare them for match_quality.
- skill_match: ALL skills from JD classified as matched/missing. ALL extra CV skills. Group by category. skill_score = matched/total*100
- top_skill_groups: 6-8 groups from JD, ordered by importance. Mark each skill found/not-found in CV
- experience_analysis: verb_alignment 0-100, list common and missing action verbs. section_relevance MUST have exactly 6 sections: Experience, Summary, Education, Skills, Soft Skills, Future-Ready Skills — each scored 0-100 for relevance to the JD
- role_relevancy_score: A single integer 0-100 representing how relevant the candidate's overall profile is to this specific role. Consider industry alignment, seniority match, domain expertise, and career trajectory. Be realistic: most unoptimized CVs score 30-60.
- jd_keywords/cv_keywords: Top 15 important keywords each
- NEVER echo back the CV or JD text. Return ONLY the JSON."""


# ---------------------------------------------------------------------------
# Call 2: Recruiter Insights
# ---------------------------------------------------------------------------

# [7h] Stronger JSON enforcement
_RECRUITER_SYSTEM = """You are a senior technical recruiter and career development advisor with 15+ years of hiring experience. You evaluate candidates directly and specifically — no fluff. You also recommend specific skills and learning paths to close career gaps. Address the candidate in 2nd person (you/your).

RULES:
- Output ONLY a valid JSON object. Do NOT include any text outside the JSON.
- Your output must parse with json.loads(). No trailing commas, no comments.
- All string values must be properly escaped. No literal newlines inside strings.
- Do NOT echo or repeat the CV or JD content.
- Reference specific items from the CV, not generic advice.
- Be honest: a weak fit is a weak fit."""


def _build_recruiter_prompt(cv_text: str, jd_text: str,
                            ats_score: int, matched: list, missing: list,
                            skill_score: float) -> str:
    matched_str = ', '.join(matched[:15]) or 'None'
    missing_str = ', '.join(missing[:15]) or 'None'

    return f"""Evaluate this candidate. ATS Score: {ats_score}%. Skill Match: {skill_score:.0f}%. Matched: {matched_str}. Missing: {missing_str}.

<JD>
{jd_text[:4000]}
</JD>

<CV>
{cv_text[:6000]}
</CV>

Return this JSON:
{{
  "profile_summary": "3-5 sentences in 2nd person. Start with overall verdict, reference specific CV content, end with top action item.",
  "working_well": ["Strength 1 referencing CV content", "Strength 2"],
  "needs_improvement": ["Gap 1 referencing missing skill/experience", "Gap 2"],
  "suggestions": [
    {{
      "type": "skill_acquisition",
      "skill": "Kubernetes",
      "title": "Learn Kubernetes for Container Orchestration",
      "body": "The JD requires container orchestration experience. Kubernetes is the industry standard and critical for this DevOps role.",
      "course_name": "Kubernetes for the Absolute Beginners - Hands-on",
      "platform": "Udemy",
      "priority": "high"
    }}
  ],
  "skill_gap_tips": [
    {{
      "skill": "SkillName",
      "tip": "One actionable sentence to demonstrate this skill.",
      "original_text": "Managed database operations for the team",
      "improved_text": "Architected and optimized PostgreSQL database cluster serving 2M+ daily queries with 99.9% uptime"
    }}
  ]
}}

Instructions:
- profile_summary: 3-5 sentences, 2nd person, specific, honest
- working_well: 3-5 genuine strengths for THIS role
- needs_improvement: 3-5 real gaps, be direct
- suggestions: EXACTLY 5-7 skill acquisition recommendations based on the candidate's skill gaps against this JD. Each must:
  - Focus on a SPECIFIC skill the candidate is MISSING or WEAK in (from the missing skills list above)
  - type: always "skill_acquisition"
  - skill: the exact skill name from the missing skills list
  - title: a concise actionable learning goal (e.g., "Master Docker and Container Orchestration")
  - body: 1-2 sentences explaining WHY this skill matters for THIS role, referencing the JD
  - course_name: recommend a specific, well-known course or certification program (e.g., "AWS Certified Solutions Architect", "Google Project Management Certificate", "The Complete Python Bootcamp"). Use your knowledge of popular courses.
  - platform: which platform offers it (Udemy, Coursera, Simplilearn, LinkedIn Learning, edX, Pluralsight)
  - priority: first 2 "high" (most critical missing skills), next 2 "medium", rest "low"
  - Do NOT give CV writing advice like "Tailor Your CV" or "Quantify Achievements". Focus ONLY on what skills to LEARN/ACQUIRE.
- skill_gap_tips: Top 3-5 missing or weak skills. Each must include:
  - skill: the skill name
  - tip: one actionable sentence explaining how to address this gap
  - original_text: a REAL bullet point or phrase from the candidate's CV that could be improved to showcase this skill (or "Not present in CV" if the skill is completely absent from their experience)
  - improved_text: a rewritten version of that bullet point incorporating the missing skill naturally. Make it specific, quantified, and compelling. If original_text is "Not present in CV", write a NEW bullet point the candidate could add based on their existing experience.
- NEVER echo the CV or JD. Return ONLY the JSON."""


# ---------------------------------------------------------------------------
# ATS Score Computation
# ---------------------------------------------------------------------------

_ATS_WEIGHTS = {
    'skill_coverage': 0.30,
    'experience_alignment': 0.20,
    'keyword_optimization': 0.15,
    'education_match': 0.10,
    'action_verb_quality': 0.10,
    'section_structure': 0.10,
    'overall_relevance': 0.05,
}

_ATS_LABELS = {
    'skill_coverage': 'Skill Coverage',
    'experience_alignment': 'Experience Alignment',
    'keyword_optimization': 'Keyword Optimization',
    'education_match': 'Education Match',
    'action_verb_quality': 'Action Verb Quality',
    'section_structure': 'Section Structure',
    'overall_relevance': 'Overall Relevance',
}


def compute_ats_score(breakdown: dict) -> tuple:
    """Compute weighted ATS score from 7-component breakdown.

    Returns (composite_score: int, detailed_breakdown: list[dict]).
    Each item in detailed_breakdown has: key, label, score, weight, weighted,
    rationale.
    """
    detailed = []
    total_weighted = 0.0

    for key, weight in _ATS_WEIGHTS.items():
        component = breakdown.get(key, {})
        raw_score = _ensure_float(component.get('score', 0)) if isinstance(component, dict) else 0.0
        raw_score = min(100.0, max(0.0, raw_score))
        rationale = str(component.get('rationale', '')) if isinstance(component, dict) else ''
        weighted = round(raw_score * weight, 1)
        total_weighted += weighted
        detailed.append({
            'key': key,
            'label': _ATS_LABELS.get(key, key),
            'score': round(raw_score),
            'weight': round(weight * 100),
            'weighted': weighted,
            'rationale': rationale,
        })

    composite = min(100, max(0, round(total_weighted)))
    return composite, detailed


# ---------------------------------------------------------------------------
# Course URL Generation (Change 6)
# ---------------------------------------------------------------------------

def _generate_course_url(topic: str) -> str:
    """Generate a Udemy free course search URL for a given topic (legacy)."""
    clean_topic = topic.strip()
    encoded = urllib.parse.quote_plus(clean_topic)
    return f'https://www.udemy.com/courses/search/?q={encoded}&price=price-free&sort=relevance'


def _generate_course_urls(skill: str, course_name: str = '', platform: str = '') -> list:
    """Generate course search URLs across multiple learning platforms."""
    search_term = course_name.strip() if course_name.strip() else skill.strip()
    encoded = urllib.parse.quote_plus(search_term)
    skill_encoded = urllib.parse.quote_plus(skill.strip())

    platforms = [
        {'name': 'Udemy', 'url': f'https://www.udemy.com/courses/search/?q={encoded}&sort=relevance'},
        {'name': 'Coursera', 'url': f'https://www.coursera.org/search?query={encoded}'},
        {'name': 'Simplilearn', 'url': f'https://www.simplilearn.com/search?query={skill_encoded}'},
    ]

    # Sort preferred platform first if LLM specified one
    if platform:
        platform_lower = platform.lower()
        platforms.sort(key=lambda p: 0 if platform_lower in p['name'].lower() else 1)

    return platforms


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_with_llm(cv_text: str, jd_text: str) -> dict:
    """Run full analysis via two LLM calls. Returns template-ready dict."""
    if not LLM_ENABLED:
        raise RuntimeError('LLM is not configured (set GEMINI_API_KEY)')

    # --- Call 1: Skills & Scoring ---
    skills_prompt = _build_skills_prompt(cv_text, jd_text)
    logger.info('LLM call 1: skills & scoring (%d chars)', len(skills_prompt))
    # [7d] Lower temperature for more deterministic output
    # Gemini 2.5 Flash is a thinking model — thinking tokens consume part of
    # max_tokens budget, so we need ~3-4x the expected output size
    skills_data = _call_llm(_SKILLS_SYSTEM, skills_prompt, max_tokens=16000,
                            temperature=0.2, timeout=120.0)

    # --- Build results from call 1 ---
    results = {}

    # ATS Breakdown — compute weighted composite from 7 sub-scores
    raw_breakdown = skills_data.get('ats_breakdown', {})
    if isinstance(raw_breakdown, dict) and raw_breakdown:
        ats_composite, ats_detailed = compute_ats_score(raw_breakdown)
        results['ats_score'] = ats_composite
        results['ats_breakdown'] = ats_detailed
    else:
        # Fallback: use single ats_score if breakdown missing
        ats = skills_data.get('ats_score', 40)
        results['ats_score'] = min(100, max(0, int(ats))) if isinstance(ats, (int, float)) else 40
        results['ats_breakdown'] = []

    qm = skills_data.get('quick_match', {})
    results['quick_match'] = {}
    for key in ('experience', 'education', 'skills', 'location'):
        dim = qm.get(key, {})
        results['quick_match'][key] = {
            'cv_value': str(dim.get('cv_value', 'Not specified')),
            'jd_value': str(dim.get('jd_value', 'Not specified')),
            'match_quality': str(dim.get('match_quality', 'Good Match')),
        }

    sm = skills_data.get('skill_match', {})
    results['skill_match'] = {
        'matched': _ensure_list(sm.get('matched', [])),
        'missing': _ensure_list(sm.get('missing', [])),
        'extra': _ensure_list(sm.get('extra', [])),
        'skill_score': _ensure_float(sm.get('skill_score', 0)),
        'matched_by_category': _ensure_dict_of_lists(sm.get('matched_by_category', {})),
        'missing_by_category': _ensure_dict_of_lists(sm.get('missing_by_category', {})),
        'extra_by_category': _ensure_dict_of_lists(sm.get('extra_by_category', {})),
        'category_breakdown': _normalise_category_breakdown(sm.get('category_breakdown', {})),
    }

    tsg = skills_data.get('top_skill_groups', [])
    results['top_skill_groups'] = _normalise_top_skill_groups(tsg)

    # [Change 3] Show top 3 matched skills instead of "found/total" format
    if results['top_skill_groups']:
        total = sum(g['total'] for g in results['top_skill_groups'])
        found = sum(g['matched'] for g in results['top_skill_groups'])
        matched_skills = results['skill_match']['matched']
        top_3 = matched_skills[:3]
        results['quick_match']['skills']['cv_value'] = ', '.join(top_3) if top_3 else 'No matches'
        results['quick_match']['skills']['top_matched'] = top_3
        results['quick_match']['skills']['total_matched'] = found
        results['quick_match']['skills']['total_required'] = total
        results['quick_match']['skills']['jd_value'] = f'{total} required'

    ea = skills_data.get('experience_analysis', {})
    results['experience_analysis'] = {
        'verb_alignment': _ensure_float(ea.get('verb_alignment', 0)),
        'common_action_verbs': _ensure_list(ea.get('common_action_verbs', [])),
        'missing_action_verbs': _ensure_list(ea.get('missing_action_verbs', [])),
        'section_relevance': _normalise_section_relevance(ea.get('section_relevance', [])),
    }

    # [7f] Enforce exactly 6 sections in section_relevance
    _REQUIRED_SECTIONS = ['Experience', 'Summary', 'Education', 'Skills', 'Soft Skills', 'Future-Ready Skills']
    existing_sections = {s['section'] for s in results['experience_analysis']['section_relevance']}
    for section_name in _REQUIRED_SECTIONS:
        if section_name not in existing_sections:
            results['experience_analysis']['section_relevance'].append({
                'section': section_name,
                'relevance': 0.0,
            })
    results['experience_analysis']['section_relevance'] = [
        s for s in results['experience_analysis']['section_relevance']
        if s['section'] in set(_REQUIRED_SECTIONS)
    ][:6]

    # [Change 2] Role relevancy score
    role_rel = skills_data.get('role_relevancy_score', None)
    if role_rel is not None:
        results['role_relevancy_score'] = min(100, max(0, int(_ensure_float(role_rel))))
    else:
        # Fallback: use overall_relevance from ATS breakdown
        or_score = raw_breakdown.get('overall_relevance', {})
        if isinstance(or_score, dict):
            results['role_relevancy_score'] = min(100, max(0, int(_ensure_float(or_score.get('score', 45)))))
        else:
            results['role_relevancy_score'] = 45

    skill_score = results['skill_match']['skill_score']
    verb_score = results['experience_analysis']['verb_alignment']
    results['tfidf_score'] = results['ats_score']
    results['composite_score'] = results['ats_score']

    jd_kw = skills_data.get('jd_keywords', [])
    cv_kw = skills_data.get('cv_keywords', [])
    results['jd_keywords'] = [{'phrase': k, 'score': 1.0} for k in jd_kw if isinstance(k, str)]
    results['cv_keywords'] = [{'phrase': k, 'score': 1.0} for k in cv_kw if isinstance(k, str)]
    results['jd_keywords_categorized'] = _categorize_keywords(
        results['jd_keywords'], results['skill_match'].get('matched_by_category', {}),
        results['skill_match'].get('missing_by_category', {}))
    results['cv_keywords_categorized'] = _categorize_keywords(
        results['cv_keywords'], results['skill_match'].get('matched_by_category', {}),
        results['skill_match'].get('extra_by_category', {}))

    # [7b] Fix: jd_skills = all JD skills, cv_skills = all CV skills
    jd_all = {}
    for cat, skills in results['skill_match'].get('matched_by_category', {}).items():
        jd_all.setdefault(cat, []).extend(skills)
    for cat, skills in results['skill_match'].get('missing_by_category', {}).items():
        jd_all.setdefault(cat, []).extend(skills)
    results['jd_skills'] = jd_all

    cv_all = {}
    for cat, skills in results['skill_match'].get('matched_by_category', {}).items():
        cv_all.setdefault(cat, []).extend(skills)
    for cat, skills in results['skill_match'].get('extra_by_category', {}).items():
        cv_all.setdefault(cat, []).extend(skills)
    results['cv_skills'] = cv_all

    # --- Call 2: Recruiter Insights ---
    try:
        recruiter_prompt = _build_recruiter_prompt(
            cv_text, jd_text,
            results['ats_score'],
            results['skill_match']['matched'],
            results['skill_match']['missing'],
            skill_score,
        )
        logger.info('LLM call 2: recruiter insights (%d chars)', len(recruiter_prompt))
        # [7d] Lower temperature for consistency
        recruiter_data = _call_llm(_RECRUITER_SYSTEM, recruiter_prompt,
                                    max_tokens=12000, temperature=0.25, timeout=120.0)

        results['llm_insights'] = {}
        if isinstance(recruiter_data.get('profile_summary'), str) and recruiter_data['profile_summary'].strip():
            results['llm_insights']['profile_summary'] = recruiter_data['profile_summary']
        if isinstance(recruiter_data.get('working_well'), list):
            results['llm_insights']['working_well'] = [s for s in recruiter_data['working_well'] if isinstance(s, str) and s.strip()]
        if isinstance(recruiter_data.get('needs_improvement'), list):
            results['llm_insights']['needs_improvement'] = [s for s in recruiter_data['needs_improvement'] if isinstance(s, str) and s.strip()]

        # [Change 5] Handle skill_gap_tips — new list format with before/after
        raw_tips = recruiter_data.get('skill_gap_tips', [])
        if isinstance(raw_tips, list):
            gap_tips = []
            for tip in raw_tips:
                if isinstance(tip, dict) and tip.get('skill'):
                    gap_tips.append({
                        'skill': str(tip.get('skill', '')),
                        'tip': str(tip.get('tip', '')),
                        'original_text': str(tip.get('original_text', '')),
                        'improved_text': str(tip.get('improved_text', '')),
                    })
            results['llm_insights']['skill_gap_tips'] = gap_tips
        elif isinstance(raw_tips, dict):
            # Legacy dict format — convert to list format
            gap_tips = []
            for skill, tip_text in raw_tips.items():
                gap_tips.append({
                    'skill': str(skill),
                    'tip': str(tip_text),
                    'original_text': '',
                    'improved_text': '',
                })
            results['llm_insights']['skill_gap_tips'] = gap_tips

        results['llm_insights']['ats_score'] = results['ats_score']

        raw_suggestions = recruiter_data.get('suggestions', [])
        results['suggestions'] = []
        for i, s in enumerate(raw_suggestions):
            if isinstance(s, dict) and s.get('title'):
                skill = s.get('skill', s['title'])
                course_name = s.get('course_name', '')
                platform = s.get('platform', '')
                results['suggestions'].append({
                    'type': s.get('type', 'skill_acquisition'),
                    'skill': skill,
                    'title': s['title'],
                    'body': s.get('body', ''),
                    'course_name': course_name,
                    'platform': platform,
                    # [7g] Proper priority fallback: high/medium/low
                    'priority': s.get('priority', 'high' if i < 2 else ('medium' if i < 4 else 'low')),
                    'course_urls': _generate_course_urls(skill, course_name, platform),
                })

        # Mark that we have enhanced (LLM-powered) suggestions
        if results['suggestions']:
            results['llm_insights']['enhanced_suggestions'] = True

    except Exception as e:
        logger.error('Recruiter insights call failed: %s', e, exc_info=True)
        results['llm_insights'] = {}
        results['suggestions'] = []

    # Fallback: ensure profile_summary is never missing
    if not results.get('llm_insights', {}).get('profile_summary'):
        score = results['ats_score']
        matched = len(results['skill_match']['matched'])
        total = matched + len(results['skill_match']['missing'])
        if score >= 70:
            verdict = f'Your CV is a strong match for this role with an ATS score of {score}%.'
        elif score >= 40:
            verdict = f'Your CV shows moderate alignment with this role (ATS score: {score}%). There are clear areas for improvement.'
        else:
            verdict = f'Your CV needs significant optimization for this role (ATS score: {score}%). Key skill gaps need to be addressed.'
        results.setdefault('llm_insights', {})['profile_summary'] = (
            f'{verdict} You match {matched} out of {total} key skills the role requires. '
            f'Review the detailed breakdown below to understand where your CV stands and how to improve it.'
        )

    # Ensure suggestions has at least 5 items — skill acquisition defaults
    _default_suggestions = [
        {'type': 'skill_acquisition', 'skill': 'Cloud Computing',
         'title': 'Build Cloud Computing Fundamentals',
         'body': 'Cloud skills are increasingly required across most tech roles. Start with a foundational certification.',
         'course_name': 'AWS Cloud Practitioner Essentials', 'platform': 'Coursera', 'priority': 'high',
         'course_urls': _generate_course_urls('Cloud Computing', 'AWS Cloud Practitioner Essentials', 'Coursera')},
        {'type': 'skill_acquisition', 'skill': 'Project Management',
         'title': 'Develop Project Management Skills',
         'body': 'Project management methodology is valued in almost every technical role for leading initiatives effectively.',
         'course_name': 'Google Project Management Certificate', 'platform': 'Coursera', 'priority': 'high',
         'course_urls': _generate_course_urls('Project Management', 'Google Project Management Certificate', 'Coursera')},
        {'type': 'skill_acquisition', 'skill': 'Data Analysis',
         'title': 'Learn Data Analysis and Visualization',
         'body': 'Data-driven decision making is a core competency employers look for across all technical and business roles.',
         'course_name': 'Google Data Analytics Certificate', 'platform': 'Coursera', 'priority': 'medium',
         'course_urls': _generate_course_urls('Data Analysis', 'Google Data Analytics Certificate', 'Coursera')},
        {'type': 'skill_acquisition', 'skill': 'Communication',
         'title': 'Strengthen Technical Communication',
         'body': 'Clear communication is consistently cited as a top skill gap. Learn to present technical concepts to non-technical stakeholders.',
         'course_name': 'Business Communication Skills', 'platform': 'Udemy', 'priority': 'medium',
         'course_urls': _generate_course_urls('Technical Communication', 'Business Communication Skills', 'Udemy')},
        {'type': 'skill_acquisition', 'skill': 'Agile Methodologies',
         'title': 'Master Agile and Scrum Practices',
         'body': 'Most modern teams operate in Agile environments. Understanding Scrum, Kanban, and sprint planning is essential.',
         'course_name': 'Agile with Atlassian Jira', 'platform': 'Coursera', 'priority': 'low',
         'course_urls': _generate_course_urls('Agile Methodologies', 'Agile with Atlassian Jira', 'Coursera')},
    ]
    if not results.get('suggestions'):
        results['suggestions'] = _default_suggestions
    elif len(results['suggestions']) < 5:
        # Pad with defaults that aren't already present
        existing_titles = {s['title'].lower() for s in results['suggestions']}
        for ds in _default_suggestions:
            if len(results['suggestions']) >= 5:
                break
            if ds['title'].lower() not in existing_titles:
                results['suggestions'].append(ds)

    logger.info('Analysis complete: ATS=%d, skills=%d/%d, relevancy=%d',
                results['ats_score'],
                len(results['skill_match']['matched']),
                len(results['skill_match']['matched']) + len(results['skill_match']['missing']),
                results.get('role_relevancy_score', 0))
    return results


# ---------------------------------------------------------------------------
# Call 3: CV Rewrite (on-demand, paid feature)
# ---------------------------------------------------------------------------

_REWRITE_SYSTEM = """You are an expert CV writer and ATS optimization specialist with 15+ years of experience. You rewrite CVs to maximize ATS scores and recruiter appeal for a specific job description.

CRITICAL RULES:
- Output ONLY a valid JSON object. Do NOT include any text outside the JSON.
- NEVER fabricate experience, degrees, companies, job titles, or skills the candidate doesn't have.
- ONLY reorganize, reword, and optimize what already exists in the original CV.
- You MUST preserve EVERY section and EVERY job/experience entry from the original CV. Do NOT drop any roles, internships, projects, education entries, or sections — even short or old ones.
- Naturally weave in JD keywords where truthful.
- Use strong, specific action verbs and quantify achievements where possible.
- The candidate's name and all contact information must appear EXACTLY as in the original — do NOT alter, rearrange, or garble the name.
- Keep ALL dates, ALL company names, ALL job titles exactly as they are.
- Address the candidate in 2nd person in the changes_summary.
- The rewritten CV must be AT LEAST as long as the original. Never shorten or truncate it."""

_REWRITE_PROMPT = """Rewrite this CV to be optimized for the target role below. You MUST preserve every single section, job entry, internship, project, and detail from the original CV.

Matched skills (already in CV): {matched}
Missing skills (DO NOT fabricate — only mention if the candidate has related transferable experience): {missing}
Missing action verbs to incorporate where truthful: {missing_verbs}
Current ATS score: {ats_score}%

<JD>
{jd_text}
</JD>

<ORIGINAL_CV>
{cv_text}
</ORIGINAL_CV>

Return this JSON:
{{
  "rewritten_cv": "The COMPLETE rewritten CV text. Every section, every job, every bullet point from the original must be present.",
  "changes_summary": [
    "Specific change 1 — what was improved and why",
    "Specific change 2 — what was improved and why"
  ],
  "expected_ats_improvement": 15
}}

STRICT Instructions for rewritten_cv:
- Use this EXACT format structure:
  CANDIDATE NAME (exactly as original)
  TITLE LINE (e.g., "EXPERIENCED ENGINEER | AI | DATA SCIENCE")

  CONTACT
  Phone: ...
  Email: ...
  LinkedIn: ...
  GitHub: ... (if present)

  SUMMARY
  (Rewrite the summary to be more targeted to the JD. Keep all factual claims.)

  EXPERIENCE
  COMPANY NAME — Date Range
  Job Title
  * Bullet point 1 (improved with action verbs + metrics)
  * Bullet point 2
  (Repeat for EVERY company/role in the original CV — do NOT skip any!)

  EDUCATION
  DEGREE — UNIVERSITY
  Concentration/Details
  (Repeat for ALL degrees)

  PROJECTS
  Project Name
  * Detail 1
  * Detail 2
  (Include ALL projects from original)

  (Include any other sections from the original: HOBBIES, CERTIFICATIONS, etc.)

- You MUST include EVERY job/internship from the original, even short summer internships. Count the number of roles in the original CV and ensure the same count appears in the output.
- Improve wording: replace weak verbs (worked on, helped, did) with strong verbs (architected, spearheaded, engineered, optimized, delivered)
- Add JD keywords ONLY where the candidate genuinely has the experience
- Quantify achievements wherever possible (numbers, percentages, scale)
- Do NOT use markdown syntax like ## or ** or ### in the output — use PLAIN TEXT with CAPS for section headings and company names
- Bullet points should use * or - prefix
- changes_summary: 5-10 specific bullet points explaining what you changed and why
- expected_ats_improvement: Estimated point increase (0-40) from original score. Be realistic.
- NEVER echo the JD text. Return ONLY the JSON."""


def rewrite_cv(cv_text: str, jd_text: str, matched: list, missing: list,
               missing_verbs: list, ats_score: int) -> dict:
    """Rewrite a CV optimized for the target JD. Returns dict with
    'rewritten_cv', 'changes_summary', 'expected_ats_improvement'.

    This is the 3rd LLM call (separate from analysis, only on user action).
    """
    if not LLM_ENABLED:
        raise RuntimeError('LLM is not configured (set GEMINI_API_KEY)')

    prompt = _REWRITE_PROMPT.format(
        matched=', '.join(matched[:15]) or 'None',
        missing=', '.join(missing[:15]) or 'None',
        missing_verbs=', '.join(missing_verbs[:10]) or 'None',
        ats_score=ats_score,
        jd_text=jd_text[:3000],
        cv_text=cv_text[:8000],
    )

    logger.info('LLM call 3: CV rewrite (%d chars)', len(prompt))
    data = _call_llm(_REWRITE_SYSTEM, prompt, max_tokens=24000, timeout=180.0)

    result = {
        'rewritten_cv': str(data.get('rewritten_cv', '')),
        'changes_summary': [str(s) for s in data.get('changes_summary', []) if isinstance(s, str)],
        'expected_ats_improvement': min(40, max(0, int(data.get('expected_ats_improvement', 10)))),
    }

    if not result['rewritten_cv']:
        raise RuntimeError('LLM returned empty rewritten CV')

    if not result['changes_summary']:
        result['changes_summary'] = ['CV has been optimized for the target role.']

    logger.info('CV rewrite complete: %d chars, %d changes, +%d ATS est.',
                len(result['rewritten_cv']),
                len(result['changes_summary']),
                result['expected_ats_improvement'])
    return result


# ---------------------------------------------------------------------------
# Call 0: CV-Only Review (Tier 1 — NLP-heavy, small LLM call)
# ---------------------------------------------------------------------------

_CV_ONLY_SYSTEM = """You are an expert CV reviewer and career coach with 15+ years of hiring experience. You evaluate CVs for quality, structure, and professional presentation WITHOUT comparing to any job description.

RULES:
- Output ONLY a valid JSON object.
- Address the candidate in 2nd person (you/your).
- Be specific: reference actual content from the CV.
- Be constructive: identify strengths AND actionable improvements.
- Do NOT discuss job fit, ATS matching, or JD alignment — this is a standalone CV quality review.
- Do NOT reproduce or echo CV text."""


def _build_cv_only_prompt(cv_text: str, nlp_results: dict) -> str:
    """Build prompt for CV-only qualitative feedback, using NLP results as context."""
    # Summarise NLP findings for the LLM
    sections = nlp_results.get('sections', {})
    verbs = nlp_results.get('verbs', {})
    quant = nlp_results.get('quantification', {})
    contact = nlp_results.get('contact', {})
    formatting = nlp_results.get('formatting', {})
    skills = nlp_results.get('skills', {})
    candidate_name = nlp_results.get('candidate_name', '')

    nlp_summary = f"""NLP Analysis Summary:
- Candidate Name: {candidate_name or 'Not detected'}
- CV Quality Score: {nlp_results.get('cv_quality_score', 'N/A')}/100
- Sections found: {', '.join(sections.get('sections_found', []))}
- Sections missing: {', '.join(sections.get('sections_missing', []))}
- Word count: {formatting.get('word_count', 0)}
- Bullet points: {formatting.get('bullet_count', 0)}
- Strong action verbs: {verbs.get('strong_verb_count', 0)} ({', '.join(verbs.get('strong_verbs_found', [])[:5])})
- Weak action verbs: {verbs.get('weak_verb_count', 0)} ({', '.join(verbs.get('weak_verbs_found', [])[:5])})
- Bullets with metrics: {quant.get('bullets_with_metrics', 0)}/{quant.get('total_bullets', 0)}
- Contact: email={contact.get('email', '?')}, phone={contact.get('phone', '?')}, linkedin={contact.get('linkedin', '?')}
- Skills detected: {skills.get('total_skills', 0)} across {sum(1 for v in skills.get('category_coverage', {}).values() if v > 0)} categories"""

    sections_found_list = ', '.join(f'"{s}"' for s in sections.get('sections_found', []))

    return f"""Review this CV for overall quality and professional presentation. I've already run NLP analysis — use it as context, but add your qualitative insights.

{nlp_summary}

<CV>
{cv_text[:5000]}
</CV>

Return this JSON:
{{
  "candidate_name": "Full name of the candidate as it appears on the CV",
  "one_liner_summary": "One sentence, max 15 words, summarising the candidate's profile and strongest positioning",
  "profile_summary": "3-4 sentences assessing the CV's overall quality, structure, and presentation. Be specific about what stands out.",
  "cv_highlights": [
    {{"dimension": "Strategic Clarity", "score": 7, "rationale": "Short explanation"}},
    {{"dimension": "Progression Logic", "score": 6, "rationale": "Short explanation"}},
    {{"dimension": "Signal to Noise Ratio", "score": 5, "rationale": "Short explanation"}},
    {{"dimension": "Formatting Discipline", "score": 8, "rationale": "Short explanation"}},
    {{"dimension": "Red Flags", "score": 3, "rationale": "Short explanation"}},
    {{"dimension": "Credibility Markers", "score": 7, "rationale": "Short explanation"}}
  ],
  "section_summaries": {{
    "Summary": "One-line description of how this section reads in the CV",
    "Experience": "One-line description of the experience section"
  }},
  "working_well": [
    "Strength 1 referencing specific CV content",
    "Strength 2",
    "Strength 3"
  ],
  "needs_improvement": [
    "Issue 1 with specific actionable advice",
    "Issue 2",
    "Issue 3"
  ],
  "bullet_rewrites": [
    {{
      "original_text": "Exact weak bullet from the CV",
      "improved_text": "Rewritten version with stronger verbs and metrics",
      "improvement_reason": "Why this is better"
    }}
  ],
  "future_ready_suggestions": [
    {{
      "skill": "Docker",
      "title": "Learn Containerization",
      "body": "Containers are becoming standard for deployment. Learning Docker will future-proof your ops skills.",
      "course_name": "Docker for Beginners",
      "platform": "Udemy",
      "priority": "high"
    }}
  ],
  "general_suggestions": [
    {{
      "title": "Short title for the suggestion",
      "body": "2-3 sentences explaining why this matters and how to fix it",
      "priority": "high"
    }}
  ]
}}

Requirements:
- candidate_name: Extract the full name from the CV. If NLP detected "{candidate_name}", verify or correct it.
- one_liner_summary: Max 15 words. Example: "Experienced full-stack developer with strong React and Node.js expertise"
- cv_highlights: EXACTLY 6 dimensions, each scored 1-10:
  - Strategic Clarity: Does the CV tell a coherent career story?
  - Progression Logic: Is there visible career growth and trajectory?
  - Signal to Noise Ratio: How much of the content is impactful vs filler?
  - Formatting Discipline: Is the layout clean, consistent, and scannable?
  - Red Flags: Are there gaps, inconsistencies, or concerns? (higher = fewer red flags)
  - Credibility Markers: Are there quantified results, brand names, certifications?
- section_summaries: One-line description for EACH section found in the CV: [{sections_found_list}]. Describe what's in the section, not generic advice.
- 3-5 items in working_well
- 3-5 items in needs_improvement
- bullet_rewrites: Pick the 3-5 WEAKEST bullet points from the CV and rewrite them. NEVER fabricate experience — only improve wording, add impact verbs, suggest where metrics could go.
- future_ready_suggestions: 3-5 trending skills relevant to the candidate's DOMAIN (not JD-based). Each must have a specific course recommendation.
  - priority: first 2 "high", next 1-2 "medium", rest "low"
  - These should be forward-looking industry trends, not basic skills the candidate already has.
- 5-7 items in general_suggestions (first 2 high priority, next 2 medium, rest low)
- Be specific to THIS CV — no generic advice
- Do NOT suggest matching to a job description (user hasn't provided one yet)
- Focus on: writing quality, structure, impact, clarity, completeness"""


def analyze_cv_only(cv_text: str) -> dict:
    """Tier 1: CV-only analysis. NLP-heavy, minimal LLM.

    Returns a template-ready dict combining NLP analysis and optional
    LLM qualitative feedback.
    """
    import nlp_service

    # 1. Run all local NLP analysis
    nlp_results = nlp_service.analyze_cv_standalone(cv_text)
    logger.info('NLP analysis complete: quality_score=%d, %d skills, %d sections',
                nlp_results.get('cv_quality_score', 0),
                nlp_results.get('skills', {}).get('total_skills', 0),
                nlp_results.get('sections', {}).get('section_count', 0))

    # 2. LLM call for qualitative feedback (optional — degrades gracefully)
    try:
        if LLM_ENABLED:
            prompt = _build_cv_only_prompt(cv_text, nlp_results)
            logger.info('LLM call 0: CV-only review (%d chars)', len(prompt))
            llm_data = _call_llm(_CV_ONLY_SYSTEM, prompt, max_tokens=8000,
                                  temperature=0.3, timeout=90.0)

            # Candidate name: prefer LLM, fallback to NLP
            llm_name = str(llm_data.get('candidate_name', '')).strip()
            if llm_name and not nlp_results.get('candidate_name'):
                nlp_results['candidate_name'] = llm_name
            elif llm_name and nlp_results.get('candidate_name'):
                # LLM may correct casing or formatting
                nlp_results['candidate_name'] = llm_name

            # One-liner summary
            nlp_results['one_liner_summary'] = str(llm_data.get('one_liner_summary', '')).strip()

            # CV highlights (6 scored dimensions)
            raw_highlights = llm_data.get('cv_highlights', [])
            cv_highlights = []
            if isinstance(raw_highlights, list):
                for h in raw_highlights[:6]:
                    if isinstance(h, dict) and h.get('dimension'):
                        score = min(10, max(1, int(_ensure_float(h.get('score', 5)))))
                        cv_highlights.append({
                            'dimension': str(h['dimension']),
                            'score': score,
                            'rationale': str(h.get('rationale', '')),
                        })
            nlp_results['cv_highlights'] = cv_highlights

            # Section summaries (LLM overrides static descriptions)
            raw_section_summaries = llm_data.get('section_summaries', {})
            if isinstance(raw_section_summaries, dict):
                existing = nlp_results.get('section_descriptions', {})
                for sec, desc in raw_section_summaries.items():
                    if isinstance(desc, str) and desc.strip():
                        existing[str(sec)] = desc.strip()
                nlp_results['section_descriptions'] = existing

            # Bullet rewrites (before/after)
            raw_rewrites = llm_data.get('bullet_rewrites', [])
            bullet_rewrites = []
            if isinstance(raw_rewrites, list):
                for r in raw_rewrites[:5]:
                    if isinstance(r, dict) and r.get('original_text'):
                        bullet_rewrites.append({
                            'original_text': str(r['original_text']),
                            'improved_text': str(r.get('improved_text', '')),
                            'improvement_reason': str(r.get('improvement_reason', '')),
                        })
            nlp_results['bullet_rewrites'] = bullet_rewrites

            # Future ready suggestions
            raw_future = llm_data.get('future_ready_suggestions', [])
            future_suggestions = []
            if isinstance(raw_future, list):
                for i, fs in enumerate(raw_future[:5]):
                    if isinstance(fs, dict) and fs.get('skill'):
                        skill = str(fs['skill'])
                        course_name = str(fs.get('course_name', ''))
                        platform = str(fs.get('platform', ''))
                        future_suggestions.append({
                            'skill': skill,
                            'title': str(fs.get('title', '')),
                            'body': str(fs.get('body', '')),
                            'course_name': course_name,
                            'platform': platform,
                            'priority': str(fs.get('priority', 'high' if i < 2 else ('medium' if i < 4 else 'low'))),
                            'course_urls': _generate_course_urls(skill, course_name, platform),
                        })
            nlp_results['future_ready_suggestions'] = future_suggestions

            nlp_results['llm_insights'] = {
                'profile_summary': str(llm_data.get('profile_summary', '')),
                'working_well': [str(s) for s in llm_data.get('working_well', [])
                                 if isinstance(s, str) and s.strip()],
                'needs_improvement': [str(s) for s in llm_data.get('needs_improvement', [])
                                      if isinstance(s, str) and s.strip()],
            }

            suggestions = []
            for s in llm_data.get('general_suggestions', []):
                if isinstance(s, dict) and s.get('title'):
                    suggestions.append({
                        'title': str(s.get('title', '')),
                        'body': str(s.get('body', '')),
                        'priority': str(s.get('priority', 'medium')),
                    })
            nlp_results['suggestions'] = suggestions or _default_cv_suggestions()

            nlp_results['llm_enhanced'] = True
            logger.info('LLM CV-only review complete: %d suggestions, %d highlights, %d bullet rewrites',
                        len(nlp_results['suggestions']),
                        len(nlp_results.get('cv_highlights', [])),
                        len(nlp_results.get('bullet_rewrites', [])))
        else:
            raise RuntimeError('LLM not enabled')

    except Exception as e:
        logger.warning('CV-only LLM call failed, using NLP-only results: %s', e)
        nlp_results['llm_insights'] = {
            'profile_summary': _generate_nlp_only_summary(nlp_results),
            'working_well': nlp_results.get('formatting', {}).get('strengths', []),
            'needs_improvement': nlp_results.get('formatting', {}).get('issues', []),
        }
        nlp_results['suggestions'] = _default_cv_suggestions()
        nlp_results.setdefault('one_liner_summary', '')
        nlp_results.setdefault('cv_highlights', [])
        nlp_results.setdefault('bullet_rewrites', [])
        nlp_results.setdefault('future_ready_suggestions', [])
        nlp_results['llm_enhanced'] = False

    return nlp_results


def _generate_nlp_only_summary(nlp_results: dict) -> str:
    """Generate a profile summary from NLP results when LLM is unavailable."""
    score = nlp_results.get('cv_quality_score', 50)
    skills_count = nlp_results.get('skills', {}).get('total_skills', 0)
    sections = nlp_results.get('sections', {}).get('sections_found', [])
    word_count = nlp_results.get('formatting', {}).get('word_count', 0)

    if score >= 70:
        quality = 'well-structured'
    elif score >= 50:
        quality = 'reasonably structured'
    else:
        quality = 'in need of improvement'

    return (
        f'Your CV is {quality} with a quality score of {score}/100. '
        f'It contains {word_count} words across {len(sections)} sections '
        f'with {skills_count} identifiable skills. '
        f'Review the detailed breakdown below for specific areas to improve.'
    )


def _default_cv_suggestions() -> list:
    """Default suggestions when LLM is unavailable."""
    return [
        {
            'title': 'Strengthen Your Action Verbs',
            'body': 'Replace weak verbs like "managed" or "helped" with strong action verbs like "orchestrated", "engineered", or "spearheaded" to make your achievements more impactful.',
            'priority': 'high',
        },
        {
            'title': 'Quantify Your Achievements',
            'body': 'Add specific numbers, percentages, and scale indicators to your bullet points. "Improved API performance by 40%" is far more compelling than "Improved API performance".',
            'priority': 'high',
        },
        {
            'title': 'Ensure All Key Sections Are Present',
            'body': 'A strong CV includes Summary, Experience, Education, and Skills sections at minimum. Add any that are missing to give recruiters a complete picture.',
            'priority': 'medium',
        },
        {
            'title': 'Optimise CV Length',
            'body': 'Aim for 300-800 words (1-2 pages). Remove outdated or irrelevant entries and focus on your most impactful recent experience.',
            'priority': 'medium',
        },
        {
            'title': 'Add Contact Information',
            'body': 'Include email, phone number, and LinkedIn profile URL at the top of your CV. This makes it easy for recruiters to reach you.',
            'priority': 'low',
        },
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_list(val) -> list:
    if isinstance(val, list):
        return [str(v) for v in val if v]
    return []


def _ensure_float(val) -> float:
    try:
        return round(float(val), 1)
    except (TypeError, ValueError):
        return 0.0


def _ensure_dict_of_lists(val) -> dict:
    if not isinstance(val, dict):
        return {}
    return {str(k): _ensure_list(v) for k, v in val.items() if v}


def _normalise_category_breakdown(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return {}
    result = {}
    for cat, data in raw.items():
        if not isinstance(data, dict):
            continue
        result[str(cat)] = {
            'matched': _ensure_list(data.get('matched', [])),
            'missing': _ensure_list(data.get('missing', [])),
            'score': _ensure_float(data.get('score', 0)),
        }
    return result


def _normalise_top_skill_groups(raw: list) -> list:
    if not isinstance(raw, list):
        return []
    groups = []
    for g in raw[:8]:
        if not isinstance(g, dict) or not g.get('category'):
            continue
        skills_raw = g.get('skills', [])
        skills = []
        for s in skills_raw:
            if isinstance(s, dict) and 'skill' in s:
                skills.append({'skill': str(s['skill']), 'found': bool(s.get('found', False))})
            elif isinstance(s, str):
                skills.append({'skill': s, 'found': False})
        if skills:
            matched = sum(1 for s in skills if s['found'])
            groups.append({
                'category': str(g['category']),
                'importance': str(g.get('importance', 'Must-have')),
                'skills': skills,
                'matched': g.get('matched', matched),
                'total': g.get('total', len(skills)),
            })
    return groups


def _normalise_section_relevance(raw: list) -> list:
    if not isinstance(raw, list):
        return []
    return [
        {'section': str(s['section']), 'relevance': _ensure_float(s.get('relevance', 0))}
        for s in raw if isinstance(s, dict) and s.get('section')
    ]


# ---------------------------------------------------------------------------
# Refine CV Section (P14 — inline editing with AI)
# ---------------------------------------------------------------------------

_REFINE_SYSTEM = """You are an expert CV editor. You refine specific sections of a CV based on user instructions.

RULES:
- Output ONLY a valid JSON object with a single key "refined_text".
- Preserve the candidate's real experience — NEVER fabricate.
- Apply the user's instruction precisely.
- Keep the same general length unless the instruction says otherwise.
- Use strong action verbs and quantified achievements where possible."""


def refine_cv_section(selected_text: str, instruction: str,
                      full_cv_context: str = '') -> str:
    """Refine a selected CV section based on user instruction.

    Returns the refined text string. Raises RuntimeError on failure.
    """
    if not LLM_ENABLED:
        raise RuntimeError('LLM is not configured')

    prompt = f"""Refine the following selected text from a CV based on the user's instruction.

<SELECTED_TEXT>
{selected_text[:2000]}
</SELECTED_TEXT>

<USER_INSTRUCTION>
{instruction[:500]}
</USER_INSTRUCTION>

{f'<CV_CONTEXT>{full_cv_context[:3000]}</CV_CONTEXT>' if full_cv_context else ''}

Return this JSON:
{{
  "refined_text": "The refined version of the selected text"
}}

Rules:
- Apply the user's instruction precisely
- Keep the same format (bullet points stay as bullet points, etc.)
- NEVER fabricate experience, skills, or companies
- Improve wording, action verbs, and impact where relevant
- Return ONLY the JSON"""

    data = _call_llm(_REFINE_SYSTEM, prompt, max_tokens=2000,
                     temperature=0.3, timeout=30.0)
    refined = str(data.get('refined_text', '')).strip()
    if not refined:
        raise RuntimeError('LLM returned empty refined text')
    return refined


def _categorize_keywords(keywords: list, *category_dicts) -> dict:
    if not keywords:
        return {}
    skill_to_cat = {}
    for cat_dict in category_dicts:
        if isinstance(cat_dict, dict):
            for cat, skills in cat_dict.items():
                for skill in (skills if isinstance(skills, list) else []):
                    skill_to_cat[skill.lower()] = cat
    categorized = {}
    other = []
    for kw in keywords:
        phrase = kw.get('phrase', '') if isinstance(kw, dict) else str(kw)
        cat = skill_to_cat.get(phrase.lower())
        if cat:
            categorized.setdefault(cat, []).append(kw)
        else:
            other.append(kw)
    if other:
        categorized['Other'] = other[:10]
    return categorized
