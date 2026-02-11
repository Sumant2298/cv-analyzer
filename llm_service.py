"""LLM-powered CV analysis — waterfall multi-provider support.

Provider waterfall (tries each until one succeeds):
  1. Groq      — fastest, best JSON mode, ~1K req/day free
  2. Cerebras  — 1M tokens/day free, very fast, 8K context
  3. Together  — Llama 3.3 70B free endpoint, ~36 req/hr
  4. OpenRouter — 18+ free models, auto-routes

Also supports:
  - LOCAL_LLM_URL → Ollama / any local server (highest priority if set)

All analysis is performed via LLM — no NLP libraries needed.
Three focused LLM calls:
  1. Skills & scoring (structured extraction)
  2. Recruiter insights (narrative feedback)
  3. CV rewrite (on-demand, paid)
"""

import json
import logging
import os
import time
import urllib.parse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Waterfall Configuration
# ---------------------------------------------------------------------------

# Local LLM (highest priority if configured)
LOCAL_LLM_URL = os.environ.get('LOCAL_LLM_URL', '').rstrip('/')
LOCAL_LLM_MODEL = os.environ.get('LOCAL_LLM_MODEL', 'llama3:8b')

# Cloud providers — waterfall order
_PROVIDERS = []

# Provider 1: Groq (fastest, best structured JSON)
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
if GROQ_API_KEY:
    _PROVIDERS.append({
        'name': 'groq',
        'base_url': 'https://api.groq.com/openai/v1',
        'api_key': GROQ_API_KEY,
        'model': GROQ_MODEL,
        'max_context': 128000,
    })

# Provider 2: Cerebras — REMOVED (8K context too small for reliable results)
# CEREBRAS_API_KEY = os.environ.get('CEREBRAS_API_KEY', '')
# CEREBRAS_MODEL = os.environ.get('CEREBRAS_MODEL', 'llama-3.3-70b')

# Provider 3: Together AI (free Llama 3.3 70B endpoint)
TOGETHER_API_KEY = os.environ.get('TOGETHER_API_KEY', '')
TOGETHER_MODEL = os.environ.get('TOGETHER_MODEL',
                                 'meta-llama/Llama-3.3-70B-Instruct-Turbo-Free')
if TOGETHER_API_KEY:
    _PROVIDERS.append({
        'name': 'together',
        'base_url': 'https://api.together.xyz/v1',
        'api_key': TOGETHER_API_KEY,
        'model': TOGETHER_MODEL,
        'max_context': 128000,
    })

# Provider 4: OpenRouter (18+ free models, auto-routes)
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = os.environ.get('OPENROUTER_MODEL',
                                   'meta-llama/llama-3.3-70b-instruct:free')
if OPENROUTER_API_KEY:
    _PROVIDERS.append({
        'name': 'openrouter',
        'base_url': 'https://openrouter.ai/api/v1',
        'api_key': OPENROUTER_API_KEY,
        'model': OPENROUTER_MODEL,
        'max_context': 128000,
    })

# Determine if any backend is available
LLM_ENABLED = bool(LOCAL_LLM_URL) or bool(_PROVIDERS)

if LOCAL_LLM_URL:
    logger.info('LLM backend: LOCAL (%s, model=%s)', LOCAL_LLM_URL, LOCAL_LLM_MODEL)
if _PROVIDERS:
    names = [p['name'] for p in _PROVIDERS]
    logger.info('LLM waterfall: %s (%d providers)', ' → '.join(names), len(names))
if not LLM_ENABLED:
    logger.warning('No LLM backend configured — set at least one API key '
                   '(GROQ_API_KEY, CEREBRAS_API_KEY, TOGETHER_API_KEY, OPENROUTER_API_KEY)')

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


def _call_llm_local(system: str, prompt: str, max_tokens: int,
                     temperature: float, timeout: float) -> str:
    """Call local Ollama via direct HTTP POST (bypasses ngrok interstitial)."""
    import httpx

    base_url = LOCAL_LLM_URL.rstrip('/')
    url = f'{base_url}/api/chat'

    payload = {
        'model': LOCAL_LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': prompt},
        ],
        'stream': False,
        'format': 'json',
        'options': {
            'temperature': temperature,
            'num_predict': max_tokens,
        },
    }

    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'LevelUpX/1.0',
        'ngrok-skip-browser-warning': 'true',
    }

    logger.info('Local LLM request: %s (model=%s)', url, LOCAL_LLM_MODEL)
    resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data.get('message', {}).get('content', '')


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
    """Call a single cloud provider and return raw response text."""
    client = _get_provider_client(provider)
    name = provider['name']

    # Build extra headers for OpenRouter
    extra_kwargs = {}
    if name == 'openrouter':
        extra_kwargs['extra_headers'] = {
            'HTTP-Referer': 'https://levelupx.ai',
            'X-Title': 'LevelUpX CV Analyzer',
        }

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
        **extra_kwargs,
    )
    return response.choices[0].message.content


def _call_llm(system: str, prompt: str, max_tokens: int = 3000,
              temperature: float = 0.3, timeout: float = 120.0,
              _retries: int = 2) -> dict:
    """Call LLM with waterfall failover across providers.

    Tries each provider in order. Within each provider, retries up to
    _retries times on JSON validation failures. On rate limit / server
    errors, falls through to the next provider.

    Skips providers whose max_context is too small for the request.

    For local backend, uses Ollama native API directly.
    """
    errors_by_provider = {}

    # Rough token estimate: 1 token ≈ 4 chars for English text
    estimated_input_tokens = (len(system) + len(prompt)) // 3
    min_context_needed = estimated_input_tokens + max_tokens

    # --- Local LLM first (if configured) ---
    if LOCAL_LLM_URL:
        try:
            t = max(timeout, 180.0)
            raw = _call_llm_local(system, prompt, max_tokens, temperature, t)
            logger.info('LLM response (local): %d chars', len(raw))
            return _parse_raw_json(raw)
        except Exception as e:
            logger.warning('Local LLM failed: %s', e)
            errors_by_provider['local'] = e
            if not _PROVIDERS:
                raise

    # --- Waterfall through cloud providers ---
    if not _PROVIDERS:
        raise RuntimeError('No LLM backend configured — set at least one API key')

    for provider in _PROVIDERS:
        name = provider['name']
        last_error = None

        # Skip providers that can't fit this request
        provider_context = provider.get('max_context', 128000)
        if min_context_needed > provider_context:
            logger.info('[%s] skipped — estimated %d tokens exceeds %d context',
                        name, min_context_needed, provider_context)
            errors_by_provider[name] = RuntimeError(
                f'Context too small: need ~{min_context_needed}, have {provider_context}')
            continue

        for attempt in range(_retries + 1):
            try:
                # [7c] Decrease temperature on retry for more deterministic JSON
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

                result = _parse_raw_json(raw)
                if attempt > 0 or provider != _PROVIDERS[0]:
                    logger.info('[%s] succeeded (waterfall position: %d)',
                                name, _PROVIDERS.index(provider) + 1)
                return result

            except Exception as e:
                last_error = e
                error_str = str(e)

                # JSON validation failure → retry same provider
                if ('json_validate_failed' in error_str or
                        'failed_generation' in error_str):
                    logger.warning('[%s] JSON validation failed (attempt %d/%d): %s',
                                   name, attempt + 1, _retries + 1, error_str[:200])
                    if attempt < _retries:
                        continue
                    # Exhausted retries for this provider — fall through
                    break

                # Rate limit / server error → short backoff then fall through
                if _is_rate_limit_error(e):
                    logger.warning('[%s] rate limited / unavailable: %s',
                                   name, error_str[:200])
                    # Brief pause before trying next provider (helps if limits are per-second)
                    time.sleep(2)
                    break

                # Other error (auth, invalid model, etc.) → fall through
                logger.warning('[%s] error: %s — trying next provider',
                               name, error_str[:200])
                break

        errors_by_provider[name] = last_error

    # All providers failed — last-resort: wait 15s and retry the first viable provider
    all_rate_limited = all(_is_rate_limit_error(e) for e in errors_by_provider.values()
                          if e is not None)
    if all_rate_limited and _PROVIDERS:
        logger.info('All providers rate-limited — waiting 15s for cooldown retry...')
        time.sleep(15)
        # Retry first viable provider once
        for provider in _PROVIDERS:
            name = provider['name']
            provider_context = provider.get('max_context', 128000)
            if min_context_needed > provider_context:
                continue
            try:
                raw = _call_provider(provider, system, prompt,
                                     max_tokens, temperature, timeout)
                logger.info('[%s] cooldown retry succeeded', name)
                return _parse_raw_json(raw)
            except Exception as e:
                logger.warning('[%s] cooldown retry also failed: %s', name, str(e)[:200])
                errors_by_provider[f'{name}_retry'] = e
                break

    provider_summary = '; '.join(f'{n}: {str(e)[:80]}' for n, e in errors_by_provider.items())
    raise RuntimeError(
        f'All LLM providers failed. Tried: {provider_summary}'
    )


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
        raise RuntimeError('LLM is not configured (set LOCAL_LLM_URL or GROQ_API_KEY)')

    # --- Call 1: Skills & Scoring ---
    skills_prompt = _build_skills_prompt(cv_text, jd_text)
    logger.info('LLM call 1: skills & scoring (%d chars)', len(skills_prompt))
    # [7d] Lower temperature for more deterministic output
    skills_data = _call_llm(_SKILLS_SYSTEM, skills_prompt, max_tokens=4000,
                            temperature=0.2, timeout=60.0)

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
                                    max_tokens=3500, temperature=0.25, timeout=60.0)

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
        raise RuntimeError('LLM is not configured (set LOCAL_LLM_URL or GROQ_API_KEY)')

    prompt = _REWRITE_PROMPT.format(
        matched=', '.join(matched[:15]) or 'None',
        missing=', '.join(missing[:15]) or 'None',
        missing_verbs=', '.join(missing_verbs[:10]) or 'None',
        ats_score=ats_score,
        jd_text=jd_text[:3000],
        cv_text=cv_text[:8000],
    )

    logger.info('LLM call 3: CV rewrite (%d chars)', len(prompt))
    data = _call_llm(_REWRITE_SYSTEM, prompt, max_tokens=8000, timeout=180.0)

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
