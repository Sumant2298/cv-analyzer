/**
 * Resume Templates — Handlebars templates + CSS for live preview rendering
 * Each template renders a JSON Resume schema object into a print-ready A4 layout.
 */

const RESUME_TEMPLATES = {

    /* ═══════════════════════════════════════════════════════
       CLASSIC — Traditional professional layout
       ═══════════════════════════════════════════════════════ */
    classic: {
        name: 'Classic',
        description: 'Traditional professional layout with clean sections',
        css: `
            @page { size: A4; margin: 0; }
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Georgia', 'Times New Roman', serif; font-size: 10.5pt; line-height: 1.5; color: #1a1a1a; padding: 40px 48px; max-width: 210mm; background: #fff; }
            h1 { font-size: 22pt; font-weight: 700; color: #111; letter-spacing: -0.5px; margin-bottom: 2px; }
            .label-title { font-size: 11pt; color: #4f46e5; font-weight: 500; margin-bottom: 8px; }
            .contact-bar { display: flex; flex-wrap: wrap; gap: 12px; font-size: 9pt; color: #555; padding: 8px 0; border-bottom: 2px solid #e5e7eb; margin-bottom: 16px; }
            .contact-bar a { color: #4f46e5; text-decoration: none; }
            .section { margin-bottom: 14px; }
            .section-title { font-size: 11pt; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #4f46e5; border-bottom: 1px solid #e5e7eb; padding-bottom: 3px; margin-bottom: 8px; }
            .entry { margin-bottom: 10px; }
            .entry-header { display: flex; justify-content: space-between; align-items: baseline; }
            .entry-header .position { font-weight: 700; font-size: 10.5pt; }
            .entry-header .company { color: #555; }
            .entry-header .dates { font-size: 9pt; color: #777; white-space: nowrap; }
            .entry-location { font-size: 9pt; color: #777; margin-top: 1px; }
            .entry-summary { font-size: 10pt; color: #333; margin-top: 3px; }
            .highlights { list-style: disc; padding-left: 18px; margin-top: 4px; }
            .highlights li { font-size: 10pt; color: #333; margin-bottom: 2px; }
            .summary-text { font-size: 10.5pt; color: #333; line-height: 1.6; }
            .skills-grid { display: flex; flex-wrap: wrap; gap: 8px 20px; }
            .skill-group .skill-name { font-weight: 700; font-size: 10pt; }
            .skill-group .skill-keywords { font-size: 9.5pt; color: #555; }
            .edu-degree { font-weight: 700; }
            .edu-institution { color: #555; }
            .edu-score { font-size: 9pt; color: #777; }
            .profiles { display: flex; flex-wrap: wrap; gap: 10px; }
            .profiles a { font-size: 9pt; color: #4f46e5; text-decoration: none; }
            .lang-item { display: inline-block; margin-right: 16px; font-size: 10pt; }
            .lang-fluency { color: #777; font-size: 9pt; }
            .award-title { font-weight: 700; }
            .award-meta { font-size: 9pt; color: #777; }
            .cert-name { font-weight: 700; }
            .cert-meta { font-size: 9pt; color: #777; }
            .cert-name a { color: #4f46e5; text-decoration: none; }
            .project-name { font-weight: 700; }
            .project-name a { color: #4f46e5; text-decoration: none; }
            .project-keywords { font-size: 9pt; color: #777; margin-top: 2px; }
        `,
        html: `
            <h1>{{basics.name}}</h1>
            {{#if basics.label}}<div class="label-title">{{basics.label}}</div>{{/if}}

            <div class="contact-bar">
                {{#if basics.email}}<span>{{basics.email}}</span>{{/if}}
                {{#if basics.phone}}<span>{{basics.phone}}</span>{{/if}}
                {{#if basics.url}}<a href="{{basics.url}}">{{basics.url}}</a>{{/if}}
                {{#if basics.location}}
                    {{#if basics.location.city}}<span>{{basics.location.city}}{{#if basics.location.region}}, {{basics.location.region}}{{/if}}{{#if basics.location.countryCode}} {{basics.location.countryCode}}{{/if}}</span>{{/if}}
                {{/if}}
                {{#each basics.profiles}}
                    <a href="{{this.url}}">{{this.network}}: {{this.username}}</a>
                {{/each}}
            </div>

            {{#if basics.summary}}
            <div class="section">
                <div class="section-title">Summary</div>
                <div class="summary-text">{{basics.summary}}</div>
            </div>
            {{/if}}

            {{#if work.length}}
            <div class="section">
                <div class="section-title">Experience</div>
                {{#each work}}
                <div class="entry">
                    <div class="entry-header">
                        <div><span class="position">{{this.position}}</span>{{#if this.name}} <span class="company">at {{this.name}}</span>{{/if}}</div>
                        <span class="dates">{{this.startDate}}{{#if this.endDate}} &ndash; {{this.endDate}}{{else}} &ndash; Present{{/if}}</span>
                    </div>
                    {{#if this.location}}<div class="entry-location">{{this.location}}</div>{{/if}}
                    {{#if this.summary}}<div class="entry-summary">{{this.summary}}</div>{{/if}}
                    {{#if this.highlights.length}}
                    <ul class="highlights">
                        {{#each this.highlights}}<li>{{this}}</li>{{/each}}
                    </ul>
                    {{/if}}
                </div>
                {{/each}}
            </div>
            {{/if}}

            {{#if education.length}}
            <div class="section">
                <div class="section-title">Education</div>
                {{#each education}}
                <div class="entry">
                    <div class="entry-header">
                        <div><span class="edu-degree">{{this.studyType}}{{#if this.area}} in {{this.area}}{{/if}}</span> <span class="edu-institution">&mdash; {{this.institution}}</span></div>
                        <span class="dates">{{this.startDate}}{{#if this.endDate}} &ndash; {{this.endDate}}{{/if}}</span>
                    </div>
                    {{#if this.score}}<div class="edu-score">GPA: {{this.score}}</div>{{/if}}
                </div>
                {{/each}}
            </div>
            {{/if}}

            {{#if skills.length}}
            <div class="section">
                <div class="section-title">Skills</div>
                <div class="skills-grid">
                    {{#each skills}}
                    <div class="skill-group">
                        <span class="skill-name">{{this.name}}:</span>
                        <span class="skill-keywords">{{join this.keywords ", "}}</span>
                    </div>
                    {{/each}}
                </div>
            </div>
            {{/if}}

            {{#if projects.length}}
            <div class="section">
                <div class="section-title">Projects</div>
                {{#each projects}}
                <div class="entry">
                    <div class="entry-header">
                        <div><span class="project-name">{{#if this.url}}<a href="{{this.url}}">{{this.name}}</a>{{else}}{{this.name}}{{/if}}</span></div>
                        {{#if this.startDate}}<span class="dates">{{this.startDate}}{{#if this.endDate}} &ndash; {{this.endDate}}{{/if}}</span>{{/if}}
                    </div>
                    {{#if this.description}}<div class="entry-summary">{{this.description}}</div>{{/if}}
                    {{#if this.highlights.length}}
                    <ul class="highlights">
                        {{#each this.highlights}}<li>{{this}}</li>{{/each}}
                    </ul>
                    {{/if}}
                    {{#if this.keywords.length}}<div class="project-keywords">{{join this.keywords " &middot; "}}</div>{{/if}}
                </div>
                {{/each}}
            </div>
            {{/if}}

            {{#if awards.length}}
            <div class="section">
                <div class="section-title">Awards</div>
                {{#each awards}}
                <div class="entry">
                    <span class="award-title">{{this.title}}</span>
                    <span class="award-meta">{{#if this.awarder}} &mdash; {{this.awarder}}{{/if}}{{#if this.date}} ({{this.date}}){{/if}}</span>
                    {{#if this.summary}}<div class="entry-summary">{{this.summary}}</div>{{/if}}
                </div>
                {{/each}}
            </div>
            {{/if}}

            {{#if certificates.length}}
            <div class="section">
                <div class="section-title">Certifications</div>
                {{#each certificates}}
                <div class="entry">
                    <span class="cert-name">{{#if this.url}}<a href="{{this.url}}">{{this.name}}</a>{{else}}{{this.name}}{{/if}}</span>
                    <span class="cert-meta">{{#if this.issuer}} &mdash; {{this.issuer}}{{/if}}{{#if this.date}} ({{this.date}}){{/if}}</span>
                </div>
                {{/each}}
            </div>
            {{/if}}

            {{#if languages.length}}
            <div class="section">
                <div class="section-title">Languages</div>
                {{#each languages}}
                <span class="lang-item">{{this.language}} <span class="lang-fluency">({{this.fluency}})</span></span>
                {{/each}}
            </div>
            {{/if}}
        `
    },

    /* ═══════════════════════════════════════════════════════
       MODERN — Two-column with left sidebar
       ═══════════════════════════════════════════════════════ */
    modern: {
        name: 'Modern',
        description: 'Clean two-column design with colored sidebar',
        css: `
            @page { size: A4; margin: 0; }
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif; font-size: 10pt; line-height: 1.5; color: #1a1a1a; background: #fff; display: flex; min-height: 297mm; }
            .sidebar { width: 220px; min-width: 220px; background: #1e1b4b; color: #e0e7ff; padding: 36px 24px; }
            .main { flex: 1; padding: 36px 32px; }
            .sidebar h1 { font-size: 20pt; font-weight: 800; color: #fff; margin-bottom: 4px; letter-spacing: -0.5px; }
            .sidebar .label-title { font-size: 10pt; color: #a5b4fc; font-weight: 500; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid #3730a3; }
            .sidebar .section { margin-bottom: 16px; }
            .sidebar .section-title { font-size: 8pt; font-weight: 700; text-transform: uppercase; letter-spacing: 2px; color: #818cf8; margin-bottom: 6px; }
            .sidebar .contact-item { font-size: 9pt; color: #c7d2fe; margin-bottom: 4px; word-break: break-all; }
            .sidebar .contact-item a { color: #a5b4fc; text-decoration: none; }
            .sidebar .skill-name { font-size: 9.5pt; font-weight: 600; color: #fff; margin-top: 6px; }
            .sidebar .skill-keywords { font-size: 8.5pt; color: #c7d2fe; }
            .sidebar .lang-item { font-size: 9.5pt; color: #e0e7ff; display: block; margin-bottom: 3px; }
            .sidebar .lang-fluency { color: #a5b4fc; font-size: 8.5pt; }
            .sidebar .profile-link { display: block; font-size: 9pt; color: #a5b4fc; text-decoration: none; margin-bottom: 3px; }
            .main .section { margin-bottom: 16px; }
            .main .section-title { font-size: 11pt; font-weight: 700; color: #1e1b4b; border-bottom: 2px solid #4f46e5; padding-bottom: 3px; margin-bottom: 10px; }
            .main .summary-text { font-size: 10pt; color: #374151; line-height: 1.6; }
            .main .entry { margin-bottom: 12px; }
            .main .entry-header { display: flex; justify-content: space-between; align-items: baseline; }
            .main .position { font-weight: 700; font-size: 10.5pt; color: #111; }
            .main .company { color: #4f46e5; font-weight: 500; }
            .main .dates { font-size: 9pt; color: #6b7280; white-space: nowrap; }
            .main .entry-location { font-size: 9pt; color: #6b7280; }
            .main .entry-summary { font-size: 9.5pt; color: #374151; margin-top: 3px; }
            .main .highlights { list-style: none; padding-left: 0; margin-top: 4px; }
            .main .highlights li { font-size: 9.5pt; color: #374151; margin-bottom: 2px; padding-left: 14px; position: relative; }
            .main .highlights li::before { content: "\\25B8"; position: absolute; left: 0; color: #4f46e5; }
            .main .edu-degree { font-weight: 700; }
            .main .edu-institution { color: #4f46e5; }
            .main .edu-score { font-size: 9pt; color: #6b7280; }
            .main .project-name { font-weight: 700; }
            .main .project-name a { color: #4f46e5; text-decoration: none; }
            .main .project-keywords { font-size: 8.5pt; color: #6b7280; margin-top: 2px; }
            .main .award-title { font-weight: 700; }
            .main .award-meta { font-size: 9pt; color: #6b7280; }
            .main .cert-name { font-weight: 700; }
            .main .cert-name a { color: #4f46e5; text-decoration: none; }
            .main .cert-meta { font-size: 9pt; color: #6b7280; }
        `,
        html: `
            <div class="sidebar">
                <h1>{{basics.name}}</h1>
                {{#if basics.label}}<div class="label-title">{{basics.label}}</div>{{/if}}

                <div class="section">
                    <div class="section-title">Contact</div>
                    {{#if basics.email}}<div class="contact-item">{{basics.email}}</div>{{/if}}
                    {{#if basics.phone}}<div class="contact-item">{{basics.phone}}</div>{{/if}}
                    {{#if basics.url}}<div class="contact-item"><a href="{{basics.url}}">{{basics.url}}</a></div>{{/if}}
                    {{#if basics.location}}
                        {{#if basics.location.city}}<div class="contact-item">{{basics.location.city}}{{#if basics.location.region}}, {{basics.location.region}}{{/if}}</div>{{/if}}
                    {{/if}}
                </div>

                {{#if basics.profiles.length}}
                <div class="section">
                    <div class="section-title">Profiles</div>
                    {{#each basics.profiles}}
                    <a class="profile-link" href="{{this.url}}">{{this.network}}: {{this.username}}</a>
                    {{/each}}
                </div>
                {{/if}}

                {{#if skills.length}}
                <div class="section">
                    <div class="section-title">Skills</div>
                    {{#each skills}}
                    <div class="skill-name">{{this.name}}</div>
                    <div class="skill-keywords">{{join this.keywords ", "}}</div>
                    {{/each}}
                </div>
                {{/if}}

                {{#if languages.length}}
                <div class="section">
                    <div class="section-title">Languages</div>
                    {{#each languages}}
                    <span class="lang-item">{{this.language}} <span class="lang-fluency">({{this.fluency}})</span></span>
                    {{/each}}
                </div>
                {{/if}}

                {{#if certificates.length}}
                <div class="section">
                    <div class="section-title">Certifications</div>
                    {{#each certificates}}
                    <div class="contact-item" style="margin-bottom:6px;">
                        <strong style="color:#fff;">{{this.name}}</strong>
                        {{#if this.issuer}}<br>{{this.issuer}}{{/if}}
                        {{#if this.date}}<br><span style="font-size:8pt;color:#a5b4fc;">{{this.date}}</span>{{/if}}
                    </div>
                    {{/each}}
                </div>
                {{/if}}
            </div>

            <div class="main">
                {{#if basics.summary}}
                <div class="section">
                    <div class="section-title">Summary</div>
                    <div class="summary-text">{{basics.summary}}</div>
                </div>
                {{/if}}

                {{#if work.length}}
                <div class="section">
                    <div class="section-title">Experience</div>
                    {{#each work}}
                    <div class="entry">
                        <div class="entry-header">
                            <div><span class="position">{{this.position}}</span>{{#if this.name}} <span class="company">| {{this.name}}</span>{{/if}}</div>
                            <span class="dates">{{this.startDate}}{{#if this.endDate}} &ndash; {{this.endDate}}{{else}} &ndash; Present{{/if}}</span>
                        </div>
                        {{#if this.location}}<div class="entry-location">{{this.location}}</div>{{/if}}
                        {{#if this.summary}}<div class="entry-summary">{{this.summary}}</div>{{/if}}
                        {{#if this.highlights.length}}
                        <ul class="highlights">
                            {{#each this.highlights}}<li>{{this}}</li>{{/each}}
                        </ul>
                        {{/if}}
                    </div>
                    {{/each}}
                </div>
                {{/if}}

                {{#if education.length}}
                <div class="section">
                    <div class="section-title">Education</div>
                    {{#each education}}
                    <div class="entry">
                        <div class="entry-header">
                            <div><span class="edu-degree">{{this.studyType}}{{#if this.area}} in {{this.area}}{{/if}}</span> <span class="edu-institution">&mdash; {{this.institution}}</span></div>
                            <span class="dates">{{this.startDate}}{{#if this.endDate}} &ndash; {{this.endDate}}{{/if}}</span>
                        </div>
                        {{#if this.score}}<div class="edu-score">GPA: {{this.score}}</div>{{/if}}
                    </div>
                    {{/each}}
                </div>
                {{/if}}

                {{#if projects.length}}
                <div class="section">
                    <div class="section-title">Projects</div>
                    {{#each projects}}
                    <div class="entry">
                        <div class="entry-header">
                            <div><span class="project-name">{{#if this.url}}<a href="{{this.url}}">{{this.name}}</a>{{else}}{{this.name}}{{/if}}</span></div>
                            {{#if this.startDate}}<span class="dates">{{this.startDate}}{{#if this.endDate}} &ndash; {{this.endDate}}{{/if}}</span>{{/if}}
                        </div>
                        {{#if this.description}}<div class="entry-summary">{{this.description}}</div>{{/if}}
                        {{#if this.highlights.length}}
                        <ul class="highlights">
                            {{#each this.highlights}}<li>{{this}}</li>{{/each}}
                        </ul>
                        {{/if}}
                        {{#if this.keywords.length}}<div class="project-keywords">{{join this.keywords " &middot; "}}</div>{{/if}}
                    </div>
                    {{/each}}
                </div>
                {{/if}}

                {{#if awards.length}}
                <div class="section">
                    <div class="section-title">Awards</div>
                    {{#each awards}}
                    <div class="entry">
                        <span class="award-title">{{this.title}}</span>
                        <span class="award-meta">{{#if this.awarder}} &mdash; {{this.awarder}}{{/if}}{{#if this.date}} ({{this.date}}){{/if}}</span>
                        {{#if this.summary}}<div class="entry-summary">{{this.summary}}</div>{{/if}}
                    </div>
                    {{/each}}
                </div>
                {{/if}}
            </div>
        `
    },

    /* ═══════════════════════════════════════════════════════
       MINIMAL — Clean single-column, maximum whitespace
       ═══════════════════════════════════════════════════════ */
    minimal: {
        name: 'Minimal',
        description: 'Simple and elegant single-column layout',
        css: `
            @page { size: A4; margin: 0; }
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif; font-size: 10pt; line-height: 1.6; color: #333; padding: 44px 52px; max-width: 210mm; background: #fff; }
            h1 { font-size: 26pt; font-weight: 300; color: #111; letter-spacing: -1px; }
            .label-title { font-size: 11pt; color: #666; font-weight: 400; margin-bottom: 6px; }
            .contact-bar { display: flex; flex-wrap: wrap; gap: 8px; font-size: 9pt; color: #888; padding: 10px 0; border-top: 1px solid #ddd; border-bottom: 1px solid #ddd; margin-bottom: 20px; }
            .contact-bar span { white-space: nowrap; }
            .contact-bar a { color: #333; text-decoration: none; border-bottom: 1px dotted #aaa; }
            .section { margin-bottom: 18px; }
            .section-title { font-size: 9pt; font-weight: 600; text-transform: uppercase; letter-spacing: 3px; color: #999; margin-bottom: 8px; }
            .entry { margin-bottom: 12px; }
            .entry-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 2px; }
            .position { font-weight: 600; font-size: 10.5pt; color: #111; }
            .company { color: #666; font-weight: 400; }
            .dates { font-size: 9pt; color: #999; }
            .entry-location { font-size: 9pt; color: #999; }
            .entry-summary { font-size: 10pt; color: #444; margin-top: 3px; }
            .highlights { list-style: none; padding-left: 0; margin-top: 4px; }
            .highlights li { font-size: 9.5pt; color: #444; margin-bottom: 2px; padding-left: 12px; position: relative; }
            .highlights li::before { content: "\\2013"; position: absolute; left: 0; color: #bbb; }
            .summary-text { font-size: 10.5pt; color: #444; line-height: 1.7; }
            .skills-grid { display: flex; flex-wrap: wrap; gap: 6px 24px; }
            .skill-group .skill-name { font-weight: 600; font-size: 9.5pt; color: #111; }
            .skill-group .skill-keywords { font-size: 9pt; color: #666; }
            .edu-degree { font-weight: 600; color: #111; }
            .edu-institution { color: #666; }
            .edu-score { font-size: 9pt; color: #999; }
            .project-name { font-weight: 600; color: #111; }
            .project-name a { color: #111; text-decoration: none; border-bottom: 1px dotted #aaa; }
            .project-keywords { font-size: 8.5pt; color: #999; margin-top: 2px; }
            .lang-item { display: inline-block; margin-right: 20px; font-size: 10pt; color: #333; }
            .lang-fluency { color: #999; font-size: 9pt; }
            .award-title { font-weight: 600; }
            .award-meta { font-size: 9pt; color: #999; }
            .cert-name { font-weight: 600; }
            .cert-name a { color: #111; text-decoration: none; border-bottom: 1px dotted #aaa; }
            .cert-meta { font-size: 9pt; color: #999; }
            .profiles a { font-size: 9pt; color: #555; text-decoration: none; margin-right: 12px; border-bottom: 1px dotted #aaa; }
        `,
        html: `
            <h1>{{basics.name}}</h1>
            {{#if basics.label}}<div class="label-title">{{basics.label}}</div>{{/if}}

            <div class="contact-bar">
                {{#if basics.email}}<span>{{basics.email}}</span>{{/if}}
                {{#if basics.phone}}<span>{{basics.phone}}</span>{{/if}}
                {{#if basics.url}}<span><a href="{{basics.url}}">{{basics.url}}</a></span>{{/if}}
                {{#if basics.location}}
                    {{#if basics.location.city}}<span>{{basics.location.city}}{{#if basics.location.region}}, {{basics.location.region}}{{/if}}</span>{{/if}}
                {{/if}}
                {{#each basics.profiles}}
                    <span><a href="{{this.url}}">{{this.network}}</a></span>
                {{/each}}
            </div>

            {{#if basics.summary}}
            <div class="section">
                <div class="section-title">About</div>
                <div class="summary-text">{{basics.summary}}</div>
            </div>
            {{/if}}

            {{#if work.length}}
            <div class="section">
                <div class="section-title">Experience</div>
                {{#each work}}
                <div class="entry">
                    <div class="entry-header">
                        <div><span class="position">{{this.position}}</span>{{#if this.name}}<span class="company"> &mdash; {{this.name}}</span>{{/if}}</div>
                        <span class="dates">{{this.startDate}}{{#if this.endDate}} &ndash; {{this.endDate}}{{else}} &ndash; Present{{/if}}</span>
                    </div>
                    {{#if this.location}}<div class="entry-location">{{this.location}}</div>{{/if}}
                    {{#if this.summary}}<div class="entry-summary">{{this.summary}}</div>{{/if}}
                    {{#if this.highlights.length}}
                    <ul class="highlights">
                        {{#each this.highlights}}<li>{{this}}</li>{{/each}}
                    </ul>
                    {{/if}}
                </div>
                {{/each}}
            </div>
            {{/if}}

            {{#if education.length}}
            <div class="section">
                <div class="section-title">Education</div>
                {{#each education}}
                <div class="entry">
                    <div class="entry-header">
                        <div><span class="edu-degree">{{this.studyType}}{{#if this.area}} in {{this.area}}{{/if}}</span> <span class="edu-institution">&mdash; {{this.institution}}</span></div>
                        <span class="dates">{{this.startDate}}{{#if this.endDate}} &ndash; {{this.endDate}}{{/if}}</span>
                    </div>
                    {{#if this.score}}<div class="edu-score">GPA: {{this.score}}</div>{{/if}}
                </div>
                {{/each}}
            </div>
            {{/if}}

            {{#if skills.length}}
            <div class="section">
                <div class="section-title">Skills</div>
                <div class="skills-grid">
                    {{#each skills}}
                    <div class="skill-group">
                        <span class="skill-name">{{this.name}}</span>
                        <span class="skill-keywords">{{join this.keywords ", "}}</span>
                    </div>
                    {{/each}}
                </div>
            </div>
            {{/if}}

            {{#if projects.length}}
            <div class="section">
                <div class="section-title">Projects</div>
                {{#each projects}}
                <div class="entry">
                    <div class="entry-header">
                        <div><span class="project-name">{{#if this.url}}<a href="{{this.url}}">{{this.name}}</a>{{else}}{{this.name}}{{/if}}</span></div>
                        {{#if this.startDate}}<span class="dates">{{this.startDate}}{{#if this.endDate}} &ndash; {{this.endDate}}{{/if}}</span>{{/if}}
                    </div>
                    {{#if this.description}}<div class="entry-summary">{{this.description}}</div>{{/if}}
                    {{#if this.highlights.length}}
                    <ul class="highlights">
                        {{#each this.highlights}}<li>{{this}}</li>{{/each}}
                    </ul>
                    {{/if}}
                    {{#if this.keywords.length}}<div class="project-keywords">{{join this.keywords " &middot; "}}</div>{{/if}}
                </div>
                {{/each}}
            </div>
            {{/if}}

            {{#if awards.length}}
            <div class="section">
                <div class="section-title">Awards</div>
                {{#each awards}}
                <div class="entry">
                    <span class="award-title">{{this.title}}</span>
                    <span class="award-meta">{{#if this.awarder}} &mdash; {{this.awarder}}{{/if}}{{#if this.date}} ({{this.date}}){{/if}}</span>
                    {{#if this.summary}}<div class="entry-summary">{{this.summary}}</div>{{/if}}
                </div>
                {{/each}}
            </div>
            {{/if}}

            {{#if certificates.length}}
            <div class="section">
                <div class="section-title">Certifications</div>
                {{#each certificates}}
                <div class="entry">
                    <span class="cert-name">{{#if this.url}}<a href="{{this.url}}">{{this.name}}</a>{{else}}{{this.name}}{{/if}}</span>
                    <span class="cert-meta">{{#if this.issuer}} &mdash; {{this.issuer}}{{/if}}{{#if this.date}} ({{this.date}}){{/if}}</span>
                </div>
                {{/each}}
            </div>
            {{/if}}

            {{#if languages.length}}
            <div class="section">
                <div class="section-title">Languages</div>
                {{#each languages}}
                <span class="lang-item">{{this.language}} <span class="lang-fluency">({{this.fluency}})</span></span>
                {{/each}}
            </div>
            {{/if}}
        `
    }
};
