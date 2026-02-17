"""Multi-source job search provider abstraction layer.

Each provider implements a common interface that normalizes API responses
to the canonical job dict format used throughout the application.

Providers auto-register based on environment variable configuration.
"""

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

import requests as http_requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def make_snippet(description, max_len=250):
    """Create a short snippet from job description."""
    if not description:
        return ''
    text = description.strip()
    if len(text) > max_len:
        return text[:max_len - 3] + '...'
    return text


def format_date(date_str):
    """Format ISO date string to readable relative format."""
    if not date_str:
        return ''
    try:
        # Handle various formats
        cleaned = date_str.replace('Z', '+00:00')
        # Try ISO format
        dt = datetime.fromisoformat(cleaned)
        delta = datetime.utcnow() - dt.replace(tzinfo=None)
        if delta.days < 0:
            return 'Today'
        elif delta.days == 0:
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
        # Try parsing date-only format
        try:
            dt = datetime.strptime(date_str[:10], '%Y-%m-%d')
            delta = datetime.utcnow() - dt
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


def format_employment_type(emp_type):
    """Make employment type human-readable."""
    if not emp_type:
        return ''
    mapping = {
        'FULLTIME': 'Full-time',
        'PARTTIME': 'Part-time',
        'CONTRACTOR': 'Contract',
        'INTERN': 'Internship',
        'TEMPORARY': 'Temporary',
        'full_time': 'Full-time',
        'part_time': 'Part-time',
        'contract': 'Contract',
        'freelance': 'Freelance',
        'internship': 'Internship',
    }
    return mapping.get(emp_type, emp_type.replace('_', ' ').title())


def strip_html(html_str):
    """Strip HTML tags from a string, returning plain text."""
    if not html_str:
        return ''
    # Remove HTML tags
    text = re.sub(r'<br\s*/?>', '\n', html_str)
    text = re.sub(r'</(p|div|li|h[1-6])>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _build_search_query(prefs):
    """Build a search query string from user preferences.

    Shared across providers that accept keyword queries.
    Returns a query string like 'Marketing Manager' or '"recruiter" OR "talent acquisition"'.
    """
    titles = prefs.get('job_titles', [])
    if titles:
        return titles[0]

    func_ids = prefs.get('industries', [])
    rf_ids = prefs.get('functional_areas', [])

    if rf_ids and func_ids:
        try:
            from skills_data import TAXONOMY
            func_id = func_ids[0]
            rf_id = rf_ids[0]
            rf_data = TAXONOMY.get(func_id, {}).get('role_families', {}).get(rf_id, {})
            keywords = rf_data.get('keywords', [])
            if keywords:
                return keywords[0] if len(keywords) == 1 else f'{keywords[0]} {keywords[1]}'
        except ImportError:
            pass

    if func_ids:
        try:
            from skills_data import TAXONOMY
            func_data = TAXONOMY.get(func_ids[0], {})
            label = func_data.get('label', '')
            if label:
                return label
        except ImportError:
            pass

    return 'software developer'


def _get_location_from_prefs(prefs):
    """Get the primary location from user preferences."""
    locations = prefs.get('locations', [])
    if not locations:
        return ''
    loc = locations[0]
    # Add India suffix for API queries
    if loc and ', India' not in loc and loc.lower() not in ('remote',):
        return f'{loc}, India'
    return loc


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class JobProvider(ABC):
    """Abstract base class for all job API providers."""

    name: str = ''
    display_name: str = ''
    monthly_quota: int = 0        # 0 = unlimited
    cache_ttl_hours: int = 24

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if required env vars are set."""

    @abstractmethod
    def build_params(self, prefs: dict) -> dict:
        """Convert user prefs to provider-specific API parameters."""

    @abstractmethod
    def fetch(self, params: dict, page: int = 1) -> list:
        """Call the API and return a list of normalized job dicts."""

    def get_quota_limit(self):
        """Return the monthly quota limit for this provider."""
        return self.monthly_quota


# ---------------------------------------------------------------------------
# JSearch Provider (existing primary source)
# ---------------------------------------------------------------------------

class JSearchProvider(JobProvider):
    name = 'jsearch'
    display_name = 'JSearch'
    monthly_quota = int(os.environ.get('JSEARCH_MONTHLY_QUOTA', '200'))
    cache_ttl_hours = 24

    def is_configured(self):
        return bool(os.environ.get('RAPIDAPI_KEY'))

    def build_params(self, prefs):
        from job_filter import build_jsearch_params
        return build_jsearch_params(prefs)

    def fetch(self, params, page=1):
        api_key = os.environ.get('RAPIDAPI_KEY', '')
        host = 'jsearch.p.rapidapi.com'

        headers = {
            'X-RapidAPI-Key': api_key,
            'X-RapidAPI-Host': host,
        }
        query = params.get('query', '')
        location = params.get('location', '')
        api_params = {
            'query': f'{query} in {location}' if location else query,
            'page': str(page),
            'num_pages': '1',
        }
        if params.get('employment_type'):
            api_params['employment_types'] = params['employment_type']
        if params.get('experience'):
            api_params['job_requirements'] = params['experience']
        if params.get('remote_jobs_only'):
            api_params['remote_jobs_only'] = 'true'

        data = None
        for attempt in range(2):
            try:
                resp = http_requests.get(
                    f'https://{host}/search',
                    headers=headers,
                    params=api_params,
                    timeout=25,
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except http_requests.exceptions.Timeout:
                logger.warning('JSearch timeout (attempt %d/2)', attempt + 1)
            except Exception as e:
                logger.error('JSearch error: %s', e)
                return []

        if not data:
            return []

        jobs = []
        for item in data.get('data', []):
            raw_emp_type = item.get('job_employment_type', '')
            city = item.get('job_city', '') or ''
            state = item.get('job_state', '') or ''
            country = item.get('job_country', '') or ''
            loc_parts = [p for p in [city, state, country] if p]
            loc = ', '.join(loc_parts)
            if item.get('job_is_remote'):
                loc = f'Remote{" — " + loc if loc else ""}'
            loc = loc or 'Not specified'

            desc = (item.get('job_description', '') or '')[:3000]
            jobs.append({
                'job_id': item.get('job_id', ''),
                'title': item.get('job_title', ''),
                'company': item.get('employer_name', ''),
                'company_logo': item.get('employer_logo', ''),
                'location': loc,
                'description': desc,
                'description_snippet': make_snippet(desc),
                'employment_type': format_employment_type(raw_emp_type),
                'employment_type_raw': raw_emp_type,
                'posted_date': format_date(item.get('job_posted_at_datetime_utc', '')),
                'posted_date_raw': item.get('job_posted_at_datetime_utc', ''),
                'apply_url': item.get('job_apply_link', ''),
                'is_remote': item.get('job_is_remote', False),
                'salary_min': item.get('job_min_salary'),
                'salary_max': item.get('job_max_salary'),
                'salary_currency': item.get('job_salary_currency', ''),
                'salary_period': item.get('job_salary_period', ''),
                'source': 'jsearch',
            })

        logger.info('JSearch: fetched %d jobs (page %d)', len(jobs), page)
        return jobs


# ---------------------------------------------------------------------------
# Adzuna Provider
# ---------------------------------------------------------------------------

class AdzunaProvider(JobProvider):
    name = 'adzuna'
    display_name = 'Adzuna'
    monthly_quota = int(os.environ.get('ADZUNA_MONTHLY_QUOTA', '2500'))
    cache_ttl_hours = 24

    def is_configured(self):
        return bool(os.environ.get('ADZUNA_APP_ID') and os.environ.get('ADZUNA_APP_KEY'))

    def build_params(self, prefs):
        query = _build_search_query(prefs)
        location = prefs.get('locations', [''])[0] if prefs.get('locations') else ''

        # Map employment types
        emp_types = prefs.get('employment_types', [])
        contract_time = ''
        if emp_types:
            if 'FULLTIME' in emp_types:
                contract_time = 'full_time'
            elif 'PARTTIME' in emp_types:
                contract_time = 'part_time'
            elif 'CONTRACTOR' in emp_types:
                contract_time = 'contract'

        return {
            'what': query,
            'where': location,
            'contract_time': contract_time,
            'salary_min': prefs.get('salary_min', ''),
            'salary_max': prefs.get('salary_max', ''),
        }

    def fetch(self, params, page=1):
        app_id = os.environ.get('ADZUNA_APP_ID', '')
        app_key = os.environ.get('ADZUNA_APP_KEY', '')

        api_params = {
            'app_id': app_id,
            'app_key': app_key,
            'what': params.get('what', ''),
            'results_per_page': 20,
        }
        if params.get('where'):
            api_params['where'] = params['where']
        if params.get('contract_time'):
            api_params['content-type'] = 'application/json'
            api_params['contract_time'] = params['contract_time']

        try:
            resp = http_requests.get(
                f'https://api.adzuna.com/v1/api/jobs/in/search/{page}',
                params=api_params,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error('Adzuna error: %s', e)
            return []

        jobs = []
        for item in data.get('results', []):
            desc = (item.get('description', '') or '')[:3000]
            title = item.get('title', '')
            is_remote = 'remote' in (title + ' ' + desc).lower()

            jobs.append({
                'job_id': f'adzuna_{item.get("id", "")}',
                'title': title,
                'company': item.get('company', {}).get('display_name', '') if isinstance(item.get('company'), dict) else str(item.get('company', '')),
                'company_logo': '',
                'location': item.get('location', {}).get('display_name', '') if isinstance(item.get('location'), dict) else str(item.get('location', '')),
                'description': desc,
                'description_snippet': make_snippet(desc),
                'employment_type': format_employment_type(item.get('contract_time', '')),
                'employment_type_raw': item.get('contract_time', ''),
                'posted_date': format_date(item.get('created', '')),
                'posted_date_raw': item.get('created', ''),
                'apply_url': item.get('redirect_url', ''),
                'is_remote': is_remote,
                'salary_min': item.get('salary_min'),
                'salary_max': item.get('salary_max'),
                'salary_currency': 'INR',
                'salary_period': 'year',
                'source': 'adzuna',
            })

        logger.info('Adzuna: fetched %d jobs (page %d)', len(jobs), page)
        return jobs


# ---------------------------------------------------------------------------
# Jooble Provider
# ---------------------------------------------------------------------------

class JoobleProvider(JobProvider):
    name = 'jooble'
    display_name = 'Jooble'
    monthly_quota = 0  # Free, no published limit
    cache_ttl_hours = 24

    def is_configured(self):
        return bool(os.environ.get('JOOBLE_API_KEY'))

    def build_params(self, prefs):
        query = _build_search_query(prefs)
        location = prefs.get('locations', [''])[0] if prefs.get('locations') else ''
        if location and 'India' not in location:
            location = f'{location}, India'
        return {'keywords': query, 'location': location}

    def fetch(self, params, page=1):
        api_key = os.environ.get('JOOBLE_API_KEY', '')

        body = {
            'keywords': params.get('keywords', ''),
            'location': params.get('location', ''),
            'page': str(page),
        }

        try:
            resp = http_requests.post(
                f'https://jooble.org/api/{api_key}',
                json=body,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error('Jooble error: %s', e)
            return []

        jobs = []
        for item in data.get('jobs', []):
            snippet = (item.get('snippet', '') or '')
            desc = strip_html(snippet)[:3000]
            title = item.get('title', '')
            is_remote = 'remote' in (title + ' ' + desc).lower()

            # Parse salary string (e.g., "50000 - 80000")
            sal_min, sal_max = self._parse_salary(item.get('salary', ''))

            jobs.append({
                'job_id': f'jooble_{item.get("id", "")}',
                'title': strip_html(title),
                'company': item.get('company', ''),
                'company_logo': '',
                'location': item.get('location', ''),
                'description': desc,
                'description_snippet': make_snippet(desc),
                'employment_type': format_employment_type(item.get('type', '')),
                'employment_type_raw': item.get('type', ''),
                'posted_date': format_date(item.get('updated', '')),
                'posted_date_raw': item.get('updated', ''),
                'apply_url': item.get('link', ''),
                'is_remote': is_remote,
                'salary_min': sal_min,
                'salary_max': sal_max,
                'salary_currency': 'INR',
                'salary_period': 'year',
                'source': 'jooble',
            })

        logger.info('Jooble: fetched %d jobs (page %d)', len(jobs), page)
        return jobs

    @staticmethod
    def _parse_salary(salary_str):
        """Parse Jooble salary string like '50000 - 80000' or '₹50,000'."""
        if not salary_str:
            return None, None
        # Remove currency symbols and commas
        cleaned = re.sub(r'[₹$€£,]', '', str(salary_str))
        nums = re.findall(r'[\d]+', cleaned)
        if len(nums) >= 2:
            return float(nums[0]), float(nums[1])
        elif len(nums) == 1:
            return float(nums[0]), None
        return None, None


# ---------------------------------------------------------------------------
# RemoteOK Provider (bulk catalog, cache in-memory)
# ---------------------------------------------------------------------------

# In-memory catalog cache for bulk APIs
_REMOTE_CATALOG_CACHE = {}
REMOTE_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours


class RemoteOKProvider(JobProvider):
    name = 'remoteok'
    display_name = 'RemoteOK'
    monthly_quota = 0
    cache_ttl_hours = 6

    def is_configured(self):
        return os.environ.get('REMOTEOK_ENABLED', '1') != '0'

    def build_params(self, prefs):
        return {'query': _build_search_query(prefs)}

    def fetch(self, params, page=1):
        # Only fetch on page 1 (RemoteOK returns all jobs at once)
        if page > 1:
            return []

        all_jobs = self._get_catalog()
        if not all_jobs:
            return []

        # Filter by user query keywords
        query = (params.get('query', '') or '').lower()
        query_words = [w for w in query.split() if len(w) > 2]

        if not query_words:
            return all_jobs[:20]

        # Score jobs by keyword relevance
        scored = []
        for job in all_jobs:
            text = (job.get('title', '') + ' ' + job.get('description', '')).lower()
            score = sum(1 for w in query_words if w in text)
            if score > 0:
                scored.append((score, job))

        scored.sort(key=lambda x: -x[0])
        return [job for _, job in scored[:20]]

    def _get_catalog(self):
        """Get cached RemoteOK catalog or fetch fresh."""
        cached = _REMOTE_CATALOG_CACHE.get('remoteok')
        now = datetime.utcnow()
        if cached and (now - cached['fetched_at']).total_seconds() < REMOTE_CACHE_TTL_SECONDS:
            return cached['jobs']

        try:
            resp = http_requests.get(
                'https://remoteok.com/api',
                headers={'User-Agent': 'LevelUpX/1.0'},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error('RemoteOK catalog fetch error: %s', e)
            return cached['jobs'] if cached else []

        jobs = []
        for item in data:
            # First element is legal notice, skip non-job items
            if not isinstance(item, dict) or 'position' not in item:
                continue

            desc_html = item.get('description', '')
            desc = strip_html(desc_html)[:3000]

            jobs.append({
                'job_id': f'remoteok_{item.get("id", "")}',
                'title': item.get('position', ''),
                'company': item.get('company', ''),
                'company_logo': item.get('logo', '') or item.get('company_logo', '') or '',
                'location': item.get('location', '') or 'Remote',
                'description': desc,
                'description_snippet': make_snippet(desc),
                'employment_type': 'Full-time',
                'employment_type_raw': 'FULLTIME',
                'posted_date': format_date(item.get('date', '')),
                'posted_date_raw': item.get('date', ''),
                'apply_url': item.get('apply_url', '') or item.get('url', ''),
                'is_remote': True,
                'salary_min': item.get('salary_min'),
                'salary_max': item.get('salary_max'),
                'salary_currency': 'USD',
                'salary_period': 'year',
                'source': 'remoteok',
            })

        _REMOTE_CATALOG_CACHE['remoteok'] = {
            'jobs': jobs,
            'fetched_at': now,
        }
        logger.info('RemoteOK: cached %d remote jobs', len(jobs))
        return jobs


# ---------------------------------------------------------------------------
# Remotive Provider (bulk catalog, cache in-memory)
# ---------------------------------------------------------------------------

class RemotiveProvider(JobProvider):
    name = 'remotive'
    display_name = 'Remotive'
    monthly_quota = 0
    cache_ttl_hours = 6

    # Remotive category mapping
    _CATEGORY_MAP = {
        'software': 'software-dev',
        'engineering': 'software-dev',
        'developer': 'software-dev',
        'data': 'data',
        'analytics': 'data',
        'design': 'design',
        'ui': 'design',
        'ux': 'design',
        'marketing': 'marketing',
        'sales': 'sales',
        'product': 'product',
        'customer': 'customer-support',
        'hr': 'hr',
        'human resources': 'hr',
        'finance': 'finance-legal',
        'legal': 'finance-legal',
        'devops': 'devops-sysadmin',
        'writing': 'writing',
        'content': 'writing',
        'qa': 'qa',
        'testing': 'qa',
    }

    def is_configured(self):
        return os.environ.get('REMOTIVE_ENABLED', '1') != '0'

    def build_params(self, prefs):
        query = _build_search_query(prefs)
        # Try to map to a Remotive category
        category = ''
        for word in query.lower().split():
            if word in self._CATEGORY_MAP:
                category = self._CATEGORY_MAP[word]
                break
        return {'search': query, 'category': category}

    def fetch(self, params, page=1):
        if page > 1:
            return []

        all_jobs = self._get_catalog(params)
        if not all_jobs:
            return []

        # Filter by search query
        query = (params.get('search', '') or '').lower()
        query_words = [w for w in query.split() if len(w) > 2]

        if not query_words:
            return all_jobs[:20]

        scored = []
        for job in all_jobs:
            text = (job.get('title', '') + ' ' + job.get('description', '')).lower()
            score = sum(1 for w in query_words if w in text)
            if score > 0:
                scored.append((score, job))

        scored.sort(key=lambda x: -x[0])
        return [job for _, job in scored[:20]]

    def _get_catalog(self, params):
        """Get cached Remotive catalog or fetch fresh."""
        cache_key = f'remotive_{params.get("category", "")}'
        cached = _REMOTE_CATALOG_CACHE.get(cache_key)
        now = datetime.utcnow()
        if cached and (now - cached['fetched_at']).total_seconds() < REMOTE_CACHE_TTL_SECONDS:
            return cached['jobs']

        api_params = {'limit': 100}
        if params.get('category'):
            api_params['category'] = params['category']
        if params.get('search'):
            api_params['search'] = params['search']

        try:
            resp = http_requests.get(
                'https://remotive.com/api/remote-jobs',
                params=api_params,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error('Remotive catalog fetch error: %s', e)
            return cached['jobs'] if cached else []

        jobs = []
        for item in data.get('jobs', []):
            desc_html = item.get('description', '')
            desc = strip_html(desc_html)[:3000]

            # Parse salary string
            sal_min, sal_max = self._parse_salary(item.get('salary', ''))

            jobs.append({
                'job_id': f'remotive_{item.get("id", "")}',
                'title': item.get('title', ''),
                'company': item.get('company_name', ''),
                'company_logo': item.get('company_logo', '') or '',
                'location': item.get('candidate_required_location', '') or 'Remote',
                'description': desc,
                'description_snippet': make_snippet(desc),
                'employment_type': format_employment_type(item.get('job_type', '')),
                'employment_type_raw': item.get('job_type', ''),
                'posted_date': format_date(item.get('publication_date', '')),
                'posted_date_raw': item.get('publication_date', ''),
                'apply_url': item.get('url', ''),
                'is_remote': True,
                'salary_min': sal_min,
                'salary_max': sal_max,
                'salary_currency': 'USD',
                'salary_period': 'year',
                'source': 'remotive',
            })

        _REMOTE_CATALOG_CACHE[cache_key] = {
            'jobs': jobs,
            'fetched_at': now,
        }
        logger.info('Remotive: cached %d remote jobs (category=%s)',
                     len(jobs), params.get('category', 'all'))
        return jobs

    @staticmethod
    def _parse_salary(salary_str):
        """Parse Remotive salary like '50000-70000 USD' or '$50k - $70k'."""
        if not salary_str:
            return None, None
        cleaned = re.sub(r'[$€£,]', '', str(salary_str).lower())
        # Handle 'k' suffix (e.g., '50k')
        cleaned = re.sub(r'(\d+)k', lambda m: str(int(m.group(1)) * 1000), cleaned)
        nums = re.findall(r'[\d]+', cleaned)
        if len(nums) >= 2:
            return float(nums[0]), float(nums[1])
        elif len(nums) == 1:
            return float(nums[0]), None
        return None, None


# ---------------------------------------------------------------------------
# Provider Registry
# ---------------------------------------------------------------------------

# Priority order: higher priority providers win in deduplication
PROVIDER_PRIORITY = {
    'jsearch': 1,
    'adzuna': 2,
    'jooble': 3,
    'remoteok': 4,
    'remotive': 5,
}

PROVIDERS: dict = {}


def _init_providers():
    """Initialize all configured providers."""
    for cls in [JSearchProvider, AdzunaProvider, JoobleProvider,
                RemoteOKProvider, RemotiveProvider]:
        provider = cls()
        if provider.is_configured():
            PROVIDERS[provider.name] = provider
            logger.info('Job provider enabled: %s', provider.display_name)
        else:
            logger.info('Job provider skipped (not configured): %s', provider.display_name)


_init_providers()


def get_active_providers() -> list:
    """Return list of currently enabled and configured providers."""
    return list(PROVIDERS.values())


def get_provider(name: str):
    """Return a specific provider by name, or None."""
    return PROVIDERS.get(name)
