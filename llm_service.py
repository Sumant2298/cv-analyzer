"""LLM-powered CV analysis using Groq.

This module performs ALL analysis via the LLM — no NLP libraries needed.
A single comprehensive LLM call extracts skills, scores, matches, and
generates recruiter insights.

Graceful degradation:
- If GROQ_API_KEY is not set, returns empty results.
- If the API call fails, the app shows an error message.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
LLM_ENABLED = bool(GROQ_API_KEY)

_groq_client = None


def _get_client():
    """Lazy-initialise the Groq client."""
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior technical recruiter with 15+ years of hiring experience at top-tier companies (Google, Meta, Amazon, startups). You evaluate candidates the way a real hiring manager would — direct, specific, and focused on what actually moves the needle in a hiring decision.

Your evaluation style:
- You speak like a recruiter in a debrief meeting: confident, specific, no fluff
- You flag real red flags and genuine strengths — not vague platitudes
- You think about ATS compatibility, hiring manager first impressions, and interview readiness
- You give the candidate honest advice they can act on TODAY
- You reference specific things from their CV, not generic templates
- You address the candidate directly using "you/your"

GUARDRAILS:
1. NEVER fabricate skills, experience, or qualifications the candidate doesn't have
2. NEVER suggest lying or misrepresenting background
3. ALWAYS base feedback on actual CV content and real JD requirements
4. Focus on PRESENTATION improvements: how to better describe what they already have
5. If skills are genuinely missing, suggest learning paths, not resume tricks
6. Be encouraging but honest — a weak fit is a weak fit, say so diplomatically
7. Return ONLY valid JSON with no markdown formatting"""


# ---------------------------------------------------------------------------
# Comprehensive analysis prompt
# ---------------------------------------------------------------------------

def _build_analysis_prompt(cv_text: str, jd_text: str) -> str:
    """Build the single comprehensive analysis prompt."""
    cv_truncated = cv_text[:4000]
    jd_truncated = jd_text[:3000]

    return f"""You are performing a COMPLETE analysis of a candidate's CV against a job description. You must extract ALL information and provide ALL scoring in a single response.

## Job Description:
{jd_truncated}

## Candidate's CV:
{cv_truncated}

## Return this EXACT JSON structure (every field is required):
{{
  "ats_score": 45,

  "quick_match": {{
    "experience": {{
      "cv_value": "5 years",
      "jd_value": "3+ years",
      "match_quality": "Strong Match"
    }},
    "education": {{
      "cv_value": "Bachelors",
      "jd_value": "Bachelors",
      "match_quality": "Strong Match"
    }},
    "skills": {{
      "cv_value": "12/17 key skills",
      "jd_value": "17 required",
      "match_quality": "Good Match"
    }},
    "location": {{
      "cv_value": "Remote",
      "jd_value": "Remote",
      "match_quality": "Strong Match"
    }}
  }},

  "skill_match": {{
    "matched": ["Python", "React", "AWS"],
    "missing": ["Kubernetes", "Terraform"],
    "extra": ["Vue.js", "Redis"],
    "skill_score": 70.5,
    "matched_by_category": {{
      "Programming Languages": ["Python", "JavaScript"],
      "Cloud & DevOps": ["AWS", "Docker"]
    }},
    "missing_by_category": {{
      "Cloud & DevOps": ["Kubernetes", "Terraform"]
    }},
    "extra_by_category": {{
      "Databases": ["Redis"]
    }},
    "category_breakdown": {{
      "Programming Languages": {{
        "matched": ["Python", "JavaScript"],
        "missing": ["Go"],
        "score": 66.7
      }},
      "Cloud & DevOps": {{
        "matched": ["AWS", "Docker"],
        "missing": ["Kubernetes", "Terraform"],
        "score": 50.0
      }}
    }}
  }},

  "top_skill_groups": [
    {{
      "category": "Programming Languages",
      "importance": "Must-have",
      "skills": [
        {{"skill": "Python", "found": true}},
        {{"skill": "Go", "found": false}}
      ],
      "matched": 1,
      "total": 2
    }}
  ],

  "experience_analysis": {{
    "verb_alignment": 55.0,
    "common_action_verbs": ["develop", "manage", "implement", "design"],
    "missing_action_verbs": ["architect", "scale", "optimize"],
    "section_relevance": [
      {{"section": "Professional Experience", "relevance": 65.0}},
      {{"section": "Education", "relevance": 40.0}}
    ]
  }},

  "profile_summary": "You are a strong/borderline/weak candidate for this role. (3-5 sentences in 2nd person addressing the candidate directly.)",

  "working_well": [
    "Specific strength referencing actual CV content"
  ],

  "needs_improvement": [
    "Specific gap referencing actual missing skills/experience"
  ],

  "suggestions": [
    {{
      "type": "recruiter_insight",
      "title": "Short recruiter-style title (5-8 words)",
      "body": "Specific coaching advice referencing their CV",
      "examples": ["Specific rewritten bullet point example"],
      "priority": "high"
    }}
  ],

  "skill_gap_tips": {{
    "Kubernetes": "Take the CKA certification — it's the fastest way to demonstrate K8s competence to hiring managers."
  }},

  "jd_keywords": ["keyword1", "keyword2", "keyword3"],
  "cv_keywords": ["keyword1", "keyword2", "keyword3"]
}}

## DETAILED INSTRUCTIONS FOR EACH FIELD:

**ats_score** (0-100): How likely this CV passes an ATS for this JD. Consider keyword matches, skill coverage, formatting clarity, action verbs. Be realistic — most unoptimized CVs score 30-50.

**quick_match**: Extract REAL values from the CV and JD:
- experience: Extract actual years from CV (look for "X years of experience" or count date ranges). Extract requirements from JD. match_quality: "Strong Match" if CV >= JD, "Good Match" if close, "Weak Match" if significantly under, "Not specified" if can't determine.
- education: Extract highest degree from CV and required degree from JD. Same match_quality logic.
- skills: Count how many JD-required skills appear in CV. Format cv_value as "X/Y key skills".
- location: Extract location/remote info from both. "Strong Match" for remote jobs or matching locations.

**skill_match**: Thoroughly scan BOTH documents:
- matched: Skills that appear in BOTH CV and JD (be thorough — check aliases like "JS"/"JavaScript", "K8s"/"Kubernetes")
- missing: Skills in JD but NOT in CV
- extra: Skills in CV but NOT in JD
- skill_score: (matched count / total JD skills) * 100
- Group all skills by category (Programming Languages, Frameworks, Databases, Cloud & DevOps, Data & ML, Testing, Soft Skills, Tools, etc.)
- category_breakdown: For each category, list matched and missing skills with percentage score

**top_skill_groups**: 6-8 skill categories from the JD, ordered by importance. For each skill, indicate whether it was found in the CV. Group related skills (all languages together, all cloud tools together, etc.)

**experience_analysis**:
- verb_alignment: Estimate what % of JD action verbs (develop, manage, lead, etc.) appear in CV
- common_action_verbs: Verbs found in both CV and JD
- missing_action_verbs: Important verbs in JD but not in CV
- section_relevance: For each CV section (Experience, Education, Skills, Projects, etc.), estimate 0-100 how relevant it is to this JD

**profile_summary**: 3-5 sentences in 2nd person (you/your). Start with overall assessment, explain WHY with specific CV references, end with the single most important thing to do.

**working_well**: 3-5 genuine strengths for THIS specific role. Be specific, reference actual CV content.

**needs_improvement**: 3-5 real weaknesses or gaps. Be honest and direct. Reference actual missing skills/experience.

**suggestions**: 3-5 prioritized improvement suggestions. First 2 should be "high" priority, rest "medium". Each must have specific examples referencing the candidate's actual background.

**skill_gap_tips**: For top 3-5 missing skills ONLY. One actionable sentence each — certifications, projects, or how to frame existing experience.

**jd_keywords**: Top 15-20 important keywords/phrases from the JD (technical terms, tools, methodologies).
**cv_keywords**: Top 15-20 important keywords/phrases from the CV.

CRITICAL:
- Be THOROUGH when scanning for skills — check the ENTIRE CV and JD
- Use realistic scores — don't inflate
- Every piece of feedback must reference actual content from the CV or JD
- Return ONLY valid JSON, no markdown"""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_llm(prompt: str, system: str = None, max_tokens: int = 4000,
              temperature: float = 0.3, timeout: float = 30.0) -> dict:
    """Call Groq API and parse JSON response."""
    client = _get_client()
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {'role': 'system', 'content': system or SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={'type': 'json_object'},
        timeout=timeout,
    )
    raw = response.choices[0].message.content
    logger.info('LLM response received: %d chars', len(raw))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_with_llm(cv_text: str, jd_text: str) -> dict:
    """Run the full CV-vs-JD analysis using a single LLM call.

    Returns a fully structured results dict ready for the template,
    or raises an exception on failure.
    """
    if not LLM_ENABLED:
        raise RuntimeError('LLM is not configured (GROQ_API_KEY not set)')

    prompt = _build_analysis_prompt(cv_text, jd_text)
    logger.info('Calling Groq LLM for full analysis (prompt: %d chars, model: %s)',
                len(prompt), GROQ_MODEL)

    llm_data = _call_llm(prompt, max_tokens=4000, temperature=0.3, timeout=30.0)

    # ---------------------------------------------------------------------------
    # Validate and normalise the response
    # ---------------------------------------------------------------------------
    results = {}

    # ATS score
    ats = llm_data.get('ats_score', 40)
    results['ats_score'] = min(100, max(0, int(ats))) if isinstance(ats, (int, float)) else 40

    # Quick match
    qm = llm_data.get('quick_match', {})
    results['quick_match'] = {}
    for key in ('experience', 'education', 'skills', 'location'):
        dim = qm.get(key, {})
        results['quick_match'][key] = {
            'cv_value': str(dim.get('cv_value', 'Not specified')),
            'jd_value': str(dim.get('jd_value', 'Not specified')),
            'match_quality': str(dim.get('match_quality', 'Good Match')),
        }

    # Skill match
    sm = llm_data.get('skill_match', {})
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

    # Top skill groups
    tsg = llm_data.get('top_skill_groups', [])
    results['top_skill_groups'] = _normalise_top_skill_groups(tsg)

    # Update quick match skills display from top skill groups
    if results['top_skill_groups']:
        total = sum(g['total'] for g in results['top_skill_groups'])
        found = sum(g['matched'] for g in results['top_skill_groups'])
        results['quick_match']['skills']['cv_value'] = f'{found}/{total} key skills'

    # Experience analysis
    ea = llm_data.get('experience_analysis', {})
    results['experience_analysis'] = {
        'verb_alignment': _ensure_float(ea.get('verb_alignment', 0)),
        'common_action_verbs': _ensure_list(ea.get('common_action_verbs', [])),
        'missing_action_verbs': _ensure_list(ea.get('missing_action_verbs', [])),
        'section_relevance': _normalise_section_relevance(ea.get('section_relevance', [])),
    }

    # Composite / TF-IDF placeholders (template expects these)
    skill_score = results['skill_match']['skill_score']
    verb_score = results['experience_analysis']['verb_alignment']
    results['tfidf_score'] = results['ats_score']  # Use ATS as similarity proxy
    results['composite_score'] = round(
        results['ats_score'] * 0.5 + skill_score * 0.3 + verb_score * 0.2, 1
    )

    # LLM insights (profile summary, working well, needs improvement, etc.)
    results['llm_insights'] = {}
    if isinstance(llm_data.get('profile_summary'), str):
        results['llm_insights']['profile_summary'] = llm_data['profile_summary']
    if isinstance(llm_data.get('working_well'), list):
        results['llm_insights']['working_well'] = [s for s in llm_data['working_well'] if isinstance(s, str)]
    if isinstance(llm_data.get('needs_improvement'), list):
        results['llm_insights']['needs_improvement'] = [s for s in llm_data['needs_improvement'] if isinstance(s, str)]
    if isinstance(llm_data.get('skill_gap_tips'), dict):
        results['llm_insights']['skill_gap_tips'] = llm_data['skill_gap_tips']
    results['llm_insights']['ats_score'] = results['ats_score']

    # Suggestions
    raw_suggestions = llm_data.get('suggestions', [])
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

    # Keywords (simple lists for template)
    jd_kw = llm_data.get('jd_keywords', [])
    cv_kw = llm_data.get('cv_keywords', [])
    results['jd_keywords'] = [{'phrase': k, 'score': 1.0} for k in jd_kw if isinstance(k, str)]
    results['cv_keywords'] = [{'phrase': k, 'score': 1.0} for k in cv_kw if isinstance(k, str)]

    # Categorized keywords for template
    results['jd_keywords_categorized'] = _categorize_keywords_from_skills(
        results['jd_keywords'], results['skill_match'].get('matched_by_category', {}),
        results['skill_match'].get('missing_by_category', {}))
    results['cv_keywords_categorized'] = _categorize_keywords_from_skills(
        results['cv_keywords'], results['skill_match'].get('matched_by_category', {}),
        results['skill_match'].get('extra_by_category', {}))

    # Legacy fields the template might reference
    results['jd_skills'] = results['skill_match'].get('matched_by_category', {})
    results['cv_skills'] = results['skill_match'].get('matched_by_category', {})

    logger.info('Full LLM analysis complete: ATS=%d, skills=%d/%d',
                results['ats_score'],
                len(results['skill_match']['matched']),
                len(results['skill_match']['matched']) + len(results['skill_match']['missing']))

    return results


# ---------------------------------------------------------------------------
# Validation / normalisation helpers
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
                skills.append({
                    'skill': str(s['skill']),
                    'found': bool(s.get('found', False)),
                })
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
    sections = []
    for s in raw:
        if isinstance(s, dict) and s.get('section'):
            sections.append({
                'section': str(s['section']),
                'relevance': _ensure_float(s.get('relevance', 0)),
            })
    return sections


def _categorize_keywords_from_skills(keywords: list, *category_dicts) -> dict:
    """Group flat keyword list into categories using skill match data."""
    if not keywords:
        return {}

    # Build lookup: skill → category
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
        phrase_lower = phrase.lower()
        cat = skill_to_cat.get(phrase_lower)
        if cat:
            categorized.setdefault(cat, []).append(kw)
        else:
            other.append(kw)

    if other:
        categorized['Other'] = other[:10]

    return categorized
