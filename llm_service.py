"""LLM-powered recruiter insights for CV analysis using Groq (free tier).

This module acts as a **senior technical recruiter** evaluating candidates.
It provides opinionated, actionable feedback — not generic career advice.

Graceful degradation:
- If GROQ_API_KEY is not set, all functions return empty results instantly.
- If the API call fails for any reason, the app continues with NLP-only analysis.
- The groq package is only imported when an API key is present.
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

# ---------------------------------------------------------------------------
# Recruiter persona
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior technical recruiter with 15+ years of hiring experience at top-tier companies (Google, Meta, Amazon, startups). You evaluate candidates the way a real hiring manager would — direct, specific, and focused on what actually moves the needle in a hiring decision.

Your evaluation style:
- You speak like a recruiter in a debrief meeting: confident, specific, no fluff
- You flag real red flags and genuine strengths — not vague platitudes
- You think about ATS compatibility, hiring manager first impressions, and interview readiness
- You give the candidate honest advice they can act on TODAY
- You reference specific things from their CV, not generic templates
- You address the candidate directly using "you/your"

Scoring context:
- 70%+ = Strong candidate, likely gets an interview
- 50-69% = Borderline, needs targeted improvements to stand out
- 30-49% = Significant gaps, major rework needed
- Below 30% = Poor fit for this specific role

GUARDRAILS — You MUST follow these rules:
1. NEVER fabricate skills, experience, or qualifications the candidate doesn't have
2. NEVER suggest lying or misrepresenting background
3. ALWAYS base feedback on actual CV content and real JD requirements
4. Keep suggestions realistic — don't suggest "get 5 years of experience" as a quick fix
5. Focus on PRESENTATION improvements: how to better describe what they already have
6. If skills are genuinely missing, suggest learning paths, not resume tricks
7. Be encouraging but honest — a weak fit is a weak fit, say so diplomatically
8. Return ONLY valid JSON with no markdown formatting"""


def _get_client():
    """Lazy-initialise the Groq client (only imports groq when needed)."""
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_prompt(cv_text: str, jd_text: str, analysis_summary: dict) -> str:
    """Build a structured recruiter-evaluation prompt."""

    cv_truncated = cv_text[:2500]
    jd_truncated = jd_text[:1500]

    matched = ', '.join(analysis_summary.get('matched_skills', [])[:15]) or 'None identified'
    missing = ', '.join(analysis_summary.get('missing_skills', [])[:15]) or 'None identified'
    missing_verbs = ', '.join(analysis_summary.get('missing_verbs', [])[:10]) or 'None'

    score = analysis_summary.get('composite_score', 0)
    exp = analysis_summary.get('experience', {})
    edu = analysis_summary.get('education', {})

    # Determine verdict for recruiter context
    if score >= 70:
        verdict = "STRONG CANDIDATE — likely gets past screening"
    elif score >= 50:
        verdict = "BORDERLINE — needs improvements to stand out"
    elif score >= 30:
        verdict = "BELOW THRESHOLD — significant gaps to address"
    else:
        verdict = "POOR FIT — major rework or different role recommended"

    return f"""Evaluate this candidate as a recruiter making a hiring recommendation.

## Recruiter Assessment Context
Overall Match: {score:.0f}% — {verdict}
Skill Coverage: {analysis_summary.get('skill_score', 0):.0f}%
Verb Alignment: {analysis_summary.get('verb_alignment', 0):.0f}%
Matched Skills: {matched}
Missing Skills: {missing}
Experience: CV shows "{exp.get('cv_value', 'Not specified')}", role requires "{exp.get('jd_value', 'Not specified')}" — {exp.get('match_quality', 'Unknown')}
Education: CV shows "{edu.get('cv_value', 'Not specified')}", role requires "{edu.get('jd_value', 'Not specified')}" — {edu.get('match_quality', 'Unknown')}
Missing Action Verbs: {missing_verbs}

## Job Description:
{jd_truncated}

## Candidate's CV:
{cv_truncated}

## Return this exact JSON structure:
{{
  "profile_summary": "Write 3-5 sentences as a recruiter debrief. Start with your overall hiring recommendation (e.g., 'This is a strong/borderline/weak candidate for this role.'). Then explain WHY — reference specific things from their CV. End with the single most important thing they should do. Be direct and specific, not generic.",

  "quick_match_insights": {{
    "experience": "One specific, recruiter-style sentence about their experience fit. Reference actual years/roles from the CV.",
    "education": "One specific sentence about education alignment. If it meets requirements, say so briefly. If not, say what's expected.",
    "skills": "One sentence about technical skill coverage from a hiring perspective. Name the most critical gap if any.",
    "location": "One sentence about location/remote compatibility."
  }},

  "enhanced_suggestions": [
    {{
      "title": "Short recruiter-style title (5-8 words)",
      "body": "Write as a recruiter coaching the candidate. Be specific about WHAT to change and WHY it matters for getting hired. Reference actual content from their CV. Explain what a hiring manager looks for.",
      "examples": [
        "A specific rewritten bullet point from their CV using: [Strong verb] [specific project/context], [resulting in] [quantified impact]",
        "Another specific rewritten example"
      ]
    }}
  ],

  "working_well": [
    "Specific strength from a recruiter's perspective — reference actual CV content (e.g., 'Your 5 years of Python experience directly matches the core requirement')",
    "Another concrete strength"
  ],

  "needs_improvement": [
    "Specific gap or weakness — be direct about what's missing and why it matters (e.g., 'No mention of AWS anywhere — this is a dealbreaker for this cloud-heavy role')",
    "Another concrete improvement area"
  ],

  "ats_score": 45,

  "skill_gap_tips": {{
    "skill_name": "Practical, recruiter-approved advice: how to demonstrate this skill quickly (certifications, projects, or how to frame existing experience). Keep it to one actionable sentence."
  }}
}}

IMPORTANT:
- Generate 3-5 enhanced_suggestions ranked by hiring impact (most important first)
- Cover top 3-5 missing skills in skill_gap_tips only
- Every example bullet MUST reference something from the candidate's actual background
- working_well: 3-5 genuine strengths this CV has for THIS specific role. Be specific, not generic.
- needs_improvement: 3-5 real weaknesses or gaps. Be honest and direct. Reference actual missing skills/experience.
- ats_score: Estimate 0-100 how likely this CV passes an ATS for this JD. Consider: keyword matches, skill coverage, formatting clarity, action verbs. Be realistic — most unoptimized CVs score 30-50.
- Think: "What would make ME advance this candidate to the next round?"
- Be specific, not generic. No placeholder text.
- Return ONLY valid JSON."""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_llm(prompt: str) -> dict:
    """Call Groq API and parse JSON response."""
    client = _get_client()
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt},
        ],
        temperature=0.4,
        max_tokens=2500,
        response_format={'type': 'json_object'},
        timeout=15.0,
    )
    raw = response.choices[0].message.content
    logger.info('LLM response received: %d chars', len(raw))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_llm_insights(cv_text: str, jd_text: str, results: dict) -> dict:
    """Generate recruiter-style LLM insights for analysis results.

    Returns dict with keys: profile_summary, quick_match_insights,
    enhanced_suggestions, skill_gap_tips.  Returns {} on any failure.
    """
    if not LLM_ENABLED:
        logger.info('LLM disabled (no GROQ_API_KEY set)')
        return {}

    try:
        analysis_summary = {
            'composite_score': results.get('composite_score', 0),
            'matched_skills': results.get('skill_match', {}).get('matched', []),
            'missing_skills': results.get('skill_match', {}).get('missing', []),
            'skill_score': results.get('skill_match', {}).get('skill_score', 0),
            'experience': results.get('quick_match', {}).get('experience', {}),
            'education': results.get('quick_match', {}).get('education', {}),
            'verb_alignment': results.get('experience_analysis', {}).get('verb_alignment', 0),
            'missing_verbs': results.get('experience_analysis', {}).get('missing_action_verbs', []),
        }

        prompt = _build_prompt(cv_text, jd_text, analysis_summary)
        logger.info('Calling Groq LLM (prompt: %d chars, model: %s)', len(prompt), GROQ_MODEL)
        llm_data = _call_llm(prompt)

        # Validate each key independently — partial results are OK
        validated: dict = {}
        if isinstance(llm_data.get('profile_summary'), str):
            validated['profile_summary'] = llm_data['profile_summary']
        if isinstance(llm_data.get('quick_match_insights'), dict):
            validated['quick_match_insights'] = llm_data['quick_match_insights']
        if isinstance(llm_data.get('enhanced_suggestions'), list):
            validated['enhanced_suggestions'] = llm_data['enhanced_suggestions']
        if isinstance(llm_data.get('working_well'), list):
            validated['working_well'] = llm_data['working_well']
        if isinstance(llm_data.get('needs_improvement'), list):
            validated['needs_improvement'] = llm_data['needs_improvement']
        if isinstance(llm_data.get('ats_score'), (int, float)):
            validated['ats_score'] = min(100, max(0, int(llm_data['ats_score'])))
        if isinstance(llm_data.get('skill_gap_tips'), dict):
            validated['skill_gap_tips'] = llm_data['skill_gap_tips']

        logger.info('LLM insights ready: %s', list(validated.keys()))
        return validated

    except Exception as e:
        logger.warning('LLM insights generation failed: %s', e)
        return {}


def extract_jd_top_skills(jd_text: str) -> list[dict]:
    """Ask the LLM to identify the top skill categories from a JD.

    Returns a list of category groups:
    [{"category": "Programming Languages", "skills": ["Python", "Java"],
      "importance": "Must-have"}, ...]
    Each category groups related skills together (no duplicates across categories).
    Returns [] if LLM is unavailable or fails.
    """
    if not LLM_ENABLED:
        return []

    try:
        jd_truncated = jd_text[:2000]
        prompt = f"""Analyze this job description and identify the key skill CATEGORIES a recruiter would screen for. Group related skills together.

## Job Description:
{jd_truncated}

## Return JSON with this exact structure:
{{
  "skill_groups": [
    {{
      "category": "Category name (e.g., Programming Languages, Cloud & DevOps, Soft Skills)",
      "skills": ["Specific skill 1", "Specific skill 2"],
      "importance": "Must-have or Nice-to-have"
    }}
  ]
}}

RULES:
- Return 4-7 skill groups, ordered by importance (most critical first)
- Each group should have 1-4 specific skills inside it
- ALWAYS group related skills together:
  * All programming languages (Python, Java, C++, Go) → one "Programming Languages" group
  * All soft skills (Leadership, Communication, Collaboration, Teamwork) → one "Soft Skills" group
  * All cloud/infra tools (AWS, Docker, Kubernetes, Terraform) → one "Cloud & DevOps" group
  * All databases (MongoDB, PostgreSQL, Redis) → one "Databases" group
  * All frameworks (React, Django, Spring) → one "Frameworks" group
- NEVER list individual skills as separate categories — they MUST be grouped
- "Software Development" and "Code Review" are NOT skills — skip generic terms
- Must-have = explicitly required or repeated in JD
- Nice-to-have = preferred, bonus, or mentioned once
- Be specific: "Python" not "programming", "AWS" not "cloud"
- Return ONLY valid JSON"""

        client = _get_client()
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {'role': 'system', 'content': 'You are a technical recruiter. Group related skills into categories. Never list individual skills as separate groups. Return only valid JSON.'},
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.2,
            max_tokens=800,
            response_format={'type': 'json_object'},
            timeout=10.0,
        )
        raw = response.choices[0].message.content
        data = json.loads(raw)
        groups = data.get('skill_groups', [])

        # Validate structure
        validated = []
        for g in groups[:7]:
            if isinstance(g, dict) and g.get('category') and isinstance(g.get('skills'), list):
                skills = [s for s in g['skills'] if isinstance(s, str) and s.strip()][:4]
                if skills:
                    validated.append({
                        'category': g['category'],
                        'skills': skills,
                        'importance': g.get('importance', 'Must-have'),
                    })
        logger.info('LLM extracted %d skill groups with %d total skills',
                     len(validated), sum(len(g['skills']) for g in validated))
        return validated

    except Exception as e:
        logger.warning('JD top skills extraction failed: %s', e)
        return []


def merge_suggestions(base_suggestions: list, llm_suggestions: list):
    """Replace NLP suggestions with LLM recruiter suggestions.

    When LLM is available, its suggestions are superior because they reference
    the actual CV content. We keep LLM suggestions as the primary list and
    only retain NLP suggestions that cover topics the LLM didn't address.
    """
    if not llm_suggestions:
        return

    # Build set of LLM suggestion titles for dedup
    llm_titles = {s.get('title', '').lower().strip() for s in llm_suggestions if isinstance(s, dict)}

    # Keep only NLP suggestions whose topic isn't covered by LLM
    retained_nlp = []
    for base in base_suggestions:
        base_title = base.get('title', '').lower().strip()
        # Check if any LLM title overlaps meaningfully
        covered = any(
            base_title in lt or lt in base_title
            for lt in llm_titles
        )
        if not covered and base.get('type') in ('missing_skills', 'missing_verbs'):
            # Keep data-driven NLP suggestions as lower priority backup
            base['priority'] = 'low'
            retained_nlp.append(base)

    # Clear and rebuild: LLM first, then retained NLP
    base_suggestions.clear()
    for s in llm_suggestions:
        if isinstance(s, dict) and s.get('title'):
            base_suggestions.append({
                'type': 'recruiter_insight',
                'title': s.get('title', ''),
                'body': s.get('body', ''),
                'examples': s.get('examples', []),
                'priority': 'high' if len(base_suggestions) < 2 else 'medium',
            })
    base_suggestions.extend(retained_nlp)
