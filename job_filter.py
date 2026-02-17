"""Translation layer: user preferences → JSearch API params + local filters.

Handles three responsibilities:
1. build_jsearch_params() — map canonical filters to JSearch-supported query params
2. apply_local_filters()  — apply filters NOT supported by JSearch on fetched results
3. search_from_pool()     — search local JobPool table before hitting the API
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Build JSearch API parameters from user preferences
# ---------------------------------------------------------------------------

def build_jsearch_params(prefs: dict) -> dict:
    """Convert user preferences dict to JSearch API query params.

    Only includes parameters that JSearch actually supports.
    Uses the canonical TAXONOMY (Function → Role Family → Level) for
    keyword lookups and title derivation when explicit job_titles are empty.
    Returns a dict suitable for passing to search_jobs().
    """
    query_parts = []

    # --- Job titles (primary search terms) ---
    titles = prefs.get('job_titles', [])
    if titles:
        if len(titles) == 1:
            query_parts.append(titles[0])
        else:
            query_parts.append(' OR '.join(f'"{t}"' for t in titles[:3]))

    # If no explicit titles, build query from taxonomy selection
    func_ids = prefs.get('industries', [])      # stores function_id
    rf_ids = prefs.get('functional_areas', [])   # stores role_family_id
    level_id = prefs.get('level', '')

    if not titles and rf_ids and func_ids:
        try:
            from skills_data import TAXONOMY
            func_id = func_ids[0]
            rf_id = rf_ids[0]
            rf_data = TAXONOMY.get(func_id, {}).get('role_families', {}).get(rf_id, {})
            # Use role family keywords as primary search (e.g. "recruiter", "talent acquisition")
            keywords = rf_data.get('keywords', [])
            if keywords:
                # Use top 2 keywords as OR query for breadth
                if len(keywords) >= 2:
                    query_parts.append(f'"{keywords[0]}" OR "{keywords[1]}"')
                else:
                    query_parts.append(keywords[0])
        except ImportError:
            pass

    # If still no query parts and we have a function, use function label
    if not query_parts and func_ids:
        try:
            from skills_data import TAXONOMY
            func_data = TAXONOMY.get(func_ids[0], {})
            label = func_data.get('label', '')
            if label:
                query_parts.append(label)
        except ImportError:
            pass

    query = ' '.join(query_parts).strip()
    if not query:
        query = 'software developer'  # Fallback default

    # --- Location (first preferred location) ---
    locations = prefs.get('locations', [])
    location = locations[0] if locations else ''

    # --- Employment types ---
    emp_types = prefs.get('employment_types', [])
    employment_type = ','.join(emp_types) if emp_types else ''

    # --- Experience level (map UI values to JSearch API values) ---
    exp_map = {
        'fresher': 'no_experience',
        'no_experience': 'no_experience',
        '0_3_years': 'under_3_years_experience',
        'under_3_years_experience': 'under_3_years_experience',
        '3_8_years': 'more_than_3_years_experience',
        '8_15_years': 'more_than_3_years_experience',
        '15_plus_years': 'more_than_3_years_experience',
        'more_than_3_years_experience': 'more_than_3_years_experience',
        'no_degree': 'no_degree',
    }
    experience = prefs.get('experience_level', 'any')
    experience = exp_map.get(experience, '') if experience != 'any' else ''

    # --- Work mode: remote ---
    work_mode = prefs.get('work_mode', 'any')

    params = {
        'query': query,
        'location': location,
        'employment_type': employment_type,
        'experience': experience,
    }

    # Add remote_jobs_only if remote mode selected
    if work_mode == 'remote':
        params['remote_jobs_only'] = True

    return params


# ---------------------------------------------------------------------------
# 2. Apply local filters (non-API-supported)
# ---------------------------------------------------------------------------

def apply_local_filters(jobs: List[dict], prefs: dict) -> List[dict]:
    """Apply filters NOT supported by JSearch API on pre-fetched job data.

    Args:
        jobs: List of job dicts (from search_jobs or JobPool.to_dict).
        prefs: User preferences dict (from JobPreferences.to_dict).

    Returns:
        Filtered list of job dicts.
    """
    filtered = []
    for job in jobs:
        if not _passes_work_mode(job, prefs):
            continue
        if not _passes_location(job, prefs):
            continue
        if not _passes_salary(job, prefs):
            continue
        if not _passes_functional_areas(job, prefs):
            continue
        filtered.append(job)
    return filtered


def _passes_work_mode(job: dict, prefs: dict) -> bool:
    mode = prefs.get('work_mode', 'any')
    if mode == 'any':
        return True
    if mode == 'remote':
        return job.get('is_remote', False)
    if mode == 'onsite':
        return not job.get('is_remote', False)
    if mode == 'hybrid':
        desc = (job.get('description', '') or '').lower()
        title = (job.get('title', '') or '').lower()
        return 'hybrid' in desc or 'hybrid' in title
    return True


def _passes_location(job: dict, prefs: dict) -> bool:
    """Check remaining locations (beyond the first one sent to API)."""
    locations = prefs.get('locations', [])
    if len(locations) <= 1:
        return True  # First location already pushed to API
    job_loc = (job.get('location', '') or '').lower()
    # Job matches if it contains ANY of the preferred locations
    for loc in locations:
        if loc.lower() in job_loc:
            return True
    return False


def _passes_salary(job: dict, prefs: dict) -> bool:
    """Filter by salary range in INR. Jobs without salary always pass."""
    user_min = prefs.get('salary_min')
    user_max = prefs.get('salary_max')
    if not user_min and not user_max:
        return True

    job_min = job.get('salary_min')
    job_max = job.get('salary_max')
    if job_min is None and job_max is None:
        return True  # No salary data → always include

    # Currency conversion (rough FX rates to INR)
    job_currency = (job.get('salary_currency', '') or '').upper()
    fx_rates = {'USD': 83, 'EUR': 90, 'GBP': 105, 'INR': 1, '': 1}
    fx = fx_rates.get(job_currency, 83)  # Default to USD rate

    # Annualize job salary
    job_period = (job.get('salary_period', '') or '').lower()
    jmin = (job_min or 0) * fx
    jmax = (job_max or jmin) * fx
    if 'month' in job_period:
        jmin *= 12
        jmax *= 12
    elif 'hour' in job_period:
        jmin *= 2080  # 40h × 52w
        jmax *= 2080

    # Annualize user salary
    user_period = prefs.get('salary_period', 'annual')
    umin = user_min or 0
    umax = user_max or float('inf')
    if user_period == 'monthly':
        umin *= 12
        umax = umax * 12 if umax != float('inf') else float('inf')

    # Range overlap check
    if umin and jmax and jmax < umin:
        return False
    if umax != float('inf') and jmin and jmin > umax:
        return False
    return True


def _passes_functional_areas(job: dict, prefs: dict) -> bool:
    """Check if job matches preferred role family (permissive).

    Uses taxonomy-driven keyword lookup instead of hardcoded dict.
    """
    rf_ids = prefs.get('functional_areas', [])
    if not rf_ids:
        return True

    func_ids = prefs.get('industries', [])
    desc = (job.get('description', '') or '').lower()
    title = (job.get('title', '') or '').lower()
    text = title + ' ' + desc

    try:
        from skills_data import TAXONOMY
        for rf_id in rf_ids:
            # Search across specified function or all functions
            search_funcs = [func_ids[0]] if func_ids else list(TAXONOMY.keys())
            for fid in search_funcs:
                func_data = TAXONOMY.get(fid, {})
                rf_data = func_data.get('role_families', {}).get(rf_id, {})
                for kw in rf_data.get('keywords', []):
                    if kw.lower() in text:
                        return True
    except ImportError:
        pass

    # No match → include (permissive for role families)
    return True


# ---------------------------------------------------------------------------
# 3. Search from local JobPool before hitting API
# ---------------------------------------------------------------------------

def search_from_pool(prefs: dict, min_results: int = 8, max_age_days: int = 7) -> Optional[List[dict]]:
    """Search the local JobPool table using SQL queries.

    Returns list of job dicts if enough results found, else None
    (meaning the caller should fall back to API).
    """
    from models import db, JobPool

    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    query = JobPool.query.filter(JobPool.fetched_at > cutoff)

    # Apply SQL-level filters for job titles
    titles = prefs.get('job_titles', [])
    if titles:
        title_conditions = []
        for t in titles:
            title_conditions.append(JobPool.title_lower.contains(t.lower()))
        query = query.filter(db.or_(*title_conditions))

    # Employment types
    emp_types = prefs.get('employment_types', [])
    if emp_types:
        query = query.filter(JobPool.employment_type.in_(emp_types))

    # Work mode (SQL-level for remote/onsite)
    work_mode = prefs.get('work_mode', 'any')
    if work_mode == 'remote':
        query = query.filter(JobPool.is_remote == True)
    elif work_mode == 'onsite':
        query = query.filter(JobPool.is_remote == False)

    # Locations (SQL LIKE on any)
    locations = prefs.get('locations', [])
    if locations:
        loc_conditions = [JobPool.location.ilike(f'%{loc}%') for loc in locations]
        query = query.filter(db.or_(*loc_conditions))

    # Order by recency, fetch up to 50
    query = query.order_by(JobPool.fetched_at.desc())
    pool_jobs = query.limit(50).all()

    if len(pool_jobs) < min_results:
        logger.info('Job pool: only %d results (need %d), falling back to API',
                     len(pool_jobs), min_results)
        return None

    # Convert to dicts and apply remaining local filters
    job_dicts = [j.to_dict() for j in pool_jobs]
    filtered = apply_local_filters(job_dicts, prefs)

    if len(filtered) < min_results:
        logger.info('Job pool: %d after local filters (need %d), falling back to API',
                     len(filtered), min_results)
        return None

    logger.info('Job pool hit: returning %d jobs from local pool', len(filtered))
    return filtered


# ---------------------------------------------------------------------------
# Cache key normalization
# ---------------------------------------------------------------------------

def normalize_api_params_for_cache(prefs: dict, page: int = 1) -> tuple:
    """Normalize JSearch API params from user prefs and produce a stable cache key.

    Calls build_jsearch_params() internally, then normalizes the output
    (lowercase, sorted arrays, stripped whitespace) so that equivalent
    queries always produce the same SHA-256 hash.

    Returns (normalized_params_dict, sha256_cache_key_hex).
    """
    import hashlib
    import json

    api_params = build_jsearch_params(prefs)

    normalized = {
        'query': api_params.get('query', '').strip().lower(),
        'location': api_params.get('location', '').strip().lower(),
        'employment_type': ','.join(sorted(
            t.strip() for t in api_params.get('employment_type', '').split(',') if t.strip()
        )),
        'experience': api_params.get('experience', '').strip().lower(),
        'remote_jobs_only': api_params.get('remote_jobs_only', False),
        'page': page,
    }

    cache_key = hashlib.sha256(
        json.dumps(normalized, sort_keys=True).encode()
    ).hexdigest()

    return normalized, cache_key
