/**
 * LevelUpX AutoFill — Ashby Adapter
 *
 * Ashby (jobs.ashbyhq.com) uses React-based forms with custom components:
 * - Single "Name" field (not first/last split)
 * - Custom typeahead for location ("Start typing...")
 * - Date picker for start date ("Pick date...")
 * - Radio buttons for Yes/No questions
 * - Checkbox groups for multi-select (e.g. office preference)
 */

window.LevelUpXAshby = window.LevelUpXBaseAdapter.create({
  name: 'Ashby',
  hostPatterns: ['ashbyhq.com'],

  formDetector() {
    return !!(
      // Ashby application pages always have /application in the URL
      location.pathname.includes('/application') ||
      // Fallback: detect form structure
      document.querySelector('form[action*="application"]') ||
      document.querySelector('[class*="ashby"], [class*="application-form"]') ||
      // Generic: name + email + file inputs together
      (document.querySelector('input[type="email"]') &&
       document.querySelector('input[type="file"]') &&
       document.querySelector('input[type="tel"]'))
    );
  },

  fieldMap(profile) {
    const b = profile.basics || {};
    const loc = b.location || {};
    const fullName = b.fullName || `${b.firstName || ''} ${b.lastName || ''}`.trim();
    const latestWork = (profile.work && profile.work[0]) || {};
    const latestEdu = (profile.education && profile.education[0]) || {};
    const prefs = profile.applicationPrefs || {};

    const locationStr = loc.city
      ? `${loc.city}${loc.region ? ', ' + loc.region : ''}${loc.country ? ', ' + loc.country : ''}`
      : '';

    const map = {};

    // ── Name (single field, not first/last split) ───────────
    if (fullName) {
      map[fullName] = [
        { method: 'byLabelText', args: ['name'] },
        { method: 'byPlaceholder', args: ['type here'] },
        { method: 'bySelector', args: ['input[name*="name"]:not([name*="last"]):not([name*="first"]):not([type="email"]):not([type="hidden"])'] },
        { method: 'byAriaLabel', args: ['name'] },
      ];
    }

    // ── Email ────────────────────────────────────────────────
    if (b.email) {
      map[b.email] = [
        { method: 'bySelector', args: ['input[type="email"]'] },
        { method: 'byLabelText', args: ['email'] },
        { method: 'byPlaceholder', args: ['email'] },
      ];
    }

    // ── Phone ────────────────────────────────────────────────
    if (b.phone) {
      map[b.phone] = [
        { method: 'bySelector', args: ['input[type="tel"]'] },
        { method: 'byLabelText', args: ['phone'] },
        { method: 'byPlaceholder', args: ['phone'] },
      ];
    }

    // ── LinkedIn ─────────────────────────────────────────────
    if (b.linkedin) {
      map[b.linkedin] = [
        { method: 'byLabelText', args: ['linkedin'] },
        { method: 'bySelector', args: ['input[name*="linkedin"]'] },
        { method: 'byPlaceholder', args: ['linkedin'] },
      ];
    }

    // ── Website / Portfolio ──────────────────────────────────
    if (b.website || b.github) {
      map[b.website || b.github] = [
        { method: 'byLabelText', args: ['website'] },
        { method: 'byLabelText', args: ['portfolio'] },
        { method: 'byPlaceholder', args: ['website'] },
      ];
    }

    // ── Location (typeahead) ─────────────────────────────────
    if (locationStr) {
      map[locationStr] = [
        { method: 'byLabelText', args: ['where are you'] },
        { method: 'byLabelText', args: ['location'] },
        { method: 'byLabelText', args: ['currently located'] },
        { method: 'byPlaceholder', args: ['start typing'] },
      ];
    }

    // ── Current work ─────────────────────────────────────────
    if (latestWork.company) {
      map[latestWork.company] = [
        { method: 'byLabelText', args: ['current company'] },
        { method: 'byLabelText', args: ['company'] },
        { method: 'byLabelText', args: ['employer'] },
      ];
    }
    if (latestWork.position || b.title) {
      map[latestWork.position || b.title] = [
        { method: 'byLabelText', args: ['current title'] },
        { method: 'byLabelText', args: ['job title'] },
        { method: 'byLabelText', args: ['role'] },
      ];
    }

    // ── Education ────────────────────────────────────────────
    if (latestEdu.institution) {
      map[latestEdu.institution] = [
        { method: 'byLabelText', args: ['school'] },
        { method: 'byLabelText', args: ['university'] },
        { method: 'byLabelText', args: ['college'] },
      ];
    }
    if (latestEdu.studyType) {
      map[latestEdu.studyType] = [
        { method: 'byLabelText', args: ['degree'] },
      ];
    }
    if (latestEdu.area) {
      map[latestEdu.area] = [
        { method: 'byLabelText', args: ['major'] },
        { method: 'byLabelText', args: ['field of study'] },
      ];
    }

    // ── GitHub ────────────────────────────────────────────────
    if (b.github) {
      map[b.github] = [
        { method: 'byLabelText', args: ['github'] },
        { method: 'bySelector', args: ['input[name*="github"]'] },
      ];
    }

    return map;
  },

  resumeInputSelectors: [
    'input[type="file"][accept*="pdf"]',
    'input[type="file"][accept*="doc"]',
    'input[type="file"]',
  ],
});
