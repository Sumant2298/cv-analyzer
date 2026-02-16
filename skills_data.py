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
# Hierarchical Category Tree: Industry → Roles → Suggested Skills
# Used by the filter wizard for cascading selection & better API queries
# ---------------------------------------------------------------------------
CATEGORY_TREE = {
    'IT & Software': {
        'roles': {
            'Engineering': {
                'keywords': ['engineer', 'developer', 'programming', 'software', 'backend', 'frontend', 'full stack'],
                'skills': ['python', 'java', 'javascript', 'react', 'django', 'spring boot', 'docker', 'kubernetes', 'sql', 'git'],
            },
            'Data Science & Analytics': {
                'keywords': ['data scientist', 'data analyst', 'analytics', 'machine learning', 'ml engineer'],
                'skills': ['python', 'sql', 'machine learning', 'tensorflow', 'pandas', 'numpy', 'tableau', 'spark', 'statistics'],
            },
            'DevOps & Infra': {
                'keywords': ['devops', 'sre', 'infrastructure', 'platform engineer', 'cloud engineer'],
                'skills': ['aws', 'docker', 'kubernetes', 'terraform', 'jenkins', 'ci/cd', 'linux', 'ansible', 'grafana'],
            },
            'QA & Testing': {
                'keywords': ['qa', 'quality assurance', 'tester', 'test engineer', 'sdet'],
                'skills': ['selenium', 'cypress', 'jest', 'pytest', 'unit testing', 'integration testing', 'test automation'],
            },
            'Product': {
                'keywords': ['product manager', 'product owner', 'product management'],
                'skills': ['agile', 'scrum', 'jira', 'stakeholder management', 'a/b testing', 'data analysis'],
            },
            'Design': {
                'keywords': ['designer', 'ui/ux', 'ux design', 'ui design', 'graphic design'],
                'skills': ['figma', 'user research', 'prototyping', 'design systems', 'css', 'html'],
            },
            'Security': {
                'keywords': ['security', 'cybersecurity', 'infosec', 'penetration testing'],
                'skills': ['cybersecurity', 'penetration testing', 'owasp', 'encryption', 'siem', 'compliance'],
            },
        },
        'api_boost_keywords': ['software', 'developer', 'engineer', 'technology'],
    },
    'Finance & Banking': {
        'roles': {
            'Financial Analysis': {
                'keywords': ['financial analyst', 'finance', 'investment', 'portfolio'],
                'skills': ['sql', 'python', 'excel', 'tableau', 'power bi', 'financial modeling'],
            },
            'Risk & Compliance': {
                'keywords': ['risk', 'compliance', 'audit', 'regulatory'],
                'skills': ['risk management', 'compliance', 'sql', 'python', 'statistics'],
            },
            'Fintech Engineering': {
                'keywords': ['fintech', 'payment', 'blockchain', 'trading platform'],
                'skills': ['python', 'java', 'sql', 'aws', 'docker', 'kubernetes'],
            },
        },
        'api_boost_keywords': ['finance', 'banking', 'financial'],
    },
    'Healthcare': {
        'roles': {
            'Health Informatics': {
                'keywords': ['health informatics', 'ehr', 'medical data', 'clinical data'],
                'skills': ['python', 'sql', 'data analysis', 'statistics'],
            },
            'Biotech & Research': {
                'keywords': ['biotech', 'research', 'clinical', 'pharmaceutical'],
                'skills': ['python', 'r', 'statistics', 'machine learning', 'data analysis'],
            },
        },
        'api_boost_keywords': ['healthcare', 'medical', 'health'],
    },
    'E-commerce': {
        'roles': {
            'Engineering': {
                'keywords': ['engineer', 'developer', 'full stack'],
                'skills': ['javascript', 'react', 'python', 'sql', 'aws', 'redis', 'elasticsearch'],
            },
            'Marketing & Growth': {
                'keywords': ['marketing', 'growth', 'seo', 'content'],
                'skills': ['seo', 'a/b testing', 'data analysis', 'sql', 'python'],
            },
            'Operations & Logistics': {
                'keywords': ['operations', 'supply chain', 'logistics', 'warehouse'],
                'skills': ['data analysis', 'sql', 'excel', 'python'],
            },
        },
        'api_boost_keywords': ['ecommerce', 'retail', 'marketplace'],
    },
    'Education': {
        'roles': {
            'EdTech Engineering': {
                'keywords': ['edtech', 'learning platform', 'lms'],
                'skills': ['javascript', 'react', 'python', 'django', 'aws', 'sql'],
            },
            'Instructional Design': {
                'keywords': ['instructional design', 'curriculum', 'content development'],
                'skills': ['curriculum design', 'e-learning', 'data analysis'],
            },
        },
        'api_boost_keywords': ['education', 'edtech', 'learning'],
    },
    'Consulting': {
        'roles': {
            'Management Consulting': {
                'keywords': ['consultant', 'advisory', 'strategy'],
                'skills': ['data analysis', 'presentation', 'project management', 'sql', 'python'],
            },
            'Technology Consulting': {
                'keywords': ['technology consulting', 'it consulting', 'digital transformation'],
                'skills': ['aws', 'azure', 'agile', 'project management', 'python', 'sql'],
            },
        },
        'api_boost_keywords': ['consulting', 'advisory'],
    },
    'Manufacturing': {
        'roles': {
            'Industrial Engineering': {
                'keywords': ['industrial engineer', 'manufacturing', 'process engineer'],
                'skills': ['lean manufacturing', 'six sigma', 'data analysis', 'python'],
            },
            'Supply Chain': {
                'keywords': ['supply chain', 'procurement', 'logistics'],
                'skills': ['data analysis', 'sql', 'excel', 'python'],
            },
        },
        'api_boost_keywords': ['manufacturing', 'industrial'],
    },
    'Media & Entertainment': {
        'roles': {
            'Content & Creative': {
                'keywords': ['content', 'creative', 'media', 'editorial'],
                'skills': ['content strategy', 'data analysis', 'python'],
            },
            'Streaming & Tech': {
                'keywords': ['streaming', 'ott', 'video platform'],
                'skills': ['python', 'javascript', 'aws', 'docker', 'kubernetes'],
            },
        },
        'api_boost_keywords': ['media', 'entertainment', 'content'],
    },
    'Telecom': {
        'roles': {
            'Network Engineering': {
                'keywords': ['network', 'telecom', '5g', 'wireless'],
                'skills': ['networking', 'linux', 'python', 'sql', 'aws'],
            },
        },
        'api_boost_keywords': ['telecom', 'telecommunications'],
    },
    'Government & PSU': {
        'roles': {
            'IT & Digital': {
                'keywords': ['e-governance', 'digital india', 'government it'],
                'skills': ['java', 'spring boot', 'sql', 'linux', 'oracle'],
            },
        },
        'api_boost_keywords': ['government', 'public sector'],
    },
}
