"""Public job search via JSearch (RapidAPI).

Provides search_jobs() function that queries the JSearch API with caching
to conserve the free-tier rate limit (200 requests/month).
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
CACHE_TTL_HOURS = 6


def search_jobs(query, location='', employment_type='',
                experience='', page=1, num_pages=1):
    """Search for public job listings via JSearch API.

    Returns dict with 'jobs' list and 'total_count'.
    Each job has: job_id, title, company, company_logo, location, description,
                  description_snippet, employment_type, posted_date, apply_url,
                  is_remote, salary_min, salary_max, salary_currency, salary_period.
    """
    from models import db, JobSearchCache

    # Build cache key from search parameters
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

    # Check cache first
    try:
        cached = JobSearchCache.query.filter_by(query_hash=cache_key)\
            .filter(JobSearchCache.expires_at > datetime.utcnow()).first()
        if cached:
            logger.info('Job search cache hit for hash=%s', cache_key[:8])
            return json.loads(cached.results_json)
    except Exception as e:
        logger.warning('Cache lookup failed: %s', e)

    # Call JSearch API
    if not RAPIDAPI_KEY:
        logger.warning('RAPIDAPI_KEY not set — job search unavailable')
        return {
            'jobs': [],
            'total_count': 0,
            'error': 'Job search is not configured yet. Please set RAPIDAPI_KEY.',
        }

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

    try:
        resp = http_requests.get(
            f'https://{JSEARCH_HOST}/search',
            headers=headers,
            params=api_params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except http_requests.exceptions.Timeout:
        logger.error('JSearch API timeout')
        return {'jobs': [], 'total_count': 0, 'error': 'Job search timed out. Please try again.'}
    except http_requests.exceptions.HTTPError as e:
        logger.error('JSearch API HTTP error: %s | params: %s', e, api_params)
        if resp.status_code == 429:
            return {'jobs': [], 'total_count': 0, 'error': 'API rate limit reached. Please try again later.'}
        return {'jobs': [], 'total_count': 0, 'error': f'Job search error: {resp.status_code}'}
    except Exception as e:
        logger.error('JSearch API error: %s', e)
        return {'jobs': [], 'total_count': 0, 'error': str(e)}

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

    # Cache results (blob cache for exact query replay)
    try:
        cache_entry = JobSearchCache(
            query_hash=cache_key,
            query_params=json.dumps(params),
            results_json=json.dumps(result),
            result_count=len(jobs),
            expires_at=datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS),
        )
        db.session.add(cache_entry)
        db.session.commit()
        logger.info('Cached %d job results for hash=%s', len(jobs), cache_key[:8])
    except Exception as e:
        logger.error('Failed to cache job search results: %s', e)
        db.session.rollback()

    # Stock the local job pool with individual records
    _store_jobs_in_pool(jobs, query)

    return result


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
