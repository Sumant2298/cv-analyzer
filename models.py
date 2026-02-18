"""Database models for LevelUpX — users, credits, transactions."""

from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(256), nullable=False, index=True)
    name = db.Column(db.String(256))
    picture = db.Column(db.String(512))
    analysis_count = db.Column(db.Integer, default=0)
    credits = db.Column(db.Integer, default=0, nullable=False)
    onboarding_completed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)

    transactions = db.relationship('Transaction', backref='user', lazy='dynamic')
    credit_usages = db.relationship('CreditUsage', backref='user', lazy='dynamic')

    def __repr__(self):
        return f'<User {self.email}>'


class Transaction(db.Model):
    """Razorpay payment transaction — tracks credit purchases."""
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    razorpay_order_id = db.Column(db.String(128), unique=True, nullable=False)
    razorpay_payment_id = db.Column(db.String(128))
    razorpay_signature = db.Column(db.String(256))
    amount_paise = db.Column(db.Integer, nullable=False)       # Amount in paise (₹199 = 19900)
    credits_purchased = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='created', nullable=False)  # created / paid / failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    def __repr__(self):
        return f'<Transaction {self.razorpay_order_id} {self.status}>'


class CreditUsage(db.Model):
    """Tracks credit consumption — rewrites, bonuses, etc."""
    __tablename__ = 'credit_usages'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    credits_used = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(50), nullable=False)  # 'cv_rewrite', 'bonus_signup'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<CreditUsage user={self.user_id} action={self.action} credits={self.credits_used}>'


class LLMUsage(db.Model):
    """Tracks LLM API call statistics — tokens, duration, model."""
    __tablename__ = 'llm_usages'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    action = db.Column(db.String(50), nullable=False)  # cv_analysis, jd_analysis, cv_rewrite, cv_refine
    model = db.Column(db.String(100), nullable=False)
    input_chars = db.Column(db.Integer, default=0)
    output_chars = db.Column(db.Integer, default=0)
    estimated_input_tokens = db.Column(db.Integer, default=0)
    estimated_output_tokens = db.Column(db.Integer, default=0)
    duration_ms = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<LLMUsage user={self.user_id} action={self.action} model={self.model}>'


class StoredCV(db.Model):
    """Stores uploaded CV files permanently in PostgreSQL for admin access."""
    __tablename__ = 'stored_cvs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    user_email = db.Column(db.String(256))
    filename = db.Column(db.String(256), nullable=False)
    file_data = db.Column(db.LargeBinary, nullable=False)
    file_size = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<StoredCV {self.filename} user={self.user_email}>'


class UserResume(db.Model):
    """User's stored resumes — up to 5 per user, one marked as primary."""
    __tablename__ = 'user_resumes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    label = db.Column(db.String(100), default='My Resume')
    is_primary = db.Column(db.Boolean, default=False)
    filename = db.Column(db.String(256), nullable=False)
    file_data = db.Column(db.LargeBinary, nullable=False)
    extracted_text = db.Column(db.Text)
    file_size = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Resume editor fields
    resume_json = db.Column(db.Text)                                   # JSON Resume schema data (NULL for uploaded resumes)
    template_id = db.Column(db.String(30), default='classic')          # Template: classic | modern | minimal
    resume_source = db.Column(db.String(20), default='upload')         # Source: upload | editor

    # Analysis persistence fields (unified resumes page)
    target_job = db.Column(db.String(200), default='General')
    ats_score = db.Column(db.Integer)                                  # NULL = not yet analyzed
    analysis_status = db.Column(db.String(20), default='none')         # none | completed | failed
    analysis_results_json = db.Column(db.Text)                         # Full results as JSON
    last_analyzed_at = db.Column(db.DateTime)

    user = db.relationship('User', backref=db.backref('resumes', lazy='dynamic'))

    def __repr__(self):
        return f'<UserResume {self.label} user={self.user_id} primary={self.is_primary}>'


class JDAnalysis(db.Model):
    """Stores JD analysis progress and results in the database.

    Uses DB instead of in-memory dict so it works across multiple
    gunicorn workers on Railway.
    """
    __tablename__ = 'jd_analyses'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    status = db.Column(db.String(20), default='analyzing')  # analyzing | completed | failed
    error_message = db.Column(db.Text)
    jd_text = db.Column(db.Text)                            # Original JD text for rewrite flow
    results_json = db.Column(db.Text)                       # Full results as JSON
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('jd_analyses', lazy='dynamic'))

    def __repr__(self):
        return f'<JDAnalysis id={self.id} user={self.user_id} status={self.status}>'


class JobSearchCache(db.Model):
    """Cache for job search API results to conserve rate-limited API calls."""
    __tablename__ = 'job_search_cache'

    id = db.Column(db.Integer, primary_key=True)
    query_hash = db.Column(db.String(64), nullable=False, index=True)
    query_params = db.Column(db.Text, nullable=False)
    results_json = db.Column(db.Text, nullable=False)
    result_count = db.Column(db.Integer, default=0)
    page = db.Column(db.Integer, default=1, nullable=False)
    source = db.Column(db.String(20), default='jsearch')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)

    def __repr__(self):
        return f'<JobSearchCache hash={self.query_hash[:8]} count={self.result_count}>'


class JobATSScore(db.Model):
    """Cached ATS scores for jobs analyzed against a user's resume."""
    __tablename__ = 'job_ats_scores'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    job_id = db.Column(db.String(128), nullable=False)
    resume_id = db.Column(db.Integer, db.ForeignKey('user_resumes.id'), nullable=False)
    ats_score = db.Column(db.Integer, nullable=False)
    matched_skills = db.Column(db.Text)
    missing_skills = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'job_id', 'resume_id', name='uq_user_job_resume'),
    )

    def __repr__(self):
        return f'<JobATSScore user={self.user_id} job={self.job_id[:20]} score={self.ats_score}>'


class JobPreferences(db.Model):
    """Saved job search filter preferences per user.

    One row per user. Multi-value fields stored as JSON text arrays.
    Covers 4 filter sections: Basic Job Criteria, Compensation,
    Areas of Interest, Company Insights.
    """
    __tablename__ = 'job_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True, index=True)

    # Section 1: Basic Job Criteria
    job_titles = db.Column(db.Text, default='[]')              # JSON array of strings
    experience_level = db.Column(db.String(30), default='any')  # any|no_experience|under_3_years|more_than_3_years|no_degree
    employment_types = db.Column(db.Text, default='[]')         # JSON: ["FULLTIME","CONTRACTOR"]
    work_mode = db.Column(db.String(20), default='any')         # any|remote|hybrid|onsite
    locations = db.Column(db.Text, default='[]')                # JSON array of strings

    # Section 2: Compensation Range (INR)
    salary_min = db.Column(db.Integer, nullable=True)           # In INR, e.g. 500000
    salary_max = db.Column(db.Integer, nullable=True)
    salary_period = db.Column(db.String(10), default='annual')  # annual|monthly

    # Section 3: Areas of Interest
    industries = db.Column(db.Text, default='[]')               # JSON array — stores [function_id]
    functional_areas = db.Column(db.Text, default='[]')         # JSON array — stores [role_family_id]
    level = db.Column(db.String(30), default='')                # e.g. 'senior', 'lead', 'entry'
    skills = db.Column(db.Text, default='[]')                   # JSON array

    # Section 4: Company Insights
    company_sizes = db.Column(db.Text, default='[]')            # JSON: ["startup","mid_size","enterprise","mnc"]
    company_types = db.Column(db.Text, default='[]')            # JSON: ["product","service","consulting","startup"]
    companies_include = db.Column(db.Text, default='[]')        # JSON array of company names
    companies_exclude = db.Column(db.Text, default='[]')        # JSON array of company names

    # Meta
    setup_completed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('job_preferences', uselist=False))

    def __repr__(self):
        return f'<JobPreferences user={self.user_id} setup={self.setup_completed}>'

    def _parse_json(self, field_name):
        """Parse a JSON text field into a Python list."""
        import json
        val = getattr(self, field_name, '[]')
        try:
            return json.loads(val) if val else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _set_json(self, field_name, value):
        """Serialize a list to JSON text and set on the field."""
        import json
        setattr(self, field_name, json.dumps(value if value else []))

    def to_dict(self):
        """Return all preferences as a plain dict for JSON responses / templates."""
        return {
            'job_titles': self._parse_json('job_titles'),
            'experience_level': self.experience_level or 'any',
            'employment_types': self._parse_json('employment_types'),
            'work_mode': self.work_mode or 'any',
            'locations': self._parse_json('locations'),
            'salary_min': self.salary_min,
            'salary_max': self.salary_max,
            'salary_period': self.salary_period or 'annual',
            'industries': self._parse_json('industries'),
            'functional_areas': self._parse_json('functional_areas'),
            'level': self.level or '',
            'setup_completed': self.setup_completed,
        }

    def update_from_dict(self, data):
        """Update fields from a plain dict (e.g. from JSON request body)."""
        import json
        json_fields = [
            'job_titles', 'employment_types', 'locations', 'industries',
            'functional_areas',
        ]
        for field in json_fields:
            if field in data:
                val = data[field]
                setattr(self, field, json.dumps(val if isinstance(val, list) else []))

        str_fields = ['experience_level', 'work_mode', 'salary_period']
        for field in str_fields:
            if field in data:
                setattr(self, field, data[field] or getattr(self, field))

        if 'salary_min' in data:
            self.salary_min = int(data['salary_min']) if data['salary_min'] else None
        if 'salary_max' in data:
            self.salary_max = int(data['salary_max']) if data['salary_max'] else None

        # Level (taxonomy field)
        if 'level' in data:
            self.level = data['level'] or ''

        self.setup_completed = True
        self.updated_at = datetime.utcnow()


class JobPool(db.Model):
    """Local pool of individual job records fetched from JSearch API.

    Stores denormalized job data for local search/filtering without
    re-calling the API. Each job_id is globally unique.
    """
    __tablename__ = 'job_pool'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(256), unique=True, nullable=False, index=True)
    title = db.Column(db.String(500), nullable=False)
    company = db.Column(db.String(300), default='')
    company_logo = db.Column(db.String(512), default='')
    location = db.Column(db.String(300), default='')
    description = db.Column(db.Text, default='')
    description_snippet = db.Column(db.Text, default='')
    employment_type = db.Column(db.String(30), default='')          # FULLTIME, PARTTIME, etc.
    employment_type_display = db.Column(db.String(30), default='')  # Full-time, Part-time, etc.
    posted_date_raw = db.Column(db.String(50), default='')          # ISO date string from API
    posted_date_display = db.Column(db.String(50), default='')
    apply_url = db.Column(db.String(1024), default='')
    is_remote = db.Column(db.Boolean, default=False)
    salary_min = db.Column(db.Float, nullable=True)
    salary_max = db.Column(db.Float, nullable=True)
    salary_currency = db.Column(db.String(10), default='')
    salary_period = db.Column(db.String(20), default='')
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    source_query = db.Column(db.String(500), default='')
    source = db.Column(db.String(30), default='jsearch')  # Provider: jsearch, adzuna, jooble, remoteok, remotive
    # Lowercase copies for efficient SQL LIKE search
    title_lower = db.Column(db.String(500), default='', index=True)
    company_lower = db.Column(db.String(300), default='')
    description_lower = db.Column(db.Text, default='')

    def __repr__(self):
        return f'<JobPool {self.job_id[:20]} {self.title[:30]}>'

    def to_dict(self):
        """Convert to dict matching search_jobs() output format."""
        return {
            'job_id': self.job_id,
            'title': self.title,
            'company': self.company,
            'company_logo': self.company_logo,
            'location': self.location,
            'description': self.description,
            'description_snippet': self.description_snippet,
            'employment_type': self.employment_type_display or self.employment_type,
            'employment_type_raw': self.employment_type,
            'posted_date': self.posted_date_display,
            'posted_date_raw': self.posted_date_raw,
            'apply_url': self.apply_url,
            'is_remote': self.is_remote,
            'salary_min': self.salary_min,
            'salary_max': self.salary_max,
            'salary_currency': self.salary_currency,
            'salary_period': self.salary_period,
            'source': self.source or 'jsearch',
        }


class UserJobSnapshot(db.Model):
    """Per-user cached job results with pre-computed quick ATS scores.

    Stores the last search result set so return visits load instantly
    without any API, pool query, or ATS recomputation.
    """
    __tablename__ = 'user_job_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True, index=True)
    resume_id = db.Column(db.Integer, db.ForeignKey('user_resumes.id'), nullable=True)
    results_json = db.Column(db.Text, nullable=False, default='[]')  # JSON: list of job dicts WITH ats_score
    job_count = db.Column(db.Integer, default=0)
    preferences_hash = db.Column(db.String(64), default='')  # SHA256 of prefs dict
    source = db.Column(db.String(20), default='')  # 'pool' or 'api'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('job_snapshot', uselist=False))


class QuickATSCache(db.Model):
    """Cached quick (keyword-based) ATS scores per (resume_id, job_id).

    Avoids recomputing extract_skills_from_cv + 7-factor scoring on every
    page load.  Keyed on (resume_id, job_id) so results are reused across
    visits and even across users with the same primary resume.
    """
    __tablename__ = 'quick_ats_cache'

    id = db.Column(db.Integer, primary_key=True)
    resume_id = db.Column(db.Integer, db.ForeignKey('user_resumes.id'), nullable=False, index=True)
    job_id = db.Column(db.String(256), nullable=False, index=True)
    score = db.Column(db.Integer, nullable=False)
    matched_skills = db.Column(db.Text, default='[]')   # JSON array
    missing_skills = db.Column(db.Text, default='[]')    # JSON array
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('resume_id', 'job_id', name='uq_quick_ats_resume_job'),
    )


class ApiUsage(db.Model):
    """Tracks monthly API call counts per provider for quota enforcement."""
    __tablename__ = 'api_usage'

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(7), nullable=False)           # 'YYYY-MM'
    provider = db.Column(db.String(30), nullable=False)       # 'jsearch'
    calls_made = db.Column(db.Integer, default=0, nullable=False)
    last_call_at = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint('month', 'provider', name='uq_api_usage_month_provider'),
    )

    def __repr__(self):
        return f'<ApiUsage {self.provider} {self.month} calls={self.calls_made}>'


class ExtensionToken(db.Model):
    """API tokens for the LevelUpX AutoFill Chrome Extension.

    Raw token is a 48-char hex string (secrets.token_hex(24)).
    Only the SHA-256 hash is stored in the database.
    """
    __tablename__ = 'extension_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(128), unique=True, nullable=False)
    label = db.Column(db.String(100), default='Chrome Extension')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)

    user = db.relationship('User', backref=db.backref('extension_tokens', lazy='dynamic'))

    def __repr__(self):
        return f'<ExtensionToken id={self.id} user={self.user_id} active={self.is_active}>'
