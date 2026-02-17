"""Public job search via JSearch (RapidAPI).

Provides search_jobs() function that queries the JSearch API with caching
to conserve the free-tier rate limit (200 requests/month).

Cache strategy:
- 24-hour TTL on normalized API params (not full user prefs)
- Monthly quota tracking with hard stop at limit
- Shared cache across users with same effective API query
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta

import requests as http_requests

logger = logging.getLogger(__name__)

RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY', '')
JSEARCH_HOST = 'jsearch.p.rapidapi.com'
CACHE_TTL_HOURS = 24
MONTHLY_QUOTA = int(os.environ.get('JSEARCH_MONTHLY_QUOTA', '200'))


# ---------------------------------------------------------------------------
# Quota helpers
# ---------------------------------------------------------------------------

def check_quota(provider='jsearch', limit=None):
    """Check if API calls for the current month are under the quota limit.

    Returns (is_under_limit: bool, calls_made: int, limit: int).
    Fails open (returns True) if the DB lookup fails.
    """
    from models import ApiUsage

    if limit is None:
        limit = MONTHLY_QUOTA

    current_month = datetime.utcnow().strftime('%Y-%m')
    try:
        usage = ApiUsage.query.filter_by(
            month=current_month, provider=provider
        ).first()
        calls = usage.calls_made if usage else 0
        return (calls < limit, calls, limit)
    except Exception as e:
        logger.warning('Quota check failed: %s', e)
        return (True, 0, limit)


def increment_quota(provider='jsearch'):
    """Increment the API call counter for the current month.

    Creates the row if it doesn't exist yet (upsert pattern).
    """
    from models import db, ApiUsage

    current_month = datetime.utcnow().strftime('%Y-%m')
    try:
        usage = ApiUsage.query.filter_by(
            month=current_month, provider=provider
        ).first()
        if usage:
            usage.calls_made += 1
            usage.last_call_at = datetime.utcnow()
        else:
            usage = ApiUsage(
                month=current_month,
                provider=provider,
                calls_made=1,
                last_call_at=datetime.utcnow(),
            )
            db.session.add(usage)
        db.session.commit()
    except Exception as e:
        logger.error('Failed to increment quota: %s', e)
        db.session.rollback()


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def get_cached_search(cache_key):
    """Look up a non-expired cache entry by its SHA-256 hash.

    Returns (result_dict, cache_entry) on hit, or (None, None) on miss.
    """
    from models import JobSearchCache

    try:
        entry = JobSearchCache.query.filter_by(query_hash=cache_key) \
            .filter(JobSearchCache.expires_at > datetime.utcnow()) \
            .first()
        if entry:
            return json.loads(entry.results_json), entry
    except Exception as e:
        logger.warning('Cache lookup failed: %s', e)
    return None, None


def get_stale_cache(cache_key):
    """Look up any cache entry by hash, even if expired.

    Used as a fallback when quota is exceeded.
    Returns (result_dict, cache_entry) or (None, None).
    """
    from models import JobSearchCache

    try:
        entry = JobSearchCache.query.filter_by(query_hash=cache_key).first()
        if entry:
            return json.loads(entry.results_json), entry
    except Exception as e:
        logger.warning('Stale cache lookup failed: %s', e)
    return None, None


def store_search_cache(cache_key, normalized_params, result,
                       ttl_hours=None, page=1, source='jsearch'):
    """Store or update a cache entry for a search result set.

    Upserts: if a row with the same query_hash exists (even expired),
    it gets updated in place.
    """
    from models import db, JobSearchCache

    if ttl_hours is None:
        ttl_hours = CACHE_TTL_HOURS

    try:
        existing = JobSearchCache.query.filter_by(query_hash=cache_key).first()
        if existing:
            existing.results_json = json.dumps(result)
            existing.result_count = len(result.get('jobs', []))
            existing.query_params = json.dumps(normalized_params)
            existing.created_at = datetime.utcnow()
            existing.expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
            existing.page = page
            existing.source = source
        else:
            entry = JobSearchCache(
                query_hash=cache_key,
                query_params=json.dumps(normalized_params),
                results_json=json.dumps(result),
                result_count=len(result.get('jobs', [])),
                expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
                page=page,
                source=source,
            )
            db.session.add(entry)
        db.session.commit()
        logger.info('Stored cache for hash=%s (%d jobs, %dh TTL)',
                     cache_key[:8], len(result.get('jobs', [])), ttl_hours)
    except Exception as e:
        logger.error('Failed to store search cache: %s', e)
        db.session.rollback()


# ---------------------------------------------------------------------------
# Main search function
# ---------------------------------------------------------------------------

def search_jobs(query, location='', employment_type='',
                experience='', page=1, num_pages=1,
                cache_key=None, normalized_params=None):
    """Search for public job listings via JSearch API.

    If cache_key is provided (by the caller that already normalized),
    it's used directly. Otherwise a key is computed from the raw params
    for backward compatibility.

    Returns dict with 'jobs' list and 'total_count'.
    """
    # Build cache key if not provided by caller
    if not cache_key:
        params = {
            'query': query.strip().lower(),
            'location': location.strip().lower(),
            'employment_type': employment_type.strip(),
            'experience': experience.strip(),
            'page': page,
        }
        cache_key = hashlib.sha256(
            json.dumps(params, sort_keys=True).encode()
        ).hexdigest()
        normalized_params = params

    # Check cache first
    cached_result, _ = get_cached_search(cache_key)
    if cached_result:
        logger.info('Cache hit for hash=%s', cache_key[:8])
        return cached_result

    # Validate API key
    if not RAPIDAPI_KEY:
        logger.warning('RAPIDAPI_KEY not set — job search unavailable')
        return {
            'jobs': [],
            'total_count': 0,
            'error': 'Job search is not configured yet. Please set RAPIDAPI_KEY.',
        }

    # Call JSearch API
    headers = {
        'X-RapidAPI-Key': RAPIDAPI_KEY,
        'X-RapidAPI-Host': JSEARCH_HOST,
    }
    api_params = {
        'query': f'{query} in {location}' if location else query,
        'page': str(page),
        'num_pages': str(num_pages),
    }
    if employment_type:
        api_params['employment_types'] = employment_type
    if experience:
        api_params['job_requirements'] = experience

    # Retry once on timeout (JSearch can be slow on first call)
    data = None
    last_error = None
    for attempt in range(2):
        try:
            resp = http_requests.get(
                f'https://{JSEARCH_HOST}/search',
                headers=headers,
                params=api_params,
                timeout=25,
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except http_requests.exceptions.Timeout:
            logger.warning('JSearch API timeout (attempt %d/2)', attempt + 1)
            last_error = 'Job search timed out. Please try again.'
        except http_requests.exceptions.HTTPError as e:
            logger.error('JSearch API HTTP error: %s | params: %s', e, api_params)
            if resp.status_code == 429:
                return {'jobs': [], 'total_count': 0, 'error': 'API rate limit reached. Please try again later.'}
            return {'jobs': [], 'total_count': 0, 'error': f'Job search error: {resp.status_code}'}
        except Exception as e:
            logger.error('JSearch API error: %s', e)
            return {'jobs': [], 'total_count': 0, 'error': str(e)}

    if data is None:
        return {'jobs': [], 'total_count': 0, 'error': last_error or 'Job search failed.'}

    # Normalize results
    jobs = []
    for item in data.get('data', []):
        raw_emp_type = item.get('job_employment_type', '')
        jobs.append({
            'job_id': item.get('job_id', ''),
            'title': item.get('job_title', ''),
            'company': item.get('employer_name', ''),
            'company_logo': item.get('employer_logo', ''),
            'location': _format_location(item),
            'description': (item.get('job_description', '') or '')[:3000],
            'description_snippet': _make_snippet(item.get('job_description', '')),
            'employment_type': _format_employment_type(raw_emp_type),
            'employment_type_raw': raw_emp_type,  # Keep raw for pool storage
            'posted_date': _format_date(item.get('job_posted_at_datetime_utc', '')),
            'posted_date_raw': item.get('job_posted_at_datetime_utc', ''),  # ISO string for pool
            'apply_url': item.get('job_apply_link', ''),
            'is_remote': item.get('job_is_remote', False),
            'salary_min': item.get('job_min_salary'),
            'salary_max': item.get('job_max_salary'),
            'salary_currency': item.get('job_salary_currency', ''),
            'salary_period': item.get('job_salary_period', ''),
        })

    result = {'jobs': jobs, 'total_count': len(jobs)}

    # Cache results
    store_search_cache(cache_key, normalized_params or {}, result, page=page)

    # Increment monthly quota counter
    increment_quota('jsearch')

    # Stock the local job pool with individual records
    _store_jobs_in_pool(jobs, query)

    return result


# ---------------------------------------------------------------------------
# Helpers (formatting)
# ---------------------------------------------------------------------------

def _format_location(item):
    """Format job location from JSearch API response."""
    city = item.get('job_city', '') or ''
    state = item.get('job_state', '') or ''
    country = item.get('job_country', '') or ''
    parts = [p for p in [city, state, country] if p]
    loc = ', '.join(parts)
    if item.get('job_is_remote'):
        loc = f'Remote{" — " + loc if loc else ""}'
    return loc or 'Not specified'


def _make_snippet(description):
    """Create a short snippet from job description."""
    if not description:
        return ''
    text = description.strip()
    if len(text) > 250:
        return text[:247] + '...'
    return text


def _format_employment_type(emp_type):
    """Make employment type human-readable."""
    mapping = {
        'FULLTIME': 'Full-time',
        'PARTTIME': 'Part-time',
        'CONTRACTOR': 'Contract',
        'INTERN': 'Internship',
        'TEMPORARY': 'Temporary',
    }
    return mapping.get(emp_type, emp_type.replace('_', ' ').title() if emp_type else '')


def _format_date(date_str):
    """Format ISO date string to readable format."""
    if not date_str:
        return ''
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        delta = datetime.utcnow() - dt.replace(tzinfo=None)
        if delta.days == 0:
            return 'Today'
        elif delta.days == 1:
            return '1 day ago'
        elif delta.days < 7:
            return f'{delta.days} days ago'
        elif delta.days < 30:
            weeks = delta.days // 7
            return f'{weeks} week{"s" if weeks > 1 else ""} ago'
        else:
            return dt.strftime('%b %d, %Y')
    except (ValueError, AttributeError):
        return date_str[:10] if len(date_str) >= 10 else date_str


# ---------------------------------------------------------------------------
# Multi-source search orchestrator
# ---------------------------------------------------------------------------

def search_jobs_multi(prefs, page=1, force_refresh=False,
                      cache_key=None, normalized_params=None):
    """Search multiple job API providers in parallel and merge results.

    Args:
        prefs: User preferences dict (from JobPreferences.to_dict())
        page: Page number for pagination
        force_refresh: Skip cache if True
        cache_key: Pre-computed cache key
        normalized_params: Normalized API params dict

    Returns:
        dict with 'jobs', 'total_count', 'sources', optional 'error'
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from job_providers import get_active_providers, PROVIDER_PRIORITY

    providers = get_active_providers()
    if not providers:
        return {'jobs': [], 'total_count': 0, 'error': 'No job providers configured.'}

    # Check cache first (skip if force refresh)
    if cache_key and not force_refresh:
        cached_result, _ = get_cached_search(cache_key)
        if cached_result:
            logger.info('Multi-source cache hit for hash=%s', cache_key[:8])
            return cached_result

    # Check quota per provider (main thread — DB access)
    eligible = []
    for p in providers:
        if p.monthly_quota == 0:
            eligible.append(p)  # Unlimited
        else:
            under, calls, limit = check_quota(p.name, p.monthly_quota)
            if under:
                eligible.append(p)
            else:
                logger.info('Provider %s over quota (%d/%d), skipping', p.name, calls, limit)

    if not eligible:
        # All providers exhausted — caller should try pool/stale cache
        return {'jobs': [], 'total_count': 0, 'sources': [],
                'error': 'All job providers have reached their quota limits.'}

    # Build params for each provider (main thread)
    provider_params = {}
    for p in eligible:
        try:
            provider_params[p.name] = p.build_params(prefs)
        except Exception as e:
            logger.warning('Provider %s build_params failed: %s', p.name, e)

    # Fetch from all providers in parallel (worker threads — HTTP only, no DB)
    all_jobs = []
    sources_used = []

    def _fetch_one(provider):
        try:
            params = provider_params.get(provider.name, {})
            jobs = provider.fetch(params, page=page)
            return provider.name, jobs
        except Exception as e:
            logger.warning('Provider %s fetch failed: %s', provider.name, e)
            return provider.name, []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_fetch_one, p): p.name
            for p in eligible
            if p.name in provider_params
        }
        for future in as_completed(futures, timeout=30):
            try:
                name, jobs = future.result(timeout=25)
                if jobs:
                    all_jobs.extend(jobs)
                    sources_used.append(name)
                    logger.info('Provider %s returned %d jobs', name, len(jobs))
            except Exception as e:
                name = futures[future]
                logger.warning('Provider %s timed out or failed: %s', name, e)

    # Increment quota for providers that succeeded (main thread — DB access)
    for name in sources_used:
        provider = next((p for p in eligible if p.name == name), None)
        if provider and provider.monthly_quota > 0:
            increment_quota(name)

    # Deduplicate: primary by job_id, secondary by (title, company)
    seen_ids = set()
    seen_titles = set()
    deduped = []

    # Sort by provider priority (lower = higher priority)
    all_jobs.sort(key=lambda j: PROVIDER_PRIORITY.get(j.get('source', ''), 99))

    for job in all_jobs:
        jid = job.get('job_id', '')
        if jid and jid in seen_ids:
            continue
        # Secondary dedup: same title + company across providers
        title_key = ((job.get('title', '') or '')[:50].lower(),
                     (job.get('company', '') or '').lower())
        if title_key[0] and title_key[1] and title_key in seen_titles:
            continue
        if jid:
            seen_ids.add(jid)
        if title_key[0] and title_key[1]:
            seen_titles.add(title_key)
        deduped.append(job)

    result = {
        'jobs': deduped,
        'total_count': len(deduped),
        'sources': sorted(set(sources_used)),
    }

    # Cache the merged result
    if cache_key:
        store_search_cache(cache_key, normalized_params or {},
                           result, page=page, source='multi')

    # Stock the pool with all new jobs
    query_str = (normalized_params or {}).get('query', '')
    _store_jobs_in_pool(deduped, query_str)

    logger.info('Multi-source search: %d jobs from %s (page %d)',
                len(deduped), sources_used, page)
    return result


# ---------------------------------------------------------------------------
# Job pool storage
# ---------------------------------------------------------------------------

def _store_jobs_in_pool(jobs, query):
    """Upsert individual jobs into the local JobPool for future local search.

    Called after every successful API fetch. Jobs that already exist
    get their fetched_at timestamp refreshed; new jobs are inserted.
    """
    from models import db, JobPool

    if not jobs:
        return

    stored = 0
    for job in jobs:
        try:
            existing = JobPool.query.filter_by(job_id=job['job_id']).first()
            if existing:
                existing.fetched_at = datetime.utcnow()
                continue

            pool_entry = JobPool(
                job_id=job['job_id'],
                title=job.get('title', ''),
                company=job.get('company', ''),
                company_logo=job.get('company_logo', ''),
                location=job.get('location', ''),
                description=job.get('description', ''),
                description_snippet=job.get('description_snippet', ''),
                employment_type=job.get('employment_type_raw', ''),
                employment_type_display=job.get('employment_type', ''),
                posted_date_raw=job.get('posted_date_raw', ''),
                posted_date_display=job.get('posted_date', ''),
                apply_url=job.get('apply_url', ''),
                is_remote=job.get('is_remote', False),
                salary_min=job.get('salary_min'),
                salary_max=job.get('salary_max'),
                salary_currency=job.get('salary_currency', ''),
                salary_period=job.get('salary_period', ''),
                source=job.get('source', 'jsearch'),
                source_query=query[:500] if query else '',
                title_lower=(job.get('title', '') or '').lower(),
                company_lower=(job.get('company', '') or '').lower(),
                description_lower=((job.get('description', '') or '')[:3000]).lower(),
            )
            db.session.add(pool_entry)
            stored += 1
        except Exception:
            continue

    try:
        db.session.commit()
        if stored:
            logger.info('Job pool: stored %d new jobs from query "%s"', stored, query[:50])
    except Exception as e:
        logger.error('Failed to store jobs in pool: %s', e)
        db.session.rollback()
