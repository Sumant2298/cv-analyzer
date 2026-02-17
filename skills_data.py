SKILL_CATEGORIES = {
    'programming_languages': {
        'python', 'java', 'javascript', 'typescript', 'c++', 'c#',
        'ruby', 'go', 'golang', 'rust', 'scala', 'kotlin', 'swift',
        'php', 'r', 'matlab', 'perl', 'lua', 'dart', 'shell', 'bash',
        'objective-c', 'haskell', 'elixir', 'clojure',
    },
    'web_frameworks': {
        'react', 'angular', 'vue', 'django', 'flask', 'fastapi',
        'spring', 'spring boot', 'express', 'nextjs', 'next.js',
        'rails', 'ruby on rails', 'laravel', 'svelte', 'nuxt',
        'gatsby', 'remix', 'asp.net', 'blazor', 'htmx',
    },
    'databases': {
        'sql', 'mysql', 'postgresql', 'postgres', 'mongodb', 'redis',
        'elasticsearch', 'dynamodb', 'cassandra', 'sqlite', 'oracle',
        'mariadb', 'neo4j', 'firebase', 'bigquery', 'snowflake',
        'couchdb', 'cockroachdb', 'supabase',
    },
    'cloud_devops': {
        'aws', 'azure', 'gcp', 'google cloud', 'docker', 'kubernetes',
        'k8s', 'terraform', 'ansible', 'jenkins', 'ci/cd',
        'github actions', 'circleci', 'cloudformation', 'serverless',
        'lambda', 'heroku', 'vercel', 'netlify', 'nginx', 'apache',
        'grafana', 'prometheus', 'datadog', 'helm', 'pulumi',
    },
    'data_ml': {
        'machine learning', 'deep learning', 'nlp',
        'natural language processing', 'computer vision', 'tensorflow',
        'pytorch', 'scikit-learn', 'pandas', 'numpy', 'spark',
        'hadoop', 'data analysis', 'data engineering', 'etl',
        'a/b testing', 'statistics', 'data visualization',
        'tableau', 'power bi', 'keras', 'opencv', 'mlops',
        'feature engineering', 'neural networks', 'transformers',
        'llm', 'large language models', 'rag', 'fine-tuning',
    },
    'soft_skills': {
        'leadership', 'communication', 'teamwork', 'problem solving',
        'project management', 'agile', 'scrum', 'mentoring',
        'stakeholder management', 'cross-functional', 'collaboration',
        'time management', 'critical thinking', 'analytical',
        'presentation', 'negotiation', 'strategic planning',
    },
    'tools': {
        'git', 'github', 'gitlab', 'bitbucket', 'jira', 'confluence',
        'slack', 'figma', 'postman', 'swagger', 'linux', 'vim',
        'vscode', 'intellij', 'webpack', 'vite', 'npm', 'yarn',
        'maven', 'gradle', 'make', 'cmake',
    },
    'testing': {
        'unit testing', 'integration testing', 'e2e testing',
        'jest', 'pytest', 'junit', 'selenium', 'cypress',
        'playwright', 'mocha', 'chai', 'rspec', 'tdd', 'bdd',
        'test automation', 'load testing', 'performance testing',
    },
    'security': {
        'cybersecurity', 'penetration testing', 'owasp', 'encryption',
        'authentication', 'authorization', 'oauth', 'jwt', 'ssl',
        'tls', 'sso', 'rbac', 'siem', 'vulnerability assessment',
        'compliance', 'gdpr', 'hipaa', 'soc2',
    },
}

# Flattened set for quick lookup
ALL_KNOWN_SKILLS = set()
for _category_skills in SKILL_CATEGORIES.values():
    ALL_KNOWN_SKILLS.update(_category_skills)


# ---------------------------------------------------------------------------
# Skill Aliases: common abbreviations/alternate names → canonical skill name
# Used by enhanced quick_ats_score to match aliases that SKILL_CATEGORIES misses
# ---------------------------------------------------------------------------
SKILL_ALIASES = {
    'js': 'javascript',
    'ts': 'typescript',
    'k8s': 'kubernetes',
    'postgres': 'postgresql',
    'mongo': 'mongodb',
    'gcp': 'google cloud',
    'ml': 'machine learning',
    'dl': 'deep learning',
    'nlp': 'natural language processing',
    'oop': 'object-oriented programming',
    'rest': 'restful api',
    'react.js': 'react',
    'reactjs': 'react',
    'node.js': 'express',
    'nodejs': 'express',
    'next.js': 'nextjs',
    'vue.js': 'vue',
    'vuejs': 'vue',
    '.net': 'asp.net',
    'dotnet': 'asp.net',
    'csharp': 'c#',
    'golang': 'go',
    'springboot': 'spring boot',
    'tf': 'terraform',
    'py': 'python',
    'rb': 'ruby',
    'ai': 'machine learning',
    'sre': 'site reliability engineering',
    'qa': 'quality assurance',
    'devops': 'ci/cd',
    'microservices': 'microservices',
    'graphql': 'graphql',
    'rabbitmq': 'rabbitmq',
    'kafka': 'kafka',
}


# ---------------------------------------------------------------------------
# Global seniority levels — same for every function
# ---------------------------------------------------------------------------
GLOBAL_LEVELS = [
    {'id': 'intern',         'label': 'Intern'},
    {'id': 'entry',          'label': 'Entry'},
    {'id': 'mid',            'label': 'Mid'},
    {'id': 'senior',         'label': 'Senior'},
    {'id': 'lead',           'label': 'Lead'},
    {'id': 'manager',        'label': 'Manager'},
    {'id': 'senior_manager', 'label': 'Senior Manager'},
    {'id': 'director',       'label': 'Director'},
    {'id': 'vp',             'label': 'VP'},
    {'id': 'c_level',        'label': 'C-Level'},
]

LEVEL_LABELS = {lv['id']: lv['label'] for lv in GLOBAL_LEVELS}


# ---------------------------------------------------------------------------
# Canonical Taxonomy: Function → Role Families → (keywords, skills, title_patterns)
# All keys are stable IDs.  UI labels come from 'label' fields.
# ---------------------------------------------------------------------------
TAXONOMY = {
    'engineering': {
        'label': 'Engineering',
        'api_boost_keywords': ['software', 'developer', 'engineer', 'technology'],
        'role_families': {
            'backend':      {'label': 'Backend Engineering',      'keywords': ['backend', 'server-side', 'api developer', 'backend engineer'],                    'skills': ['python', 'java', 'sql', 'docker', 'kubernetes', 'redis', 'postgresql', 'spring boot'],                     'title_patterns': ['{level} Backend Developer', '{level} Backend Engineer']},
            'frontend':     {'label': 'Frontend Engineering',     'keywords': ['frontend', 'front-end', 'ui developer', 'frontend engineer'],                     'skills': ['javascript', 'react', 'typescript', 'css', 'html', 'nextjs', 'vue', 'webpack'],                            'title_patterns': ['{level} Frontend Developer', '{level} Frontend Engineer']},
            'fullstack':    {'label': 'Full Stack Engineering',   'keywords': ['full stack', 'fullstack', 'full-stack developer'],                                 'skills': ['javascript', 'python', 'react', 'django', 'sql', 'docker', 'typescript', 'git'],                           'title_patterns': ['{level} Full Stack Developer', '{level} Full Stack Engineer']},
            'mobile':       {'label': 'Mobile Engineering',       'keywords': ['mobile', 'ios', 'android', 'react native', 'flutter'],                             'skills': ['swift', 'kotlin', 'react', 'flutter', 'dart', 'typescript'],                                               'title_patterns': ['{level} Mobile Developer', '{level} iOS Developer', '{level} Android Developer']},
            'data_eng':     {'label': 'Data Engineering',         'keywords': ['data engineer', 'etl', 'data pipeline', 'data platform'],                          'skills': ['python', 'sql', 'spark', 'hadoop', 'aws', 'docker', 'etl', 'snowflake'],                                   'title_patterns': ['{level} Data Engineer', '{level} ETL Developer', '{level} Data Platform Engineer']},
            'ml_ai':        {'label': 'ML / AI Engineering',      'keywords': ['machine learning', 'ml engineer', 'ai engineer', 'deep learning'],                 'skills': ['python', 'tensorflow', 'pytorch', 'machine learning', 'deep learning', 'mlops', 'pandas', 'numpy'],        'title_patterns': ['{level} ML Engineer', '{level} AI Engineer', '{level} Machine Learning Engineer']},
            'devops':       {'label': 'DevOps',                   'keywords': ['devops', 'ci/cd', 'build engineer', 'release engineer'],                           'skills': ['docker', 'kubernetes', 'jenkins', 'ci/cd', 'terraform', 'aws', 'linux', 'ansible'],                        'title_patterns': ['{level} DevOps Engineer', '{level} Build & Release Engineer']},
            'sre':          {'label': 'Site Reliability',         'keywords': ['sre', 'site reliability', 'reliability engineer'],                                 'skills': ['linux', 'kubernetes', 'docker', 'prometheus', 'grafana', 'terraform', 'python', 'aws'],                    'title_patterns': ['{level} SRE', '{level} Site Reliability Engineer']},
            'cloud_infra':  {'label': 'Cloud & Infrastructure',   'keywords': ['cloud engineer', 'infrastructure', 'platform engineer', 'cloud architect'],        'skills': ['aws', 'azure', 'gcp', 'terraform', 'kubernetes', 'docker', 'linux', 'networking'],                         'title_patterns': ['{level} Cloud Engineer', '{level} Platform Engineer', '{level} Infrastructure Engineer']},
            'security_eng': {'label': 'Security Engineering',     'keywords': ['security', 'cybersecurity', 'infosec', 'penetration testing', 'appsec'],           'skills': ['cybersecurity', 'penetration testing', 'owasp', 'encryption', 'siem', 'compliance'],                       'title_patterns': ['{level} Security Engineer', '{level} Cybersecurity Engineer', '{level} AppSec Engineer']},
            'qa_test':      {'label': 'QA & Testing',             'keywords': ['qa', 'quality assurance', 'tester', 'test engineer', 'sdet'],                      'skills': ['selenium', 'cypress', 'jest', 'pytest', 'test automation', 'playwright', 'unit testing'],                   'title_patterns': ['{level} QA Engineer', '{level} SDET', '{level} Test Automation Engineer']},
            'embedded':     {'label': 'Embedded & Systems',       'keywords': ['embedded', 'firmware', 'systems programming', 'iot', 'rtos'],                      'skills': ['c++', 'c', 'python', 'linux', 'rtos', 'iot', 'assembly'],                                                  'title_patterns': ['{level} Embedded Engineer', '{level} Firmware Engineer', '{level} Systems Engineer']},
            'blockchain':   {'label': 'Blockchain Engineering',   'keywords': ['blockchain', 'web3', 'smart contract', 'solidity', 'defi'],                        'skills': ['solidity', 'javascript', 'python', 'ethereum', 'web3', 'rust'],                                            'title_patterns': ['{level} Blockchain Developer', '{level} Smart Contract Engineer', '{level} Web3 Developer']},
        },
    },
    'product': {
        'label': 'Product',
        'api_boost_keywords': ['product manager', 'product management'],
        'role_families': {
            'product_management': {'label': 'Product Management',          'keywords': ['product manager', 'product owner', 'product management'],                   'skills': ['agile', 'scrum', 'jira', 'stakeholder management', 'a/b testing', 'data analysis'],            'title_patterns': ['{level} Product Manager', '{level} Product Owner']},
            'technical_product':  {'label': 'Technical Product Management','keywords': ['technical product manager', 'tpm', 'technical pm'],                          'skills': ['agile', 'scrum', 'sql', 'python', 'data analysis', 'jira', 'api design'],                     'title_patterns': ['{level} Technical Product Manager', '{level} TPM']},
            'growth_product':     {'label': 'Growth Product',              'keywords': ['growth product', 'growth pm', 'experimentation'],                            'skills': ['a/b testing', 'data analysis', 'sql', 'experimentation', 'analytics'],                        'title_patterns': ['{level} Growth Product Manager']},
            'platform_product':   {'label': 'Platform Product',            'keywords': ['platform product', 'platform pm', 'internal product'],                       'skills': ['agile', 'sql', 'api design', 'stakeholder management', 'data analysis'],                      'title_patterns': ['{level} Platform Product Manager']},
            'ai_product':         {'label': 'AI Product Management',       'keywords': ['ai product', 'ml product', 'ai pm'],                                         'skills': ['machine learning', 'data analysis', 'python', 'agile', 'stakeholder management'],              'title_patterns': ['{level} AI Product Manager', '{level} ML Product Manager']},
            'product_ops':        {'label': 'Product Operations',          'keywords': ['product ops', 'product operations', 'release management'],                   'skills': ['jira', 'project management', 'data analysis', 'agile', 'communication'],                      'title_patterns': ['{level} Product Ops Manager', '{level} Release Manager']},
            'product_analytics':  {'label': 'Product Analytics',           'keywords': ['product analytics', 'product analyst', 'product data'],                      'skills': ['sql', 'python', 'data analysis', 'a/b testing', 'tableau', 'statistics'],                     'title_patterns': ['{level} Product Analyst', '{level} Product Data Analyst']},
        },
    },
    'design': {
        'label': 'Design',
        'api_boost_keywords': ['designer', 'ux', 'ui design'],
        'role_families': {
            'ui_design':          {'label': 'UI Design',              'keywords': ['ui design', 'ui designer', 'visual interface'],                                      'skills': ['figma', 'css', 'html', 'design systems', 'typography', 'sketch'],                             'title_patterns': ['{level} UI Designer', '{level} Visual Designer']},
            'ux_design':          {'label': 'UX Design',              'keywords': ['ux design', 'ux designer', 'user experience'],                                      'skills': ['figma', 'user research', 'prototyping', 'usability testing', 'wireframing'],                  'title_patterns': ['{level} UX Designer']},
            'product_design':     {'label': 'Product Design',         'keywords': ['product design', 'product designer', 'end-to-end design'],                          'skills': ['figma', 'user research', 'prototyping', 'design systems', 'css'],                             'title_patterns': ['{level} Product Designer']},
            'interaction_design': {'label': 'Interaction Design',     'keywords': ['interaction design', 'motion', 'micro-interaction'],                                 'skills': ['figma', 'prototyping', 'animation', 'css', 'javascript'],                                     'title_patterns': ['{level} Interaction Designer']},
            'visual_design':      {'label': 'Visual / Brand Design',  'keywords': ['visual design', 'brand design', 'graphic design'],                                  'skills': ['figma', 'illustrator', 'photoshop', 'typography', 'branding'],                                'title_patterns': ['{level} Visual Designer', '{level} Brand Designer']},
            'motion_design':      {'label': 'Motion Design',          'keywords': ['motion design', 'motion graphics', 'animation'],                                    'skills': ['after effects', 'figma', 'animation', 'prototyping', 'video editing'],                        'title_patterns': ['{level} Motion Designer']},
            'design_systems':     {'label': 'Design Systems',         'keywords': ['design systems', 'component library', 'design ops'],                                'skills': ['figma', 'css', 'react', 'design tokens', 'documentation'],                                   'title_patterns': ['{level} Design Systems Lead', '{level} Design Systems Designer']},
            'ux_research':        {'label': 'UX Research',            'keywords': ['ux research', 'user research', 'usability'],                                        'skills': ['user research', 'usability testing', 'data analysis', 'statistics', 'surveys'],               'title_patterns': ['{level} UX Researcher', '{level} User Researcher']},
        },
    },
    'data': {
        'label': 'Data',
        'api_boost_keywords': ['data', 'analytics', 'machine learning'],
        'role_families': {
            'data_science':           {'label': 'Data Science',            'keywords': ['data scientist', 'machine learning', 'statistical modeling'],                     'skills': ['python', 'machine learning', 'tensorflow', 'pandas', 'numpy', 'statistics', 'sql'],           'title_patterns': ['{level} Data Scientist']},
            'analytics':              {'label': 'Analytics',               'keywords': ['data analyst', 'analytics', 'business analyst', 'reporting'],                     'skills': ['sql', 'python', 'tableau', 'power bi', 'excel', 'data analysis', 'statistics'],               'title_patterns': ['{level} Data Analyst', '{level} Business Analyst', '{level} Analytics Engineer']},
            'business_intelligence':  {'label': 'Business Intelligence',   'keywords': ['bi', 'business intelligence', 'bi developer', 'reporting'],                      'skills': ['sql', 'tableau', 'power bi', 'python', 'data visualization', 'etl'],                          'title_patterns': ['{level} BI Developer', '{level} BI Analyst']},
            'quant_research':         {'label': 'Quantitative Research',   'keywords': ['quant', 'quantitative', 'research', 'algorithmic'],                              'skills': ['python', 'r', 'statistics', 'machine learning', 'sql', 'matlab'],                             'title_patterns': ['{level} Quantitative Researcher', '{level} Quant Analyst']},
            'data_architecture':      {'label': 'Data Architecture',       'keywords': ['data architect', 'data modeling', 'data governance'],                             'skills': ['sql', 'python', 'snowflake', 'aws', 'data modeling', 'etl', 'spark'],                         'title_patterns': ['{level} Data Architect']},
            'data_governance':        {'label': 'Data Governance',         'keywords': ['data governance', 'data quality', 'master data'],                                 'skills': ['sql', 'data governance', 'data quality', 'compliance', 'python'],                             'title_patterns': ['{level} Data Governance Analyst', '{level} Data Quality Manager']},
        },
    },
    'sales': {
        'label': 'Sales',
        'api_boost_keywords': ['sales', 'business development', 'account'],
        'role_families': {
            'inside_sales':        {'label': 'Inside Sales',           'keywords': ['inside sales', 'sdr', 'bdr', 'sales development'],                                  'skills': ['communication', 'crm', 'salesforce', 'negotiation', 'cold calling'],                          'title_patterns': ['{level} SDR', '{level} Inside Sales Representative']},
            'enterprise_sales':    {'label': 'Enterprise Sales',       'keywords': ['enterprise sales', 'strategic sales', 'large deal'],                                 'skills': ['negotiation', 'stakeholder management', 'crm', 'strategic planning', 'communication'],        'title_patterns': ['{level} Enterprise Account Executive', '{level} Strategic Sales Manager']},
            'channel_sales':       {'label': 'Channel / Partner Sales','keywords': ['channel sales', 'partner sales', 'alliances', 'reseller'],                           'skills': ['negotiation', 'communication', 'crm', 'partner management', 'strategic planning'],            'title_patterns': ['{level} Channel Sales Manager', '{level} Partner Manager']},
            'account_exec':        {'label': 'Account Executive',      'keywords': ['account executive', 'ae', 'sales executive', 'closer'],                              'skills': ['negotiation', 'communication', 'crm', 'salesforce', 'presentation'],                          'title_patterns': ['{level} Account Executive', '{level} Sales Executive']},
            'account_management':  {'label': 'Account Management',     'keywords': ['account manager', 'client success', 'customer success', 'csm'],                      'skills': ['communication', 'crm', 'stakeholder management', 'project management', 'negotiation'],        'title_patterns': ['{level} Account Manager', '{level} Customer Success Manager']},
            'sales_ops':           {'label': 'Sales Operations',       'keywords': ['sales ops', 'sales operations', 'sales analytics'],                                  'skills': ['salesforce', 'sql', 'data analysis', 'excel', 'crm', 'communication'],                        'title_patterns': ['{level} Sales Operations Analyst', '{level} Sales Ops Manager']},
            'rev_ops':             {'label': 'Revenue Operations',     'keywords': ['rev ops', 'revenue operations', 'gtm ops'],                                          'skills': ['salesforce', 'sql', 'data analysis', 'crm', 'strategic planning', 'communication'],           'title_patterns': ['{level} RevOps Analyst', '{level} Revenue Operations Manager']},
        },
    },
    'marketing': {
        'label': 'Marketing',
        'api_boost_keywords': ['marketing', 'growth', 'digital marketing'],
        'role_families': {
            'performance_marketing': {'label': 'Performance Marketing',  'keywords': ['performance marketing', 'paid media', 'ppc', 'growth'],                            'skills': ['a/b testing', 'data analysis', 'sql', 'google ads', 'facebook ads', 'analytics'],              'title_patterns': ['{level} Performance Marketing Manager', '{level} Paid Media Specialist']},
            'brand_marketing':       {'label': 'Brand Marketing',        'keywords': ['brand marketing', 'brand strategy', 'brand manager'],                              'skills': ['communication', 'strategic planning', 'data analysis', 'presentation', 'branding'],           'title_patterns': ['{level} Brand Marketing Manager', '{level} Brand Strategist']},
            'product_marketing':     {'label': 'Product Marketing',      'keywords': ['product marketing', 'pmm', 'go-to-market', 'positioning'],                         'skills': ['communication', 'data analysis', 'presentation', 'strategic planning', 'market research'],    'title_patterns': ['{level} Product Marketing Manager']},
            'content_marketing':     {'label': 'Content Marketing',      'keywords': ['content marketing', 'content strategy', 'editorial'],                               'skills': ['content strategy', 'seo', 'data analysis', 'communication', 'copywriting'],                   'title_patterns': ['{level} Content Marketing Manager', '{level} Content Strategist']},
            'seo_sem':               {'label': 'SEO / SEM',              'keywords': ['seo', 'sem', 'search engine', 'organic growth'],                                    'skills': ['seo', 'google ads', 'data analysis', 'sql', 'analytics', 'content strategy'],                 'title_patterns': ['{level} SEO Specialist', '{level} SEM Manager']},
            'marketing_ops':         {'label': 'Marketing Operations',   'keywords': ['marketing ops', 'marketing operations', 'martech'],                                 'skills': ['sql', 'data analysis', 'crm', 'marketing automation', 'analytics', 'excel'],                  'title_patterns': ['{level} Marketing Operations Manager', '{level} MarTech Analyst']},
            'pr_comms':              {'label': 'PR & Communications',    'keywords': ['pr', 'public relations', 'communications', 'media relations'],                      'skills': ['communication', 'writing', 'presentation', 'media relations', 'strategic planning'],          'title_patterns': ['{level} PR Manager', '{level} Communications Manager']},
        },
    },
    'hr': {
        'label': 'HR & People',
        'api_boost_keywords': ['human resources', 'hr', 'people operations', 'talent'],
        'role_families': {
            'hrbp_generalist':  {'label': 'HRBP / Generalist',        'keywords': ['hrbp', 'hr business partner', 'hr generalist', 'human resources'],                  'skills': ['communication', 'stakeholder management', 'data analysis', 'project management'],             'title_patterns': ['{level} HRBP', '{level} HR Generalist', '{level} HR Business Partner']},
            'talent_acquisition':{'label': 'Talent Acquisition',      'keywords': ['recruiter', 'talent acquisition', 'hiring', 'sourcing'],                              'skills': ['communication', 'negotiation', 'stakeholder management', 'linkedin', 'ats'],                  'title_patterns': ['{level} Recruiter', '{level} Talent Acquisition Specialist', '{level} Sourcer']},
            'ld_od':            {'label': 'L&D / OD',                  'keywords': ['learning', 'development', 'training', 'organizational development', 'l&d'],          'skills': ['communication', 'presentation', 'project management', 'instructional design'],                'title_patterns': ['{level} L&D Specialist', '{level} Training Manager', '{level} OD Consultant']},
            'comp_benefits':    {'label': 'Compensation & Benefits',   'keywords': ['compensation', 'benefits', 'total rewards', 'payroll'],                               'skills': ['excel', 'data analysis', 'sql', 'compliance', 'compensation benchmarking'],                   'title_patterns': ['{level} Compensation Analyst', '{level} Benefits Manager']},
            'hr_operations':    {'label': 'HR Operations',             'keywords': ['hr ops', 'hr operations', 'people operations', 'hris'],                               'skills': ['hris', 'data analysis', 'project management', 'excel', 'communication'],                      'title_patterns': ['{level} HR Operations Manager', '{level} People Ops Specialist']},
            'employee_relations':{'label': 'Employee Relations',       'keywords': ['employee relations', 'labor relations', 'workplace'],                                 'skills': ['communication', 'compliance', 'negotiation', 'conflict resolution'],                          'title_patterns': ['{level} Employee Relations Specialist', '{level} ER Manager']},
            'dei':              {'label': 'DEI',                       'keywords': ['dei', 'diversity', 'equity', 'inclusion'],                                             'skills': ['communication', 'data analysis', 'strategic planning', 'project management'],                 'title_patterns': ['{level} DEI Lead', '{level} Diversity & Inclusion Manager']},
            'people_analytics': {'label': 'People Analytics',          'keywords': ['people analytics', 'hr analytics', 'workforce analytics'],                            'skills': ['python', 'sql', 'data analysis', 'tableau', 'statistics', 'excel'],                           'title_patterns': ['{level} People Analytics Analyst', '{level} HR Data Scientist']},
            'global_mobility':  {'label': 'Global Mobility',           'keywords': ['global mobility', 'relocation', 'immigration', 'expat'],                              'skills': ['compliance', 'project management', 'communication', 'immigration law'],                       'title_patterns': ['{level} Global Mobility Specialist', '{level} Immigration Analyst']},
        },
    },
    'finance': {
        'label': 'Finance',
        'api_boost_keywords': ['finance', 'financial', 'accounting'],
        'role_families': {
            'fpna':              {'label': 'FP&A',                    'keywords': ['fp&a', 'financial planning', 'financial analysis', 'budgeting'],                        'skills': ['excel', 'sql', 'python', 'financial modeling', 'tableau', 'power bi'],                        'title_patterns': ['{level} FP&A Analyst', '{level} Financial Analyst']},
            'accounting':        {'label': 'Accounting',              'keywords': ['accounting', 'accountant', 'bookkeeper', 'cpa', 'gaap'],                               'skills': ['excel', 'accounting', 'compliance', 'data analysis', 'erp'],                                  'title_patterns': ['{level} Accountant', '{level} Accounting Manager']},
            'treasury':          {'label': 'Treasury',                'keywords': ['treasury', 'cash management', 'liquidity', 'fx'],                                      'skills': ['excel', 'financial modeling', 'data analysis', 'sql', 'risk management'],                     'title_patterns': ['{level} Treasury Analyst', '{level} Treasury Manager']},
            'tax':               {'label': 'Tax',                     'keywords': ['tax', 'taxation', 'tax compliance', 'transfer pricing'],                               'skills': ['tax compliance', 'excel', 'accounting', 'data analysis', 'erp'],                              'title_patterns': ['{level} Tax Analyst', '{level} Tax Manager']},
            'audit':             {'label': 'Audit',                   'keywords': ['audit', 'auditor', 'internal audit', 'external audit'],                                'skills': ['auditing', 'compliance', 'data analysis', 'excel', 'risk management'],                        'title_patterns': ['{level} Internal Auditor', '{level} Audit Manager']},
            'corporate_finance': {'label': 'Corporate Finance',       'keywords': ['corporate finance', 'investment banking', 'valuation'],                                'skills': ['financial modeling', 'excel', 'valuation', 'data analysis', 'python'],                        'title_patterns': ['{level} Corporate Finance Analyst', '{level} Investment Banking Associate']},
            'mna':               {'label': 'M&A',                     'keywords': ['m&a', 'mergers', 'acquisitions', 'due diligence'],                                     'skills': ['financial modeling', 'valuation', 'excel', 'data analysis', 'due diligence'],                 'title_patterns': ['{level} M&A Analyst', '{level} M&A Associate']},
            'risk_management':   {'label': 'Risk Management',         'keywords': ['risk', 'risk management', 'compliance', 'regulatory'],                                 'skills': ['risk management', 'compliance', 'sql', 'python', 'statistics', 'data analysis'],              'title_patterns': ['{level} Risk Analyst', '{level} Risk Manager', '{level} Compliance Officer']},
        },
    },
    'operations': {
        'label': 'Operations',
        'api_boost_keywords': ['operations', 'strategy', 'project management'],
        'role_families': {
            'business_ops':       {'label': 'Business Operations',     'keywords': ['business ops', 'business operations', 'operations manager'],                          'skills': ['data analysis', 'sql', 'excel', 'project management', 'python', 'communication'],             'title_patterns': ['{level} Business Operations Manager', '{level} Operations Analyst']},
            'strategy_planning':  {'label': 'Strategy & Planning',     'keywords': ['strategy', 'strategic planning', 'corporate strategy'],                               'skills': ['data analysis', 'presentation', 'strategic planning', 'excel', 'sql'],                        'title_patterns': ['{level} Strategy Analyst', '{level} Business Strategy Manager']},
            'program_management': {'label': 'Program Management',      'keywords': ['program manager', 'program management', 'pgm'],                                       'skills': ['project management', 'agile', 'stakeholder management', 'jira', 'communication'],             'title_patterns': ['{level} Program Manager', '{level} Technical Program Manager']},
            'project_management': {'label': 'Project Management',      'keywords': ['project manager', 'project management', 'pmo'],                                       'skills': ['project management', 'agile', 'scrum', 'jira', 'communication', 'stakeholder management'],   'title_patterns': ['{level} Project Manager', '{level} Scrum Master']},
            'supply_chain':       {'label': 'Supply Chain',            'keywords': ['supply chain', 'scm', 'demand planning', 'inventory'],                                'skills': ['data analysis', 'sql', 'excel', 'python', 'erp', 'logistics'],                                'title_patterns': ['{level} Supply Chain Manager', '{level} Demand Planner']},
            'procurement':        {'label': 'Procurement',             'keywords': ['procurement', 'sourcing', 'vendor management', 'purchasing'],                         'skills': ['negotiation', 'data analysis', 'excel', 'erp', 'compliance'],                                 'title_patterns': ['{level} Procurement Manager', '{level} Strategic Sourcing Analyst']},
            'logistics':          {'label': 'Logistics',               'keywords': ['logistics', 'warehouse', 'distribution', 'transportation'],                           'skills': ['data analysis', 'excel', 'erp', 'logistics', 'communication'],                                'title_patterns': ['{level} Logistics Manager', '{level} Warehouse Manager']},
            'process_excellence': {'label': 'Process Excellence',      'keywords': ['process excellence', 'lean', 'six sigma', 'continuous improvement'],                  'skills': ['lean manufacturing', 'six sigma', 'data analysis', 'python', 'project management'],           'title_patterns': ['{level} Process Excellence Lead', '{level} Continuous Improvement Manager']},
        },
    },
}

# Deprecated: old name kept to avoid ImportError in stale code
CATEGORY_TREE = {}


# ---------------------------------------------------------------------------
# Title derivation helpers
# ---------------------------------------------------------------------------

def derive_titles(role_family_id, level_id, function_id=None):
    """Generate title suggestions from role_family + level.

    Substitutes level label into the role family's title_patterns.
    Returns a list of title strings.
    """
    level_label = LEVEL_LABELS.get(level_id, '')
    role_data = None
    for fid, fdata in TAXONOMY.items():
        if function_id and fid != function_id:
            continue
        if role_family_id in fdata['role_families']:
            role_data = fdata['role_families'][role_family_id]
            break
    if not role_data:
        return []
    titles = []
    for pattern in role_data.get('title_patterns', []):
        title = pattern.replace('{level}', level_label).strip()
        title = ' '.join(title.split())  # normalise whitespace
        titles.append(title)
    return titles


def get_role_family(function_id, role_family_id):
    """Look up a role family's full data dict.  Returns None if not found."""
    func = TAXONOMY.get(function_id)
    return func['role_families'].get(role_family_id) if func else None


# ---------------------------------------------------------------------------
# Indian cities for location dropdown (predefined, no free typing)
# ---------------------------------------------------------------------------
INDIAN_CITIES = [
    'Bangalore', 'Bengaluru', 'Mumbai', 'Delhi NCR', 'Hyderabad', 'Chennai', 'Pune',
    'Kolkata', 'Ahmedabad', 'Noida', 'Gurgaon', 'Gurugram', 'Jaipur', 'Chandigarh',
    'Kochi', 'Indore', 'Lucknow', 'Coimbatore', 'Thiruvananthapuram',
    'Visakhapatnam', 'Nagpur', 'Bhubaneswar', 'Remote',
]
