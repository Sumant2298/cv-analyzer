"""AI Mock Interview Service — LLM orchestration for interview sessions.

Uses Gemini 2.5 Flash via multi-turn conversation to conduct mock interviews
with adaptive follow-ups, persona-driven behavior, and structured feedback.
"""

import json
import logging

from llm_service import _call_llm_chat, get_last_call_stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Question count by duration
# ---------------------------------------------------------------------------

def get_expected_question_count(duration_minutes: int) -> int:
    """Map interview duration to expected question count."""
    if duration_minutes <= 15:
        return 5
    if duration_minutes <= 30:
        return 8
    return 11


# ---------------------------------------------------------------------------
# System Prompt Builder
# ---------------------------------------------------------------------------

_PERSONA_DESCRIPTIONS = {
    'friendly': (
        'You are warm, supportive, and encouraging. Use phrases like '
        '"That\'s a great point" and "I appreciate you sharing that." '
        'If the candidate struggles, offer gentle hints or rephrase. '
        'Your tone is like a helpful senior colleague.'
    ),
    'neutral': (
        'You are professional, balanced, and fair. Neither overly warm '
        'nor cold. You give clear, direct questions and listen attentively. '
        'Standard corporate interview style.'
    ),
    'tough': (
        'You are direct, challenging, and push for depth. Ask pointed '
        'follow-ups like "Can you be more specific?" or "Why not approach X '
        'instead?" Press for concrete numbers and results. You are respectful '
        'but demanding — like a senior VP who values precision.'
    ),
}


def build_system_prompt(target_role: str, interview_type: str,
                        difficulty: str, persona: str,
                        duration_minutes: int, resume_text: str = None,
                        jd_text: str = None) -> str:
    """Build the AI interviewer system prompt."""
    persona_desc = _PERSONA_DESCRIPTIONS.get(persona, _PERSONA_DESCRIPTIONS['neutral'])

    technical_instructions = ''
    if interview_type in ('technical', 'mixed'):
        technical_instructions = """
TECHNICAL / CODING QUESTIONS:
- For technical interviews, include 2-3 coding problems appropriate for the role.
- When asking a coding question, set "requires_code": true and "code_language": "python" (or the most relevant language).
- Coding questions should test data structures, algorithms, or system design depending on difficulty.
- easy: Simple array/string manipulation, basic data structures.
- medium: Hash maps, trees, dynamic programming, BFS/DFS.
- hard: Complex DP, graph algorithms, system design tradeoffs.
- When evaluating code answers, check: correctness, time/space complexity, code quality, edge case handling.
- Also include verbal technical questions (system design, architecture concepts) — these do NOT need requires_code.
"""

    cv_context = ''
    if resume_text:
        truncated_cv = resume_text[:3000]
        cv_context = f"""
CANDIDATE'S RESUME/CV:
{truncated_cv}

CV-BASED INSTRUCTIONS:
- Tailor your questions to the candidate's actual experience from their CV.
- Ask about specific projects, roles, skills, and achievements mentioned in their resume.
- Probe gaps in experience or areas where the CV is vague.
- At least 40% of your questions should directly reference their CV content.
- Compare their stated experience against what the {target_role} role typically requires.
- For technical candidates, ask about technologies and tools listed on their resume.
"""

    jd_context = ''
    if jd_text:
        truncated_jd = jd_text[:3000]
        jd_context = f"""
JOB DESCRIPTION:
{truncated_jd}

JD-BASED INSTRUCTIONS:
- Tailor your questions to the specific requirements and responsibilities in this job description.
- Ask questions that assess the skills, qualifications, and experience the JD demands.
- Evaluate the candidate's fit for this specific role based on JD requirements.
- At least 30% of your questions should directly relate to the JD content.
"""

    return f"""You are an experienced interviewer named Priya conducting a {interview_type} interview for the role of **{target_role}**. Difficulty level: {difficulty}.

PERSONA:
{persona_desc}
{cv_context}
{jd_context}
INTERVIEW STRUCTURE:
1. Start with a brief introduction (who you are, the interview format) and a warm-up question.
2. This is a {duration_minutes}-minute interview. Ask questions naturally based on the conversation flow. Decide when to move to a new topic versus asking a follow-up based on the depth and quality of the candidate's answers.
3. Include follow-up questions when the candidate's answer is vague, incomplete, or particularly interesting.
4. For behavioral questions, notice if the candidate uses STAR format (Situation, Task, Action, Result) — if not, gently guide them.
5. End with "Do you have any questions for me?" as the final question. Use your judgment on when the interview has covered enough ground.
6. Match difficulty to: easy = standard questions, accept shorter answers; medium = expect structured answers with examples; hard = curveball questions, deep probing, challenge assumptions.
{technical_instructions}
QUESTION DISTRIBUTION for {interview_type}:
- behavioral: Leadership, teamwork, conflict resolution, failure/success stories, motivation
- technical: Coding problems, system design, architecture, technical knowledge, debugging scenarios
- hr: Tell me about yourself, strengths/weaknesses, why this role, salary expectations, work style
- case: Business scenarios, market sizing, problem-solving frameworks, analytical thinking
- mixed: Blend of behavioral + technical + situational questions

CRITICAL RULES:
- Ask ONE question at a time. Never ask multiple questions in one turn.
- Keep your spoken message concise (2-4 sentences max for the question itself).
- Vary your question types — don't repeat the same style twice in a row.
- Reference the candidate's previous answers to make follow-ups feel natural.
- When this is a follow-up to a vague answer, set "is_follow_up": true.

RESPONSE FORMAT — you MUST return ONLY a JSON object:
{{
    "interviewer_message": "Your spoken words to the candidate (natural, conversational tone)",
    "question_type": "warmup|behavioral|technical|situational|coding|follow_up|closing",
    "is_follow_up": false,
    "is_final_question": false,
    "requires_code": false,
    "code_language": null,
    "brief_feedback": {{
        "score": 0,
        "strengths": [],
        "improvements": [],
        "star_analysis": {{"situation": false, "task": false, "action": false, "result": false}}
    }}
}}

FEEDBACK RULES for "brief_feedback":
- Score the PREVIOUS answer (0-100). Set score to 0 for the very first question (no answer yet).
- "strengths": 1-2 short bullet points about what was good.
- "improvements": 1-2 short bullet points about what could be better.
- "star_analysis": Check which STAR components were present (for behavioral answers only; set all false for non-behavioral).
- Be honest but constructive in feedback.
"""


# ---------------------------------------------------------------------------
# Start Interview
# ---------------------------------------------------------------------------

def start_interview(session, resume_text: str = None, jd_text: str = None) -> dict:
    """Generate the interviewer's opening message and first question.

    Args:
        session: InterviewSession model object with setup params populated.
        resume_text: Optional extracted text from candidate's resume/CV.
        jd_text: Optional job description text for tailored questions.

    Returns:
        dict with keys: interviewer_message, question_type, requires_code, etc.
    """
    system_prompt = build_system_prompt(
        target_role=session.target_role,
        interview_type=session.interview_type,
        difficulty=session.difficulty,
        persona=session.persona,
        duration_minutes=session.duration_minutes,
        resume_text=resume_text,
        jd_text=jd_text,
    )

    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': '[The interview begins. The candidate is seated and ready. Introduce yourself and ask your first question.]'},
    ]

    result = _call_llm_chat(messages, max_tokens=1000, temperature=0.6, timeout=30.0)

    # Ensure required fields have defaults
    result.setdefault('interviewer_message', 'Hello! I am Priya, and I will be your interviewer today.')
    result.setdefault('question_type', 'warmup')
    result.setdefault('is_follow_up', False)
    result.setdefault('is_final_question', False)
    result.setdefault('requires_code', False)
    result.setdefault('code_language', None)
    result.setdefault('brief_feedback', {'score': 0, 'strengths': [], 'improvements': []})

    return result


# ---------------------------------------------------------------------------
# Process Answer & Get Next Question
# ---------------------------------------------------------------------------

def process_answer(session, exchanges: list, answer_text: str,
                   code_text: str | None = None, resume_text: str = None) -> dict:
    """Process a candidate's answer and generate the next interviewer response.

    Args:
        session: InterviewSession model object.
        exchanges: List of InterviewExchange objects (ordered by sequence).
        answer_text: The candidate's spoken/typed answer.
        code_text: Optional code submission for technical questions.
        resume_text: Optional extracted text from candidate's resume/CV.

    Returns:
        dict with: interviewer_message, question_type, brief_feedback, etc.
    """
    system_prompt = build_system_prompt(
        target_role=session.target_role,
        interview_type=session.interview_type,
        difficulty=session.difficulty,
        persona=session.persona,
        duration_minutes=session.duration_minutes,
        resume_text=resume_text,
    )

    # Reconstruct conversation history
    messages = [{'role': 'system', 'content': system_prompt}]

    # First message that started the interview
    messages.append({
        'role': 'user',
        'content': '[The interview begins. The candidate is seated and ready. Introduce yourself and ask your first question.]',
    })

    for ex in exchanges:
        # Interviewer's question
        messages.append({
            'role': 'assistant',
            'content': json.dumps({
                'interviewer_message': ex.question_text,
                'question_type': 'question',
                'brief_feedback': json.loads(ex.feedback_json) if ex.feedback_json else {'score': 0},
            }),
        })
        # Candidate's answer (if answered)
        if ex.answer_text:
            ans = ex.answer_text
            if ex.code_text:
                ans += f'\n\n[CODE SUBMISSION]\n```\n{ex.code_text}\n```'
            messages.append({'role': 'user', 'content': ans})

    # Add the new answer
    new_ans = answer_text
    if code_text:
        new_ans += f'\n\n[CODE SUBMISSION]\n```\n{code_text}\n```'
    messages.append({'role': 'user', 'content': new_ans})

    # Soft hint to wrap up when enough questions have been asked
    current_q = len(exchanges) + 1
    if current_q >= 6:
        messages.append({
            'role': 'user',
            'content': f'[SYSTEM NOTE: This is question {current_q}. The interview has been going for a while. '
                       f'If you feel the conversation has covered enough ground, you may wrap up with your '
                       f'closing question ("Do you have any questions for me?"). Set is_final_question to true '
                       f'when you ask your closing question. Use your judgment on when to end.]',
        })

    result = _call_llm_chat(messages, max_tokens=1000, temperature=0.5, timeout=25.0)

    # Ensure defaults
    result.setdefault('interviewer_message', 'Thank you for that answer. Let me ask you another question.')
    result.setdefault('question_type', 'behavioral')
    result.setdefault('is_follow_up', False)
    result.setdefault('is_final_question', False)
    result.setdefault('requires_code', False)
    result.setdefault('code_language', None)
    result.setdefault('brief_feedback', {'score': 50, 'strengths': [], 'improvements': []})

    return result


# ---------------------------------------------------------------------------
# Generate Final Feedback Report
# ---------------------------------------------------------------------------

_FEEDBACK_SYSTEM = """You are an expert interview coach analyzing a completed mock interview transcript.
Generate comprehensive, actionable feedback.

You MUST respond with ONLY a JSON object in this exact format:
{
    "overall_score": <int 0-100>,
    "summary": "<2-3 sentence overall assessment>",
    "dimensions": {
        "communication": {
            "score": <int 0-100>,
            "feedback": "<2-3 sentences>",
            "tips": ["<actionable tip 1>", "<actionable tip 2>"]
        },
        "content_depth": {
            "score": <int 0-100>,
            "feedback": "<2-3 sentences>",
            "tips": ["<tip>", "<tip>"]
        },
        "structure": {
            "score": <int 0-100>,
            "feedback": "<2-3 sentences about STAR format usage, logical flow, conciseness>",
            "tips": ["<tip>", "<tip>"]
        },
        "technical_accuracy": {
            "score": <int 0-100>,
            "feedback": "<2-3 sentences>",
            "tips": ["<tip>", "<tip>"]
        },
        "problem_solving": {
            "score": <int 0-100>,
            "feedback": "<2-3 sentences about analytical thinking, approach to problems>",
            "tips": ["<tip>", "<tip>"]
        },
        "confidence_presence": {
            "score": <int 0-100>,
            "feedback": "<2-3 sentences about confidence, clarity, engagement>",
            "tips": ["<tip>", "<tip>"]
        }
    },
    "top_strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
    "key_improvements": ["<improvement 1>", "<improvement 2>", "<improvement 3>"],
    "per_question_feedback": [
        {
            "question": "<the interviewer's question text>",
            "answer_summary": "<1-2 sentence summary of candidate's answer>",
            "score": <int 0-100>,
            "strengths": ["<point>"],
            "improvements": ["<point>"],
            "sample_answer": "<A model strong answer for this question (3-5 sentences)>",
            "star_analysis": {"situation": <bool>, "task": <bool>, "action": <bool>, "result": <bool>},
            "code_review": null
        }
    ]
}

For coding questions, populate code_review:
{
    "code_review": {
        "correctness": "<correct/partially correct/incorrect>",
        "time_complexity": "<e.g. O(n log n)>",
        "space_complexity": "<e.g. O(n)>",
        "optimal_solution": "<brief optimal code or approach description>",
        "improvements": ["<code improvement 1>", "<code improvement 2>"]
    }
}

SCORING GUIDE:
- 90-100: Exceptional — hire-level performance
- 75-89: Strong — minor improvements needed
- 60-74: Adequate — clear areas for growth
- 40-59: Below average — significant practice needed
- 0-39: Needs major improvement

Be honest, specific, and constructive. Reference actual content from the candidate's answers."""


def generate_final_feedback(session, exchanges: list) -> dict:
    """Generate comprehensive post-interview feedback report.

    Args:
        session: InterviewSession model object.
        exchanges: List of InterviewExchange objects with answers populated.

    Returns:
        dict with overall_score, dimensions, per_question_feedback, etc.
    """
    # Build the transcript
    transcript_parts = [
        f'Interview for: {session.target_role}',
        f'Type: {session.interview_type} | Difficulty: {session.difficulty} | '
        f'Duration: {session.duration_minutes} min\n',
    ]

    for ex in exchanges:
        transcript_parts.append(f'INTERVIEWER (Q{ex.sequence}): {ex.question_text}')
        if ex.answer_text:
            transcript_parts.append(f'CANDIDATE: {ex.answer_text}')
            if ex.code_text:
                transcript_parts.append(f'CANDIDATE CODE:\n```\n{ex.code_text}\n```')
        else:
            transcript_parts.append('CANDIDATE: [No answer provided]')
        transcript_parts.append('')

    transcript = '\n'.join(transcript_parts)

    messages = [
        {'role': 'system', 'content': _FEEDBACK_SYSTEM},
        {'role': 'user', 'content': f'Please analyze this interview transcript and provide detailed feedback:\n\n{transcript}'},
    ]

    try:
        # Railway proxy timeout is ~60-90s. Use 45s timeout, NO retries (_retries=0)
        # so this returns in <50s instead of 60×3=180s that would cause 504.
        result = _call_llm_chat(messages, max_tokens=4000, temperature=0.3,
                                timeout=45.0, _retries=0)
    except Exception as e:
        logger.error('Final feedback LLM call failed: %s', e)
        result = {
            'overall_score': 0,
            'summary': 'Feedback generation encountered an error. Your interview data has been saved.',
            'dimensions': {},
            'top_strengths': [],
            'key_improvements': ['Feedback could not be generated. Please try again later.'],
            'per_question_feedback': [],
        }

    # Ensure required fields
    result.setdefault('overall_score', 50)
    result.setdefault('summary', 'Interview completed.')
    result.setdefault('dimensions', {})
    result.setdefault('top_strengths', [])
    result.setdefault('key_improvements', [])
    result.setdefault('per_question_feedback', [])

    return result
