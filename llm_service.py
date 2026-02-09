"""LLM-powered insights for CV analysis using Groq (free tier).

This module is designed for graceful degradation:
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
    """Build a single structured prompt that returns all LLM insights as JSON."""

    cv_truncated = cv_text[:2000]
    jd_truncated = jd_text[:1500]

    matched = ', '.join(analysis_summary.get('matched_skills', [])[:15]) or 'None'
    missing = ', '.join(analysis_summary.get('missing_skills', [])[:15]) or 'None'
    missing_verbs = ', '.join(analysis_summary.get('missing_verbs', [])[:10]) or 'None'

    exp = analysis_summary.get('experience', {})
    edu = analysis_summary.get('education', {})

    return f"""You are an expert career advisor and resume consultant. Analyze the following CV against the job description and the pre-computed analysis data. Return ONLY valid JSON with no markdown formatting.

## Job Description (truncated):
{jd_truncated}

## CV (truncated):
{cv_truncated}

## Pre-computed Analysis:
- Overall Match Score: {analysis_summary.get('composite_score', 0):.0f}%
- Skill Match Score: {analysis_summary.get('skill_score', 0):.0f}%
- Matched Skills: {matched}
- Missing Skills: {missing}
- Experience: CV has "{exp.get('cv_value', 'Not specified')}", JD requires "{exp.get('jd_value', 'Not specified')}" — {exp.get('match_quality', 'Unknown')}
- Education: CV has "{edu.get('cv_value', 'Not specified')}", JD requires "{edu.get('jd_value', 'Not specified')}" — {edu.get('match_quality', 'Unknown')}
- Action Verb Alignment: {analysis_summary.get('verb_alignment', 0):.0f}%
- Missing Action Verbs: {missing_verbs}

## Return this exact JSON structure:
{{
  "profile_summary": "Write 3-4 sentences as an executive summary of how this candidate fits the role. Be specific about their strengths and gaps. Use a professional recruiter tone. Address the candidate directly using 'you/your'.",
  "quick_match_insights": {{
    "experience": "One actionable sentence about the experience match",
    "education": "One actionable sentence about the education match",
    "skills": "One actionable sentence about skills coverage",
    "location": "One actionable sentence about location compatibility"
  }},
  "enhanced_suggestions": [
    {{
      "title": "Short suggestion title (5-8 words)",
      "body": "A contextual paragraph explaining this improvement area based on the actual CV and JD content. Be specific, not generic.",
      "examples": [
        "A specific resume bullet point example following: [Action verb] [specific task/project] [resulting in] [measurable outcome]",
        "Another specific example bullet point"
      ]
    }}
  ],
  "skill_gap_tips": {{
    "skill_name": "One-liner actionable recommendation for acquiring or demonstrating this skill"
  }}
}}

IMPORTANT RULES:
- For enhanced_suggestions, generate 3-5 of the most impactful improvements.
- For skill_gap_tips, cover the top 3-5 missing skills only.
- All resume bullet examples MUST follow: "[Action verb] [specific project/task], resulting in [measurable outcome]"
- Be specific to this candidate's background — reference their actual experience when possible.
- Return ONLY valid JSON. No markdown code blocks, no explanation text outside JSON."""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_llm(prompt: str) -> dict:
    """Call Groq API and parse JSON response. Raises on failure."""
    client = _get_client()
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                'role': 'system',
                'content': 'You are a career advisor. Return only valid JSON.'
            },
            {
                'role': 'user',
                'content': prompt
            },
        ],
        temperature=0.3,
        max_tokens=2000,
        response_format={'type': 'json_object'},
        timeout=10.0,
    )
    raw = response.choices[0].message.content
    logger.info('LLM response received: %d chars', len(raw))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_llm_insights(cv_text: str, jd_text: str, results: dict) -> dict:
    """Generate LLM-enhanced insights for the analysis results.

    Returns a dict with keys: profile_summary, quick_match_insights,
    enhanced_suggestions, skill_gap_tips.  Returns {} on any failure.
    """
    if not LLM_ENABLED:
        return {}

    try:
        # Build a compact analysis summary for the prompt
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
        logger.info('Calling LLM for insights (prompt: %d chars)', len(prompt))
        llm_data = _call_llm(prompt)

        # Validate each key independently — partial results are OK
        validated: dict = {}
        if isinstance(llm_data.get('profile_summary'), str):
            validated['profile_summary'] = llm_data['profile_summary']
        if isinstance(llm_data.get('quick_match_insights'), dict):
            validated['quick_match_insights'] = llm_data['quick_match_insights']
        if isinstance(llm_data.get('enhanced_suggestions'), list):
            validated['enhanced_suggestions'] = llm_data['enhanced_suggestions']
        if isinstance(llm_data.get('skill_gap_tips'), dict):
            validated['skill_gap_tips'] = llm_data['skill_gap_tips']

        logger.info('LLM insights generated: %s', list(validated.keys()))
        return validated

    except Exception as e:
        logger.warning('LLM insights generation failed: %s', e)
        return {}


def merge_suggestions(base_suggestions: list, llm_suggestions: list):
    """Override base suggestion body/examples with LLM-generated content.

    Matches by title (case-insensitive). Unmatched LLM suggestions are
    appended as new entries with type='llm_insight'.
    """
    llm_by_title: dict[str, dict] = {}
    for s in llm_suggestions:
        if isinstance(s, dict) and 'title' in s:
            llm_by_title[s['title'].lower().strip()] = s

    # Override matching base suggestions
    for base in base_suggestions:
        key = base.get('title', '').lower().strip()
        if key in llm_by_title:
            llm = llm_by_title.pop(key)
            if 'body' in llm:
                base['body'] = llm['body']
            if isinstance(llm.get('examples'), list) and llm['examples']:
                base['examples'] = llm['examples']

    # Append remaining LLM-only suggestions
    for llm in llm_by_title.values():
        base_suggestions.append({
            'type': 'llm_insight',
            'title': llm.get('title', ''),
            'body': llm.get('body', ''),
            'examples': llm.get('examples', []),
            'priority': 'medium',
        })
