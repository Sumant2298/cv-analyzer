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

    # If no explicit titles, derive from taxonomy selection
    func_ids = prefs.get('industries', [])      # stores function_id
    rf_ids = prefs.get('functional_areas', [])   # stores role_family_id
    level_id = prefs.get('level', '')

    if not titles and rf_ids and func_ids:
        try:
            from skills_data import TAXONOMY, derive_titles
            func_id = func_ids[0]
            rf_id = rf_ids[0]
            derived = derive_titles(rf_id, level_id, func_id) if level_id else []
            if derived:
                query_parts.append(' OR '.join(f'"{t}"' for t in derived[:3]))
            else:
                # Fallback: use role family keywords
                rf_data = TAXONOMY.get(func_id, {}).get('role_families', {}).get(rf_id, {})
                if rf_data.get('keywords'):
                    query_parts.append(rf_data['keywords'][0])
        except ImportError:
            pass

    # Top 2 skills boost relevance
    skills = prefs.get('skills', [])
    if skills:
        query_parts.append(' '.join(skills[:2]))

    # Include companies (only 1-2, otherwise local filter handles it)
    includes = prefs.get('companies_include', [])
    if len(includes) == 1:
        query_parts.append(includes[0])

    # Function boost keyword (from taxonomy)
    if func_ids:
        try:
            from skills_data import TAXONOMY
            func_data = TAXONOMY.get(func_ids[0], {})
            boost = func_data.get('api_boost_keywords', [])
            if boost:
                query_parts.append(boost[0])
        except ImportError:
            pass

    # Role family keyword for query refinement
    if rf_ids and func_ids:
        try:
            from skills_data import TAXONOMY
            func_data = TAXONOMY.get(func_ids[0], {})
            rf_data = func_data.get('role_families', {}).get(rf_ids[0], {})
            if rf_data.get('keywords'):
                query_parts.append(rf_data['keywords'][0])
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
        'no_experience': 'no_experience',
        'under_3_years': 'under_3_years_experience',
        'more_than_3_years': 'more_than_3_years_experience',
        'under_3_years_experience': 'under_3_years_experience',
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
        if not _passes_company_exclude(job, prefs):
            continue
        if not _passes_company_include(job, prefs):
            continue
        if not _passes_company_size(job, prefs):
            continue
        if not _passes_company_type(job, prefs):
            continue
        if not _passes_skills(job, prefs):
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


def _passes_company_exclude(job: dict, prefs: dict) -> bool:
    excludes = prefs.get('companies_exclude', [])
    if not excludes:
        return True
    company = (job.get('company', '') or '').lower()
    for exc in excludes:
        if exc.lower() in company:
            return False
    return True


def _passes_company_include(job: dict, prefs: dict) -> bool:
    """If 3+ companies in include list, treat as strict filter."""
    includes = prefs.get('companies_include', [])
    if len(includes) < 3:
        return True  # 1-2 companies were pushed to API query
    company = (job.get('company', '') or '').lower()
    return any(inc.lower() in company for inc in includes)


def _passes_company_size(job: dict, prefs: dict) -> bool:
    """Heuristic company size filter — permissive (include if no indicators)."""
    sizes = prefs.get('company_sizes', [])
    if not sizes:
        return True
    desc = (job.get('description', '') or '').lower()
    company = (job.get('company', '') or '').lower()
    text = desc + ' ' + company

    size_keywords = {
        'startup': ['startup', 'early stage', 'seed', 'series a', 'series b', 'small team'],
        'mid_size': ['mid-size', 'midsize', 'growing company', 'series c', 'series d', 'mid size'],
        'enterprise': ['enterprise', 'fortune 500', 'large organization', 'global company', 'large-scale'],
        'mnc': ['mnc', 'multinational', 'global presence', 'offices worldwide', 'fortune'],
    }

    for size in sizes:
        for kw in size_keywords.get(size, []):
            if kw in text:
                return True

    # No indicators found → include job (permissive)
    return True


def _passes_company_type(job: dict, prefs: dict) -> bool:
    """Heuristic company type filter — permissive."""
    types = prefs.get('company_types', [])
    if not types:
        return True
    desc = (job.get('description', '') or '').lower()
    company = (job.get('company', '') or '').lower()
    text = desc + ' ' + company

    type_keywords = {
        'product': ['product company', 'product-based', 'saas', 'platform'],
        'service': ['service company', 'it services', 'outsourcing', 'service-based', 'staffing'],
        'consulting': ['consulting', 'advisory', 'consultancy'],
        'startup': ['startup', 'early-stage', 'seed funded', 'venture backed'],
    }

    for t in types:
        for kw in type_keywords.get(t, []):
            if kw in text:
                return True

    # No indicators → include (permissive)
    return True


def _passes_skills(job: dict, prefs: dict) -> bool:
    """At least one preferred skill must appear in job title + description."""
    skills = prefs.get('skills', [])
    if not skills:
        return True
    desc = (job.get('description', '') or '').lower()
    title = (job.get('title', '') or '').lower()
    text = title + ' ' + desc
    return any(skill.lower() in text for skill in skills)


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
