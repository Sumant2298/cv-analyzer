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
