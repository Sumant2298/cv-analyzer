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
                'titles': ['Software Engineer', 'Frontend Developer', 'Backend Developer', 'Full Stack Developer', 'Senior Software Engineer', 'Software Architect', 'Mobile Developer', 'Embedded Engineer'],
                'skills': ['python', 'java', 'javascript', 'react', 'django', 'spring boot', 'docker', 'kubernetes', 'sql', 'git'],
            },
            'Data Science & Analytics': {
                'keywords': ['data scientist', 'data analyst', 'analytics', 'machine learning', 'ml engineer'],
                'titles': ['Data Scientist', 'Data Analyst', 'ML Engineer', 'Data Engineer', 'Business Analyst', 'Analytics Manager'],
                'skills': ['python', 'sql', 'machine learning', 'tensorflow', 'pandas', 'numpy', 'tableau', 'spark', 'statistics'],
            },
            'DevOps & Infra': {
                'keywords': ['devops', 'sre', 'infrastructure', 'platform engineer', 'cloud engineer'],
                'titles': ['DevOps Engineer', 'SRE', 'Cloud Engineer', 'Platform Engineer', 'Infrastructure Engineer', 'System Administrator'],
                'skills': ['aws', 'docker', 'kubernetes', 'terraform', 'jenkins', 'ci/cd', 'linux', 'ansible', 'grafana'],
            },
            'QA & Testing': {
                'keywords': ['qa', 'quality assurance', 'tester', 'test engineer', 'sdet'],
                'titles': ['QA Engineer', 'SDET', 'Test Automation Engineer', 'Performance Tester', 'QA Lead'],
                'skills': ['selenium', 'cypress', 'jest', 'pytest', 'unit testing', 'integration testing', 'test automation'],
            },
            'Product': {
                'keywords': ['product manager', 'product owner', 'product management'],
                'titles': ['Product Manager', 'Associate Product Manager', 'Senior Product Manager', 'Product Owner', 'Technical Product Manager'],
                'skills': ['agile', 'scrum', 'jira', 'stakeholder management', 'a/b testing', 'data analysis'],
            },
            'Design': {
                'keywords': ['designer', 'ui/ux', 'ux design', 'ui design', 'graphic design'],
                'titles': ['UI/UX Designer', 'Product Designer', 'UX Researcher', 'Visual Designer', 'Interaction Designer'],
                'skills': ['figma', 'user research', 'prototyping', 'design systems', 'css', 'html'],
            },
            'Security': {
                'keywords': ['security', 'cybersecurity', 'infosec', 'penetration testing'],
                'titles': ['Security Engineer', 'Cybersecurity Analyst', 'Penetration Tester', 'SOC Analyst', 'Security Architect'],
                'skills': ['cybersecurity', 'penetration testing', 'owasp', 'encryption', 'siem', 'compliance'],
            },
        },
        'api_boost_keywords': ['software', 'developer', 'engineer', 'technology'],
    },
    'Finance & Banking': {
        'roles': {
            'Financial Analysis': {
                'keywords': ['financial analyst', 'finance', 'investment', 'portfolio'],
                'titles': ['Financial Analyst', 'Investment Analyst', 'Portfolio Analyst', 'FP&A Analyst', 'Finance Manager'],
                'skills': ['sql', 'python', 'excel', 'tableau', 'power bi', 'financial modeling'],
            },
            'Risk & Compliance': {
                'keywords': ['risk', 'compliance', 'audit', 'regulatory'],
                'titles': ['Risk Analyst', 'Compliance Officer', 'Internal Auditor', 'Regulatory Analyst'],
                'skills': ['risk management', 'compliance', 'sql', 'python', 'statistics'],
            },
            'Fintech Engineering': {
                'keywords': ['fintech', 'payment', 'blockchain', 'trading platform'],
                'titles': ['Fintech Developer', 'Payment Engineer', 'Blockchain Developer', 'Quantitative Developer'],
                'skills': ['python', 'java', 'sql', 'aws', 'docker', 'kubernetes'],
            },
        },
        'api_boost_keywords': ['finance', 'banking', 'financial'],
    },
    'Healthcare': {
        'roles': {
            'Health Informatics': {
                'keywords': ['health informatics', 'ehr', 'medical data', 'clinical data'],
                'titles': ['Health Data Analyst', 'Clinical Data Manager', 'Health Informatics Specialist', 'EHR Analyst'],
                'skills': ['python', 'sql', 'data analysis', 'statistics'],
            },
            'Biotech & Research': {
                'keywords': ['biotech', 'research', 'clinical', 'pharmaceutical'],
                'titles': ['Research Scientist', 'Biostatistician', 'Clinical Research Associate', 'Bioinformatics Analyst'],
                'skills': ['python', 'r', 'statistics', 'machine learning', 'data analysis'],
            },
        },
        'api_boost_keywords': ['healthcare', 'medical', 'health'],
    },
    'E-commerce': {
        'roles': {
            'Engineering': {
                'keywords': ['engineer', 'developer', 'full stack'],
                'titles': ['E-commerce Developer', 'Marketplace Engineer', 'Full Stack Developer'],
                'skills': ['javascript', 'react', 'python', 'sql', 'aws', 'redis', 'elasticsearch'],
            },
            'Marketing & Growth': {
                'keywords': ['marketing', 'growth', 'seo', 'content'],
                'titles': ['Growth Marketing Manager', 'SEO Specialist', 'Performance Marketing Manager', 'Content Strategist'],
                'skills': ['seo', 'a/b testing', 'data analysis', 'sql', 'python'],
            },
            'Operations & Logistics': {
                'keywords': ['operations', 'supply chain', 'logistics', 'warehouse'],
                'titles': ['Operations Manager', 'Supply Chain Analyst', 'Logistics Coordinator', 'Warehouse Manager'],
                'skills': ['data analysis', 'sql', 'excel', 'python'],
            },
        },
        'api_boost_keywords': ['ecommerce', 'retail', 'marketplace'],
    },
    'Education': {
        'roles': {
            'EdTech Engineering': {
                'keywords': ['edtech', 'learning platform', 'lms'],
                'titles': ['EdTech Developer', 'Learning Platform Engineer', 'LMS Developer'],
                'skills': ['javascript', 'react', 'python', 'django', 'aws', 'sql'],
            },
            'Instructional Design': {
                'keywords': ['instructional design', 'curriculum', 'content development'],
                'titles': ['Instructional Designer', 'Curriculum Developer', 'E-Learning Specialist'],
                'skills': ['curriculum design', 'e-learning', 'data analysis'],
            },
        },
        'api_boost_keywords': ['education', 'edtech', 'learning'],
    },
    'Consulting': {
        'roles': {
            'Management Consulting': {
                'keywords': ['consultant', 'advisory', 'strategy'],
                'titles': ['Management Consultant', 'Strategy Analyst', 'Business Consultant', 'Associate Consultant'],
                'skills': ['data analysis', 'presentation', 'project management', 'sql', 'python'],
            },
            'Technology Consulting': {
                'keywords': ['technology consulting', 'it consulting', 'digital transformation'],
                'titles': ['Technology Consultant', 'IT Consultant', 'Digital Transformation Lead', 'Solution Architect'],
                'skills': ['aws', 'azure', 'agile', 'project management', 'python', 'sql'],
            },
        },
        'api_boost_keywords': ['consulting', 'advisory'],
    },
    'Manufacturing': {
        'roles': {
            'Industrial Engineering': {
                'keywords': ['industrial engineer', 'manufacturing', 'process engineer'],
                'titles': ['Industrial Engineer', 'Process Engineer', 'Manufacturing Engineer', 'Quality Engineer'],
                'skills': ['lean manufacturing', 'six sigma', 'data analysis', 'python'],
            },
            'Supply Chain': {
                'keywords': ['supply chain', 'procurement', 'logistics'],
                'titles': ['Supply Chain Manager', 'Procurement Analyst', 'Logistics Manager'],
                'skills': ['data analysis', 'sql', 'excel', 'python'],
            },
        },
        'api_boost_keywords': ['manufacturing', 'industrial'],
    },
    'Media & Entertainment': {
        'roles': {
            'Content & Creative': {
                'keywords': ['content', 'creative', 'media', 'editorial'],
                'titles': ['Content Manager', 'Creative Director', 'Content Strategist', 'Copywriter'],
                'skills': ['content strategy', 'data analysis', 'python'],
            },
            'Streaming & Tech': {
                'keywords': ['streaming', 'ott', 'video platform'],
                'titles': ['Streaming Engineer', 'Video Platform Developer', 'Media Software Engineer'],
                'skills': ['python', 'javascript', 'aws', 'docker', 'kubernetes'],
            },
        },
        'api_boost_keywords': ['media', 'entertainment', 'content'],
    },
    'Telecom': {
        'roles': {
            'Network Engineering': {
                'keywords': ['network', 'telecom', '5g', 'wireless'],
                'titles': ['Network Engineer', 'Telecom Engineer', '5G Engineer', 'Wireless Engineer'],
                'skills': ['networking', 'linux', 'python', 'sql', 'aws'],
            },
        },
        'api_boost_keywords': ['telecom', 'telecommunications'],
    },
    'Government & PSU': {
        'roles': {
            'IT & Digital': {
                'keywords': ['e-governance', 'digital india', 'government it'],
                'titles': ['E-Governance Specialist', 'Government IT Analyst', 'Digital India Developer'],
                'skills': ['java', 'spring boot', 'sql', 'linux', 'oracle'],
            },
        },
        'api_boost_keywords': ['government', 'public sector'],
    },
}


# ---------------------------------------------------------------------------
# Indian cities for location dropdown (predefined, no free typing)
# ---------------------------------------------------------------------------
INDIAN_CITIES = [
    'Bangalore', 'Mumbai', 'Delhi NCR', 'Hyderabad', 'Chennai', 'Pune',
    'Kolkata', 'Ahmedabad', 'Noida', 'Gurgaon', 'Jaipur', 'Chandigarh',
    'Kochi', 'Indore', 'Lucknow', 'Coimbatore', 'Thiruvananthapuram',
    'Visakhapatnam', 'Nagpur', 'Bhubaneswar', 'Remote',
]
