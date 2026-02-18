/**
 * Resume Editor — State management, form rendering, and live preview
 * Uses Handlebars.js for template rendering and JSON Resume schema for data.
 */

/* ═══════════════════════════════════════════════════════
   STATE
   ═══════════════════════════════════════════════════════ */

const editorState = {
    resumeId: null,
    templateId: 'classic',
    label: 'My Resume',
    isPrimary: false,
    activeSection: 'basics',
    dirty: false,
    saving: false,
    data: {
        basics: {
            name: '', label: '', email: '', phone: '', url: '', summary: '',
            location: { city: '', region: '', countryCode: '' },
            profiles: []
        },
        work: [],
        education: [],
        skills: [],
        projects: [],
        awards: [],
        certificates: [],
        languages: []
    }
};

/* ═══════════════════════════════════════════════════════
   INITIALIZATION
   ═══════════════════════════════════════════════════════ */

function initEditor(serverData) {
    if (serverData && serverData.resume_json) {
        try {
            const parsed = typeof serverData.resume_json === 'string'
                ? JSON.parse(serverData.resume_json) : serverData.resume_json;
            editorState.data = deepMerge(editorState.data, parsed);
        } catch (e) { console.warn('Failed to parse resume JSON:', e); }
    }
    if (serverData) {
        editorState.resumeId = serverData.resume_id || null;
        editorState.templateId = serverData.template_id || 'classic';
        editorState.label = serverData.label || 'My Resume';
        editorState.isPrimary = serverData.is_primary || false;
    }

    // Register Handlebars helpers
    Handlebars.registerHelper('join', function(arr, sep) {
        return Array.isArray(arr) ? arr.join(sep) : '';
    });

    // Set initial values
    const labelInput = document.getElementById('resume-label');
    if (labelInput) labelInput.value = editorState.label;
    const primaryCb = document.getElementById('is-primary');
    if (primaryCb) primaryCb.checked = editorState.isPrimary;

    // Highlight active template
    updateTemplateSelector();

    // Render first section and preview
    switchSection('basics');
    renderPreview();

    // Warn on unsaved changes
    window.addEventListener('beforeunload', function(e) {
        if (editorState.dirty) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
}

/* ═══════════════════════════════════════════════════════
   SECTION TABS
   ═══════════════════════════════════════════════════════ */

const SECTIONS = [
    { id: 'basics', label: 'Basics', icon: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z' },
    { id: 'work', label: 'Work', icon: 'M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
    { id: 'education', label: 'Education', icon: 'M12 14l9-5-9-5-9 5 9 5zm0 0l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z' },
    { id: 'skills', label: 'Skills', icon: 'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z' },
    { id: 'projects', label: 'Projects', icon: 'M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z' },
    { id: 'more', label: 'More', icon: 'M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4' }
];

function switchSection(sectionId) {
    editorState.activeSection = sectionId;
    // Update tab highlights
    document.querySelectorAll('[data-section-tab]').forEach(tab => {
        const isActive = tab.dataset.sectionTab === sectionId;
        tab.classList.toggle('bg-white', isActive);
        tab.classList.toggle('shadow-sm', isActive);
        tab.classList.toggle('text-brand-700', isActive);
        tab.classList.toggle('font-semibold', isActive);
        tab.classList.toggle('text-slate-500', !isActive);
    });
    // Render form
    renderFormSection(sectionId);
}

/* ═══════════════════════════════════════════════════════
   FORM RENDERING
   ═══════════════════════════════════════════════════════ */

function renderFormSection(section) {
    const container = document.getElementById('form-section-content');
    if (!container) return;

    switch (section) {
        case 'basics': container.innerHTML = renderBasicsForm(); break;
        case 'work': container.innerHTML = renderArrayForm('work', workFields); break;
        case 'education': container.innerHTML = renderArrayForm('education', educationFields); break;
        case 'skills': container.innerHTML = renderArrayForm('skills', skillFields); break;
        case 'projects': container.innerHTML = renderArrayForm('projects', projectFields); break;
        case 'more': container.innerHTML = renderMoreForm(); break;
    }

    // Attach input listeners
    container.querySelectorAll('input, textarea, select').forEach(el => {
        el.addEventListener('input', () => {
            collectFormData();
            editorState.dirty = true;
            debouncedPreview();
        });
    });
}

/* ── Basics Form ── */
function renderBasicsForm() {
    const b = editorState.data.basics;
    const loc = b.location || {};
    return `
        <div class="space-y-4">
            <div class="grid grid-cols-2 gap-3">
                ${field('basics.name', 'Full Name', b.name, 'text', 'John Doe')}
                ${field('basics.label', 'Professional Title', b.label, 'text', 'Software Engineer')}
            </div>
            <div class="grid grid-cols-2 gap-3">
                ${field('basics.email', 'Email', b.email, 'email', 'john@example.com')}
                ${field('basics.phone', 'Phone', b.phone, 'tel', '+1-555-0100')}
            </div>
            <div class="grid grid-cols-1 gap-3">
                ${field('basics.url', 'Website', b.url, 'url', 'https://johndoe.dev')}
            </div>
            <div class="grid grid-cols-3 gap-3">
                ${field('basics.location.city', 'City', loc.city, 'text', 'San Francisco')}
                ${field('basics.location.region', 'State / Region', loc.region, 'text', 'CA')}
                ${field('basics.location.countryCode', 'Country', loc.countryCode, 'text', 'US')}
            </div>
            ${textarea('basics.summary', 'Professional Summary', b.summary, 'Briefly describe your professional background and goals...', 3)}

            <!-- Profiles -->
            <div class="border-t border-slate-100 pt-4 mt-4">
                <div class="flex items-center justify-between mb-3">
                    <h4 class="text-sm font-semibold text-slate-700">Online Profiles</h4>
                    <button type="button" onclick="addProfile()" class="text-xs text-brand-600 hover:text-brand-700 font-semibold">+ Add Profile</button>
                </div>
                <div id="profiles-list">
                    ${(b.profiles || []).map((p, i) => renderProfileEntry(p, i)).join('')}
                </div>
            </div>
        </div>
    `;
}

function renderProfileEntry(profile, index) {
    return `
        <div class="grid grid-cols-3 gap-2 mb-2 items-end" data-profile-index="${index}">
            ${field(`profiles.${index}.network`, 'Network', profile.network, 'text', 'LinkedIn', 'text-xs')}
            ${field(`profiles.${index}.username`, 'Username', profile.username, 'text', 'johndoe', 'text-xs')}
            <div class="flex gap-1 items-end">
                <div class="flex-1">${field(`profiles.${index}.url`, 'URL', profile.url, 'url', 'https://linkedin.com/in/johndoe', 'text-xs')}</div>
                <button type="button" onclick="removeProfile(${index})" class="mb-1 p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded transition" title="Remove">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                </button>
            </div>
        </div>
    `;
}

function addProfile() {
    editorState.data.basics.profiles.push({ network: '', username: '', url: '' });
    renderFormSection('basics');
    editorState.dirty = true;
}

function removeProfile(index) {
    editorState.data.basics.profiles.splice(index, 1);
    renderFormSection('basics');
    editorState.dirty = true;
    debouncedPreview();
}

/* ── Array Section Forms (Work, Education, Skills, Projects) ── */

const workFields = [
    { row: [{ key: 'position', label: 'Position', type: 'text', ph: 'Software Engineer' },
             { key: 'name', label: 'Company', type: 'text', ph: 'Google' }] },
    { row: [{ key: 'location', label: 'Location', type: 'text', ph: 'Mountain View, CA' },
             { key: 'startDate', label: 'Start Date', type: 'text', ph: '2020-01' },
             { key: 'endDate', label: 'End Date', type: 'text', ph: '2023-06 or Present' }] },
    { key: 'summary', label: 'Summary', type: 'textarea', ph: 'Brief description of your role...', rows: 2 },
    { key: 'highlights', label: 'Key Achievements (one per line)', type: 'highlights' }
];

const educationFields = [
    { row: [{ key: 'institution', label: 'Institution', type: 'text', ph: 'MIT' },
             { key: 'studyType', label: 'Degree', type: 'text', ph: 'B.Sc.' }] },
    { row: [{ key: 'area', label: 'Field of Study', type: 'text', ph: 'Computer Science' },
             { key: 'score', label: 'GPA', type: 'text', ph: '3.8' }] },
    { row: [{ key: 'startDate', label: 'Start Date', type: 'text', ph: '2016' },
             { key: 'endDate', label: 'End Date', type: 'text', ph: '2020' }] }
];

const skillFields = [
    { row: [{ key: 'name', label: 'Skill Category', type: 'text', ph: 'Programming Languages' },
             { key: 'level', label: 'Level', type: 'select', options: ['', 'Beginner', 'Intermediate', 'Advanced', 'Expert'] }] },
    { key: 'keywords', label: 'Keywords (comma-separated)', type: 'keywords', ph: 'Python, JavaScript, Go' }
];

const projectFields = [
    { row: [{ key: 'name', label: 'Project Name', type: 'text', ph: 'Portfolio Website' },
             { key: 'url', label: 'URL', type: 'url', ph: 'https://github.com/...' }] },
    { row: [{ key: 'startDate', label: 'Start Date', type: 'text', ph: '2023-01' },
             { key: 'endDate', label: 'End Date', type: 'text', ph: '2023-06' }] },
    { key: 'description', label: 'Description', type: 'textarea', ph: 'Brief description...', rows: 2 },
    { key: 'highlights', label: 'Key Highlights (one per line)', type: 'highlights' },
    { key: 'keywords', label: 'Technologies (comma-separated)', type: 'keywords', ph: 'React, Node.js, AWS' }
];

function renderArrayForm(section, fieldDefs) {
    const items = editorState.data[section] || [];
    const sectionLabel = section.charAt(0).toUpperCase() + section.slice(1);
    let html = `<div class="space-y-4">`;

    if (items.length === 0) {
        html += `
            <div class="text-center py-8 text-slate-400">
                <p class="text-sm">No ${section} entries yet</p>
                <button type="button" onclick="addEntry('${section}')"
                    class="mt-3 inline-flex items-center gap-1.5 text-sm text-brand-600 hover:text-brand-700 font-semibold">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                    Add ${sectionLabel} Entry
                </button>
            </div>`;
    } else {
        items.forEach((item, idx) => {
            const title = getEntryTitle(section, item, idx);
            html += `
                <div class="bg-slate-50 rounded-xl p-4 border border-slate-200">
                    <div class="flex items-center justify-between mb-3">
                        <h4 class="text-sm font-semibold text-slate-700">${title}</h4>
                        <button type="button" onclick="removeEntry('${section}', ${idx})"
                            class="text-xs text-red-400 hover:text-red-600 font-medium">Remove</button>
                    </div>
                    <div class="space-y-3">`;

            fieldDefs.forEach(fd => {
                if (fd.row) {
                    html += `<div class="grid grid-cols-${fd.row.length} gap-2">`;
                    fd.row.forEach(f => { html += renderFieldForEntry(section, idx, item, f); });
                    html += `</div>`;
                } else {
                    html += renderFieldForEntry(section, idx, item, fd);
                }
            });

            html += `</div></div>`;
        });

        html += `
            <button type="button" onclick="addEntry('${section}')"
                class="w-full py-2.5 border-2 border-dashed border-slate-200 rounded-xl text-sm text-slate-400 hover:text-brand-600 hover:border-brand-300 transition font-medium">
                + Add Another ${sectionLabel} Entry
            </button>`;
    }

    html += `</div>`;
    return html;
}

function renderFieldForEntry(section, idx, item, f) {
    const name = `${section}.${idx}.${f.key}`;
    const val = item[f.key] || '';

    if (f.type === 'highlights') {
        const highlights = Array.isArray(val) ? val.join('\n') : '';
        return textarea(name, f.label, highlights, f.ph || 'One achievement per line...', 3);
    }
    if (f.type === 'keywords') {
        const keywords = Array.isArray(val) ? val.join(', ') : val;
        return field(name, f.label, keywords, 'text', f.ph);
    }
    if (f.type === 'textarea') {
        return textarea(name, f.label, val, f.ph, f.rows || 2);
    }
    if (f.type === 'select') {
        return selectField(name, f.label, val, f.options);
    }
    return field(name, f.label, val, f.type, f.ph);
}

function getEntryTitle(section, item, idx) {
    switch (section) {
        case 'work': return item.position || item.name || `Position ${idx + 1}`;
        case 'education': return item.institution || item.area || `Education ${idx + 1}`;
        case 'skills': return item.name || `Skill Group ${idx + 1}`;
        case 'projects': return item.name || `Project ${idx + 1}`;
        case 'awards': return item.title || `Award ${idx + 1}`;
        case 'certificates': return item.name || `Certificate ${idx + 1}`;
        case 'languages': return item.language || `Language ${idx + 1}`;
        default: return `Entry ${idx + 1}`;
    }
}

function addEntry(section) {
    const defaults = {
        work: { position: '', name: '', location: '', startDate: '', endDate: '', summary: '', highlights: [] },
        education: { institution: '', studyType: '', area: '', startDate: '', endDate: '', score: '' },
        skills: { name: '', level: '', keywords: [] },
        projects: { name: '', url: '', startDate: '', endDate: '', description: '', highlights: [], keywords: [] },
        awards: { title: '', date: '', awarder: '', summary: '' },
        certificates: { name: '', date: '', issuer: '', url: '' },
        languages: { language: '', fluency: '' }
    };
    if (!editorState.data[section]) editorState.data[section] = [];
    editorState.data[section].push({ ...(defaults[section] || {}) });
    renderFormSection(editorState.activeSection);
    editorState.dirty = true;
}

function removeEntry(section, index) {
    editorState.data[section].splice(index, 1);
    renderFormSection(editorState.activeSection);
    editorState.dirty = true;
    debouncedPreview();
}

/* ── More Section (Awards, Certificates, Languages) ── */

const awardFields = [
    { row: [{ key: 'title', label: 'Title', type: 'text', ph: 'Best Innovation Award' },
             { key: 'awarder', label: 'Awarder', type: 'text', ph: 'Google' }] },
    { row: [{ key: 'date', label: 'Date', type: 'text', ph: '2023-06' }] },
    { key: 'summary', label: 'Summary', type: 'textarea', ph: 'Description...', rows: 2 }
];

const certificateFields = [
    { row: [{ key: 'name', label: 'Certificate Name', type: 'text', ph: 'AWS Solutions Architect' },
             { key: 'issuer', label: 'Issuer', type: 'text', ph: 'Amazon Web Services' }] },
    { row: [{ key: 'date', label: 'Date', type: 'text', ph: '2023-03' },
             { key: 'url', label: 'URL', type: 'url', ph: 'https://...' }] }
];

const languageFields = [
    { row: [{ key: 'language', label: 'Language', type: 'text', ph: 'English' },
             { key: 'fluency', label: 'Fluency', type: 'select', options: ['', 'Elementary', 'Limited Working', 'Professional Working', 'Full Professional', 'Native'] }] }
];

function renderMoreForm() {
    let html = `<div class="space-y-6">`;

    // Awards
    html += `<div>
        <div class="flex items-center justify-between mb-3">
            <h4 class="text-sm font-bold text-slate-700">Awards</h4>
            <button type="button" onclick="addEntry('awards')" class="text-xs text-brand-600 hover:text-brand-700 font-semibold">+ Add Award</button>
        </div>`;
    html += renderSubArrayForm('awards', awardFields);
    html += `</div>`;

    // Certificates
    html += `<div class="border-t border-slate-100 pt-4">
        <div class="flex items-center justify-between mb-3">
            <h4 class="text-sm font-bold text-slate-700">Certifications</h4>
            <button type="button" onclick="addEntry('certificates')" class="text-xs text-brand-600 hover:text-brand-700 font-semibold">+ Add Certification</button>
        </div>`;
    html += renderSubArrayForm('certificates', certificateFields);
    html += `</div>`;

    // Languages
    html += `<div class="border-t border-slate-100 pt-4">
        <div class="flex items-center justify-between mb-3">
            <h4 class="text-sm font-bold text-slate-700">Languages</h4>
            <button type="button" onclick="addEntry('languages')" class="text-xs text-brand-600 hover:text-brand-700 font-semibold">+ Add Language</button>
        </div>`;
    html += renderSubArrayForm('languages', languageFields);
    html += `</div>`;

    html += `</div>`;
    return html;
}

function renderSubArrayForm(section, fieldDefs) {
    const items = editorState.data[section] || [];
    if (items.length === 0) {
        return `<p class="text-xs text-slate-400 italic">None added yet</p>`;
    }
    let html = '';
    items.forEach((item, idx) => {
        const title = getEntryTitle(section, item, idx);
        html += `<div class="bg-slate-50 rounded-lg p-3 border border-slate-200 mb-2">
            <div class="flex items-center justify-between mb-2">
                <span class="text-xs font-medium text-slate-600">${title}</span>
                <button type="button" onclick="removeEntry('${section}', ${idx})" class="text-xs text-red-400 hover:text-red-600">Remove</button>
            </div>
            <div class="space-y-2">`;
        fieldDefs.forEach(fd => {
            if (fd.row) {
                html += `<div class="grid grid-cols-${fd.row.length} gap-2">`;
                fd.row.forEach(f => { html += renderFieldForEntry(section, idx, item, f); });
                html += `</div>`;
            } else {
                html += renderFieldForEntry(section, idx, item, fd);
            }
        });
        html += `</div></div>`;
    });
    return html;
}

/* ═══════════════════════════════════════════════════════
   FORM FIELD HELPERS
   ═══════════════════════════════════════════════════════ */

function field(name, label, value, type, placeholder, extraClass) {
    const cls = extraClass || '';
    return `
        <div>
            <label class="block text-xs font-medium text-slate-500 mb-1 ${cls}">${label}</label>
            <input type="${type}" name="${name}" value="${escHtml(value || '')}"
                placeholder="${placeholder || ''}"
                class="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition bg-white">
        </div>
    `;
}

function textarea(name, label, value, placeholder, rows) {
    return `
        <div>
            <div class="flex items-center justify-between mb-1">
                <label class="text-xs font-medium text-slate-500">${label}</label>
                <button type="button" onclick="aiRewrite('${name}')" data-ai-btn="${name}"
                    class="inline-flex items-center gap-1 text-[10px] text-brand-600 hover:text-brand-700 font-semibold transition">
                    <svg class="w-3 h-3" viewBox="0 0 20 20" fill="currentColor"><path d="M10 1l2.39 5.13L18 7.24l-4 3.89.94 5.51L10 13.77l-4.94 2.87L6 11.13l-4-3.89 5.61-1.11z"/></svg>
                    Write with AI
                </button>
            </div>
            <textarea name="${name}" rows="${rows || 3}"
                placeholder="${placeholder || ''}"
                class="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition bg-white resize-y">${escHtml(value || '')}</textarea>
        </div>
    `;
}

function selectField(name, label, value, options) {
    const opts = options.map(o =>
        `<option value="${o}" ${o === value ? 'selected' : ''}>${o || '-- Select --'}</option>`
    ).join('');
    return `
        <div>
            <label class="block text-xs font-medium text-slate-500 mb-1">${label}</label>
            <select name="${name}" class="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition bg-white">
                ${opts}
            </select>
        </div>
    `;
}

function escHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/* ═══════════════════════════════════════════════════════
   DATA COLLECTION
   ═══════════════════════════════════════════════════════ */

function collectFormData() {
    const container = document.getElementById('form-section-content');
    if (!container) return;

    container.querySelectorAll('input, textarea, select').forEach(el => {
        const name = el.name;
        if (!name) return;
        const val = el.value;
        const parts = name.split('.');

        if (parts[0] === 'basics') {
            if (parts[1] === 'location') {
                editorState.data.basics.location[parts[2]] = val;
            } else {
                editorState.data.basics[parts[1]] = val;
            }
        } else if (parts[0] === 'profiles') {
            const idx = parseInt(parts[1]);
            if (editorState.data.basics.profiles[idx]) {
                editorState.data.basics.profiles[idx][parts[2]] = val;
            }
        } else if (parts.length === 3) {
            const section = parts[0];
            const idx = parseInt(parts[1]);
            const key = parts[2];
            if (editorState.data[section] && editorState.data[section][idx]) {
                // Handle special types
                if (key === 'highlights') {
                    editorState.data[section][idx][key] = val.split('\n').map(s => s.trim()).filter(Boolean);
                } else if (key === 'keywords') {
                    editorState.data[section][idx][key] = val.split(',').map(s => s.trim()).filter(Boolean);
                } else {
                    editorState.data[section][idx][key] = val;
                }
            }
        }
    });

    // Also collect label and primary
    const labelInput = document.getElementById('resume-label');
    if (labelInput) editorState.label = labelInput.value;
    const primaryCb = document.getElementById('is-primary');
    if (primaryCb) editorState.isPrimary = primaryCb.checked;
}

/* ═══════════════════════════════════════════════════════
   LIVE PREVIEW
   ═══════════════════════════════════════════════════════ */

let previewTimer = null;
function debouncedPreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(renderPreview, 300);
}

function renderPreview() {
    const tpl = RESUME_TEMPLATES[editorState.templateId];
    if (!tpl) return;

    try {
        const compiled = Handlebars.compile(tpl.html);
        const html = compiled(editorState.data);
        const iframe = document.getElementById('preview-frame');
        if (!iframe) return;

        const doc = iframe.contentDocument || iframe.contentWindow.document;
        doc.open();
        doc.write(`<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Georgia&display=swap" rel="stylesheet">
<style>${tpl.css}</style>
</head><body>${html}</body></html>`);
        doc.close();
    } catch (e) {
        console.warn('Preview render error:', e);
    }
}

/* ═══════════════════════════════════════════════════════
   TEMPLATE SWITCHING
   ═══════════════════════════════════════════════════════ */

function switchTemplate(templateId) {
    editorState.templateId = templateId;
    editorState.dirty = true;
    updateTemplateSelector();
    renderPreview();
}

function updateTemplateSelector() {
    document.querySelectorAll('[data-template-id]').forEach(btn => {
        const isActive = btn.dataset.templateId === editorState.templateId;
        btn.classList.toggle('ring-2', isActive);
        btn.classList.toggle('ring-brand-500', isActive);
        btn.classList.toggle('border-brand-500', isActive);
        btn.classList.toggle('border-slate-200', !isActive);
    });
}

/* ═══════════════════════════════════════════════════════
   SAVE
   ═══════════════════════════════════════════════════════ */

async function saveResume() {
    if (editorState.saving) return;
    collectFormData();

    editorState.saving = true;
    const saveBtn = document.getElementById('save-btn');
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg> Saving...';
    }

    try {
        const res = await fetch('/resume-studio/editor/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                resume_id: editorState.resumeId,
                resume_json: editorState.data,
                label: editorState.label,
                template_id: editorState.templateId,
                is_primary: editorState.isPrimary
            })
        });
        const result = await res.json();
        if (result.success) {
            editorState.resumeId = result.resume_id;
            editorState.dirty = false;
            // Update URL without reload if new resume
            if (!window.location.pathname.includes(result.resume_id.toString())) {
                window.history.replaceState({}, '', `/resume-studio/editor/${result.resume_id}`);
            }
            showToast('Resume saved successfully!', 'success');
        } else {
            showToast(result.error || 'Failed to save resume', 'error');
        }
    } catch (e) {
        console.error('Save error:', e);
        showToast('Network error — please try again', 'error');
    } finally {
        editorState.saving = false;
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg> Save';
        }
    }
}

/* ═══════════════════════════════════════════════════════
   EXPORT PDF (Browser Print)
   ═══════════════════════════════════════════════════════ */

function exportPDF() {
    collectFormData();
    if (editorState.resumeId) {
        // Open print page in new tab
        window.open(`/resume-studio/editor/print/${editorState.resumeId}`, '_blank');
    } else {
        // For unsaved resumes, print the iframe directly
        const iframe = document.getElementById('preview-frame');
        if (iframe) {
            iframe.contentWindow.focus();
            iframe.contentWindow.print();
        }
    }
}

/* ═══════════════════════════════════════════════════════
   WRITE WITH AI
   ═══════════════════════════════════════════════════════ */

async function aiRewrite(fieldName) {
    collectFormData();
    const el = document.querySelector(`[name="${fieldName}"]`);
    if (!el) return;

    const currentText = el.value.trim();
    if (!currentText) {
        showToast('Please enter some text first, then click Write with AI.', 'error');
        return;
    }

    // Determine field type from name
    let fieldType = 'summary';
    if (fieldName === 'basics.summary') fieldType = 'summary';
    else if (fieldName.match(/^work\.\d+\.summary$/)) fieldType = 'work_summary';
    else if (fieldName.match(/^work\.\d+\.highlights$/)) fieldType = 'work_highlights';
    else if (fieldName.match(/^projects\.\d+\.description$/)) fieldType = 'project_description';
    else if (fieldName.match(/^projects\.\d+\.highlights$/)) fieldType = 'project_highlights';
    else if (fieldName.match(/^awards\.\d+\.summary$/)) fieldType = 'award_summary';

    // Show loading state
    const btn = document.querySelector(`[data-ai-btn="${fieldName}"]`);
    const originalHtml = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<svg class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg> Rewriting...';
    }

    try {
        const res = await fetch('/resume-studio/editor/ai-rewrite', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                field_type: fieldType,
                current_text: currentText,
                job_title: editorState.data.basics.label || ''
            })
        });
        const result = await res.json();

        if (result.success) {
            el.value = result.rewritten_text;
            // Trigger input event to update state + preview
            el.dispatchEvent(new Event('input', { bubbles: true }));
            editorState.dirty = true;
            collectFormData();
            debouncedPreview();
            showToast('AI rewrite applied! 1 credit used.', 'success');
        } else {
            showToast(result.error || 'AI rewrite failed', 'error');
        }
    } catch (e) {
        console.error('AI rewrite error:', e);
        showToast('Network error — please try again', 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }
}

/* ═══════════════════════════════════════════════════════
   MOBILE PREVIEW TOGGLE
   ═══════════════════════════════════════════════════════ */

function toggleMobilePreview() {
    const preview = document.getElementById('preview-panel');
    const toggleBtn = document.getElementById('mobile-preview-toggle');
    if (preview) {
        preview.classList.toggle('hidden');
        if (toggleBtn) {
            toggleBtn.textContent = preview.classList.contains('hidden') ? 'Show Preview' : 'Hide Preview';
        }
        if (!preview.classList.contains('hidden')) {
            renderPreview();
        }
    }
}

/* ═══════════════════════════════════════════════════════
   TOAST NOTIFICATIONS
   ═══════════════════════════════════════════════════════ */

function showToast(message, type) {
    const toast = document.createElement('div');
    toast.className = `fixed top-4 right-4 z-50 px-5 py-3 rounded-xl shadow-lg text-sm font-medium text-white transition-all transform ${
        type === 'success' ? 'bg-emerald-500' : 'bg-red-500'
    }`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3000);
}

/* ═══════════════════════════════════════════════════════
   UTILITIES
   ═══════════════════════════════════════════════════════ */

function deepMerge(target, source) {
    const result = { ...target };
    for (const key of Object.keys(source)) {
        if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])
            && target[key] && typeof target[key] === 'object' && !Array.isArray(target[key])) {
            result[key] = deepMerge(target[key], source[key]);
        } else {
            result[key] = source[key];
        }
    }
    return result;
}
