"""Token budget management — centralized prompt templates, truncation, caching, and observability.

Provides:
  - Per-task max_tokens defaults and limits
  - Input truncation helpers (CV, JD text)
  - Prompt hash-based caching (in-memory LRU)
  - Token usage logging per call site
  - Current date injection for system prompts
"""

import hashlib
import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-task token budgets (max_tokens for output)
# ---------------------------------------------------------------------------
# Gemini 2.5 Flash: $0.30/1M input, $2.50/1M output
# Thinking tokens consume part of max_tokens, so budget ~3-4x expected output

TASK_BUDGETS = {
    'cv_only':     {'max_tokens': 4000,  'temperature': 0.3,  'timeout': 90.0},
    'skills':      {'max_tokens': 8000,  'temperature': 0.2,  'timeout': 120.0},
    'recruiter':   {'max_tokens': 6000,  'temperature': 0.25, 'timeout': 120.0},
    'rewrite':     {'max_tokens': 16000, 'temperature': 0.3,  'timeout': 180.0},
    'refine':      {'max_tokens': 2000,  'temperature': 0.3,  'timeout': 30.0},
}

# ---------------------------------------------------------------------------
# Input size limits (chars) — prevents sending unnecessarily large payloads
# ---------------------------------------------------------------------------

INPUT_LIMITS = {
    'cv_text': {
        'cv_only': 5000,
        'skills': 6000,
        'recruiter': 6000,
        'rewrite': 8000,
        'refine_selected': 2000,
        'refine_context': 3000,
    },
    'jd_text': {
        'skills': 4000,
        'recruiter': 4000,
        'rewrite': 3000,
    },
}

# Max payload size before auto-reject (chars, approximate)
MAX_PAYLOAD_CHARS = 25000


# ---------------------------------------------------------------------------
# Current date helper — fixes Gemini thinking it's 2025
# ---------------------------------------------------------------------------

def get_date_context() -> str:
    """Return a date-awareness line to inject into system prompts."""
    now = datetime.now(timezone.utc)
    return f"Today's date is {now.strftime('%B %d, %Y')}. The current year is {now.year}."


# ---------------------------------------------------------------------------
# Text truncation helpers
# ---------------------------------------------------------------------------

def truncate_text(text: str, max_chars: int, label: str = 'text') -> str:
    """Truncate text to max_chars. Logs if truncation occurs."""
    if not text:
        return ''
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    logger.info('Truncated %s: %d → %d chars', label, len(text), max_chars)
    return truncated


def truncate_cv(cv_text: str, task: str) -> str:
    """Truncate CV text according to task-specific limits."""
    limit = INPUT_LIMITS['cv_text'].get(task, 5000)
    return truncate_text(cv_text, limit, f'CV ({task})')


def truncate_jd(jd_text: str, task: str) -> str:
    """Truncate JD text according to task-specific limits."""
    limit = INPUT_LIMITS['jd_text'].get(task, 4000)
    return truncate_text(jd_text, limit, f'JD ({task})')


def truncate_list(items: list, max_items: int) -> list:
    """Truncate a list to max_items."""
    return items[:max_items] if items else []


# ---------------------------------------------------------------------------
# Prompt size guardrail
# ---------------------------------------------------------------------------

def check_payload_size(system: str, prompt: str, task: str) -> None:
    """Warn if payload exceeds threshold. Could auto-summarize in future."""
    total = len(system) + len(prompt)
    if total > MAX_PAYLOAD_CHARS:
        logger.warning('Payload size for %s: %d chars (threshold: %d)',
                       task, total, MAX_PAYLOAD_CHARS)


# ---------------------------------------------------------------------------
# LRU Cache for LLM responses (by normalized input hash)
# ---------------------------------------------------------------------------

class LLMCache:
    """Simple in-memory LRU cache for LLM responses.

    Cache key = hash(system + prompt + model + params).
    Entries expire after `ttl` seconds.
    """

    def __init__(self, max_size: int = 50, ttl: int = 3600):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl
        self._hits = 0
        self._misses = 0

    def _make_key(self, system: str, prompt: str, max_tokens: int,
                  temperature: float) -> str:
        """Create a cache key from normalized inputs."""
        # Normalize: strip whitespace, lower-case system for consistency
        raw = f'{system.strip()}|{prompt.strip()}|{max_tokens}|{temperature}'
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, system: str, prompt: str, max_tokens: int,
            temperature: float) -> dict | None:
        """Look up cached response. Returns None on miss."""
        key = self._make_key(system, prompt, max_tokens, temperature)
        entry = self._cache.get(key)

        if entry is None:
            self._misses += 1
            return None

        # Check TTL
        if time.time() - entry['time'] > self._ttl:
            del self._cache[key]
            self._misses += 1
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        self._hits += 1
        logger.info('Cache HIT (key=%s, hits=%d, misses=%d)',
                    key, self._hits, self._misses)
        return entry['data']

    def put(self, system: str, prompt: str, max_tokens: int,
            temperature: float, data: dict) -> None:
        """Store a response in cache."""
        key = self._make_key(system, prompt, max_tokens, temperature)

        # Evict oldest if at capacity
        while len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)

        self._cache[key] = {'data': data, 'time': time.time()}

    def stats(self) -> dict:
        """Return cache statistics."""
        return {
            'size': len(self._cache),
            'max_size': self._max_size,
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': f'{self._hits / max(1, self._hits + self._misses) * 100:.1f}%',
        }


# Global cache instance
_cache = LLMCache(max_size=50, ttl=3600)


def get_cache() -> LLMCache:
    """Return the global LLM cache instance."""
    return _cache


# ---------------------------------------------------------------------------
# Token usage tracking / observability
# ---------------------------------------------------------------------------

class TokenTracker:
    """Tracks token usage per call site for observability."""

    def __init__(self):
        self._calls: list[dict] = []

    def log_call(self, task: str, input_chars: int, output_chars: int,
                 elapsed_secs: float, cached: bool = False,
                 model: str = '') -> None:
        """Log a single LLM call."""
        # Rough token estimate: ~4 chars per token for English text
        est_input_tokens = input_chars // 4
        est_output_tokens = output_chars // 4
        est_cost_input = est_input_tokens * 0.30 / 1_000_000
        est_cost_output = est_output_tokens * 2.50 / 1_000_000
        est_total_cost = est_cost_input + est_cost_output

        entry = {
            'task': task,
            'timestamp': time.time(),
            'input_chars': input_chars,
            'output_chars': output_chars,
            'est_input_tokens': est_input_tokens,
            'est_output_tokens': est_output_tokens,
            'est_cost_usd': round(est_total_cost, 6),
            'elapsed_secs': round(elapsed_secs, 2),
            'cached': cached,
            'model': model,
        }
        self._calls.append(entry)

        # Keep only last 500 entries
        if len(self._calls) > 500:
            self._calls = self._calls[-500:]

        logger.info(
            'TOKEN_USAGE | task=%s | input=%d chars (~%d tok) | '
            'output=%d chars (~%d tok) | cost=$%.6f | %.1fs | cached=%s',
            task, input_chars, est_input_tokens,
            output_chars, est_output_tokens,
            est_total_cost, elapsed_secs, cached
        )

    def summary(self) -> dict:
        """Return aggregate usage summary."""
        if not self._calls:
            return {'total_calls': 0}

        total_input = sum(c['est_input_tokens'] for c in self._calls)
        total_output = sum(c['est_output_tokens'] for c in self._calls)
        total_cost = sum(c['est_cost_usd'] for c in self._calls)
        cached_count = sum(1 for c in self._calls if c['cached'])

        by_task = {}
        for c in self._calls:
            t = c['task']
            if t not in by_task:
                by_task[t] = {'calls': 0, 'input_tokens': 0,
                              'output_tokens': 0, 'cost_usd': 0.0}
            by_task[t]['calls'] += 1
            by_task[t]['input_tokens'] += c['est_input_tokens']
            by_task[t]['output_tokens'] += c['est_output_tokens']
            by_task[t]['cost_usd'] += c['est_cost_usd']

        return {
            'total_calls': len(self._calls),
            'cached_calls': cached_count,
            'total_input_tokens': total_input,
            'total_output_tokens': total_output,
            'total_cost_usd': round(total_cost, 4),
            'by_task': by_task,
        }


# Global tracker instance
_tracker = TokenTracker()


def get_tracker() -> TokenTracker:
    """Return the global token tracker instance."""
    return _tracker
