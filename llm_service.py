"""LLM-powered CV analysis using Groq.

All analysis is performed via LLM — no NLP libraries needed.
Two focused LLM calls:
  1. Skills & scoring (structured extraction)
  2. Recruiter insights (narrative feedback)
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
LLM_ENABLED = bool(GROQ_API_KEY)

_groq_client = None


def _get_client():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


def _call_llm(system: str, prompt: str, max_tokens: int = 3000,
              temperature: float = 0.3, timeout: float = 25.0) -> dict:
    """Call Groq API and parse JSON response."""
    client = _get_client()
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={'type': 'json_object'},
        timeout=timeout,
    )
    raw = response.choices[0].message.content
    logger.info('LLM response: %d chars', len(raw))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Call 1: Skills & Scoring
# ---------------------------------------------------------------------------

_SKILLS_SYSTEM = """You are an ATS (Applicant Tracking System) that analyses CVs against job descriptions. You extract skills, score matches, and identify gaps.

RULES:
- Output ONLY a valid JSON object. Do NOT include any text outside the JSON.
- Do NOT echo or repeat the CV or JD content.
- Be thorough: check aliases (JS=JavaScript, K8s=Kubernetes, etc.)
- Be realistic with scores — most unoptimized CVs score 30-50 ATS."""


def _build_skills_prompt(cv_text: str, jd_text: str) -> str:
    return f"""Analyse this CV against the JD. Return ONLY the JSON below.

<JD>
{jd_text[:2500]}
</JD>

<CV>
{cv_text[:3000]}
</CV>

Return this JSON:
{{
  "ats_score": 45,
  "quick_match": {{
    "experience": {{"cv_value": "5 years", "jd_value": "3+ years", "match_quality": "Strong Match"}},
    "education": {{"cv_value": "Bachelors", "jd_value": "Bachelors", "match_quality": "Strong Match"}},
    "skills": {{"cv_value": "8/12 key skills", "jd_value": "12 required", "match_quality": "Good Match"}},
    "location": {{"cv_value": "Remote", "jd_value": "Remote", "match_quality": "Strong Match"}}
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
      {{"section": "Education", "relevance": 40.0}}
    ]
  }},
  "jd_keywords": ["keyword1", "keyword2"],
  "cv_keywords": ["keyword1", "keyword2"]
}}

Instructions:
- ats_score: 0-100, realistic ATS pass likelihood
- quick_match: Extract REAL values. match_quality: "Strong Match"/"Good Match"/"Weak Match"
- skill_match: ALL skills from JD classified as matched/missing. ALL extra CV skills. Group by category. skill_score = matched/total*100
- top_skill_groups: 6-8 groups from JD, ordered by importance. Mark each skill found/not-found in CV
- experience_analysis: verb_alignment 0-100, list common and missing action verbs, section relevance 0-100
- jd_keywords/cv_keywords: Top 15 important keywords each
- NEVER echo back the CV or JD text. Return ONLY the JSON."""


# ---------------------------------------------------------------------------
# Call 2: Recruiter Insights
# ---------------------------------------------------------------------------

_RECRUITER_SYSTEM = """You are a senior technical recruiter with 15+ years of hiring experience. You evaluate candidates directly and specifically — no fluff. Address the candidate in 2nd person (you/your).

RULES:
- Output ONLY a valid JSON object. Do NOT include any text outside the JSON.
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
{jd_text[:1500]}
</JD>

<CV>
{cv_text[:2500]}
</CV>

Return this JSON:
{{
  "profile_summary": "3-5 sentences in 2nd person. Start with overall verdict, reference specific CV content, end with top action item.",
  "working_well": ["Strength 1 referencing CV content", "Strength 2"],
  "needs_improvement": ["Gap 1 referencing missing skill/experience", "Gap 2"],
  "suggestions": [
    {{
      "type": "recruiter_insight",
      "title": "5-8 word title",
      "body": "Specific advice referencing their CV",
      "examples": ["Rewritten bullet point example"],
      "priority": "high"
    }}
  ],
  "skill_gap_tips": {{
    "SkillName": "One actionable sentence to demonstrate this skill."
  }}
}}

Instructions:
- profile_summary: 3-5 sentences, 2nd person, specific, honest
- working_well: 3-5 genuine strengths for THIS role
- needs_improvement: 3-5 real gaps, be direct
- suggestions: 3-5 items, first 2 "high" priority, rest "medium"
- skill_gap_tips: Top 3-5 missing skills only, one sentence each
- NEVER echo the CV or JD. Return ONLY the JSON."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_with_llm(cv_text: str, jd_text: str) -> dict:
    """Run full analysis via two LLM calls. Returns template-ready dict."""
    if not LLM_ENABLED:
        raise RuntimeError('LLM is not configured (GROQ_API_KEY not set)')

    # --- Call 1: Skills & Scoring ---
    skills_prompt = _build_skills_prompt(cv_text, jd_text)
    logger.info('LLM call 1: skills & scoring (%d chars)', len(skills_prompt))
    skills_data = _call_llm(_SKILLS_SYSTEM, skills_prompt, max_tokens=3000, timeout=25.0)

    # --- Build results from call 1 ---
    results = {}

    ats = skills_data.get('ats_score', 40)
    results['ats_score'] = min(100, max(0, int(ats))) if isinstance(ats, (int, float)) else 40

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

    if results['top_skill_groups']:
        total = sum(g['total'] for g in results['top_skill_groups'])
        found = sum(g['matched'] for g in results['top_skill_groups'])
        results['quick_match']['skills']['cv_value'] = f'{found}/{total} key skills'

    ea = skills_data.get('experience_analysis', {})
    results['experience_analysis'] = {
        'verb_alignment': _ensure_float(ea.get('verb_alignment', 0)),
        'common_action_verbs': _ensure_list(ea.get('common_action_verbs', [])),
        'missing_action_verbs': _ensure_list(ea.get('missing_action_verbs', [])),
        'section_relevance': _normalise_section_relevance(ea.get('section_relevance', [])),
    }

    skill_score = results['skill_match']['skill_score']
    verb_score = results['experience_analysis']['verb_alignment']
    results['tfidf_score'] = results['ats_score']
    results['composite_score'] = round(
        results['ats_score'] * 0.5 + skill_score * 0.3 + verb_score * 0.2, 1
    )

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
    results['jd_skills'] = results['skill_match'].get('matched_by_category', {})
    results['cv_skills'] = results['skill_match'].get('matched_by_category', {})

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
        recruiter_data = _call_llm(_RECRUITER_SYSTEM, recruiter_prompt,
                                    max_tokens=2000, timeout=20.0)

        results['llm_insights'] = {}
        if isinstance(recruiter_data.get('profile_summary'), str):
            results['llm_insights']['profile_summary'] = recruiter_data['profile_summary']
        if isinstance(recruiter_data.get('working_well'), list):
            results['llm_insights']['working_well'] = [s for s in recruiter_data['working_well'] if isinstance(s, str)]
        if isinstance(recruiter_data.get('needs_improvement'), list):
            results['llm_insights']['needs_improvement'] = [s for s in recruiter_data['needs_improvement'] if isinstance(s, str)]
        if isinstance(recruiter_data.get('skill_gap_tips'), dict):
            results['llm_insights']['skill_gap_tips'] = recruiter_data['skill_gap_tips']
        results['llm_insights']['ats_score'] = results['ats_score']

        raw_suggestions = recruiter_data.get('suggestions', [])
        results['suggestions'] = []
        for i, s in enumerate(raw_suggestions):
            if isinstance(s, dict) and s.get('title'):
                results['suggestions'].append({
                    'type': s.get('type', 'recruiter_insight'),
                    'title': s['title'],
                    'body': s.get('body', ''),
                    'examples': _ensure_list(s.get('examples', [])),
                    'priority': s.get('priority', 'high' if i < 2 else 'medium'),
                })
    except Exception as e:
        logger.warning('Recruiter insights call failed: %s', e)
        results['llm_insights'] = {}
        results['suggestions'] = []

    # Ensure suggestions is never empty
    if not results['suggestions']:
        results['suggestions'] = [{
            'type': 'recruiter_insight',
            'title': 'Tailor Your CV to This Role',
            'body': 'Review the job description and ensure your CV mirrors its key terminology and requirements.',
            'examples': ['Use exact keywords from the JD in your experience bullets'],
            'priority': 'high',
        }]

    logger.info('Analysis complete: ATS=%d, skills=%d/%d',
                results['ats_score'],
                len(results['skill_match']['matched']),
                len(results['skill_match']['matched']) + len(results['skill_match']['missing']))
    return results


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
