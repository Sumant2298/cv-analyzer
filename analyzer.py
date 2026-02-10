"""CV-vs-JD analysis — fully powered by LLM.

All analysis (skill extraction, matching, scoring, experience evaluation,
keyword extraction, recruiter insights) is performed by the LLM in a single
call via llm_service.analyze_with_llm().
"""

import logging

from llm_service import analyze_with_llm

logger = logging.getLogger(__name__)


def analyze_cv_against_jd(cv_text: str, jd_text: str) -> dict:
    """Run full analysis pipeline via LLM. Returns structured results dict."""
    logger.info('Starting LLM-powered analysis (CV: %d chars, JD: %d chars)',
                len(cv_text), len(jd_text))
    return analyze_with_llm(cv_text, jd_text)
