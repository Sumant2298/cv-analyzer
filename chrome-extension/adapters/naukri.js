/**
 * LevelUpX AutoFill — Naukri Adapter
 *
 * Naukri has multiple apply paths: quick apply modal, chatbot, full apply.
 * Fields use standard names/classes.
 */

window.LevelUpXNaukri = window.LevelUpXBaseAdapter.create({
  name: 'Naukri',
  hostPatterns: ['naukri.com'],

  formDetector() {
    return !!(
      document.querySelector('.apply-modal, .chatbot-container, #apply-dialog') ||
      document.querySelector('[class*="applyForm"], [class*="apply-form"]') ||
      document.querySelector('input[name="name"], input[name="email"]') ||
      location.pathname.includes('/apply')
    );
  },

  fieldMap(profile) {
    const b = profile.basics || {};
    const loc = b.location || {};
    const latestWork = (profile.work && profile.work[0]) || {};
    const latestEdu = (profile.education && profile.education[0]) || {};
    const fullName = b.fullName || `${b.firstName || ''} ${b.lastName || ''}`.trim();

    const map = {
      [fullName]: [
        { method: 'byName', args: ['name'] },
        { method: 'bySelector', args: ['input[name="name"]'] },
        { method: 'byLabelText', args: ['name'] },
        { method: 'byLabelText', args: ['full name'] },
        { method: 'byPlaceholder', args: ['name'] },
        { method: 'byPlaceholder', args: ['full name'] },
      ],
      [b.email]: [
        { method: 'byName', args: ['email'] },
        { method: 'bySelector', args: ['input[type="email"]'] },
        { method: 'bySelector', args: ['input[name="email"]'] },
        { method: 'byLabelText', args: ['email'] },
        { method: 'byPlaceholder', args: ['email'] },
      ],
      [b.phone]: [
        { method: 'byName', args: ['mobile'] },
        { method: 'byName', args: ['phone'] },
        { method: 'bySelector', args: ['input[type="tel"]'] },
        { method: 'bySelector', args: ['input[name="mobile"]'] },
        { method: 'byLabelText', args: ['mobile'] },
        { method: 'byLabelText', args: ['phone'] },
        { method: 'byPlaceholder', args: ['mobile'] },
      ],
      [loc.city]: [
        { method: 'byName', args: ['currentLocation'] },
        { method: 'byName', args: ['location'] },
        { method: 'byLabelText', args: ['current location'] },
        { method: 'byLabelText', args: ['location'] },
        { method: 'byPlaceholder', args: ['location'] },
        { method: 'byPlaceholder', args: ['city'] },
      ],
      [b.title || latestWork.position]: [
        { method: 'byName', args: ['designation'] },
        { method: 'byLabelText', args: ['designation'] },
        { method: 'byLabelText', args: ['current designation'] },
        { method: 'byPlaceholder', args: ['designation'] },
        { method: 'byLabelText', args: ['job title'] },
        { method: 'byLabelText', args: ['current title'] },
      ],
    };

    // ── Current work ─────────────────────────────────────────────
    if (latestWork.company) {
      map[latestWork.company] = [
        { method: 'byName', args: ['currentCompany'] },
        { method: 'byName', args: ['company'] },
        { method: 'byLabelText', args: ['current company'] },
        { method: 'byLabelText', args: ['company name'] },
        { method: 'byLabelText', args: ['current employer'] },
        { method: 'byLabelText', args: ['organization'] },
        { method: 'byPlaceholder', args: ['company'] },
      ];
    }

    // ── Education ────────────────────────────────────────────────
    if (latestEdu.institution) {
      map[latestEdu.institution] = [
        { method: 'byLabelText', args: ['university'] },
        { method: 'byLabelText', args: ['college'] },
        { method: 'byLabelText', args: ['school'] },
        { method: 'byLabelText', args: ['institution'] },
        { method: 'byPlaceholder', args: ['university'] },
      ];
    }
    if (latestEdu.studyType) {
      map[latestEdu.studyType] = [
        { method: 'byLabelText', args: ['degree'] },
        { method: 'byLabelText', args: ['highest degree'] },
        { method: 'byLabelText', args: ['qualification'] },
        { method: 'byLabelText', args: ['education'] },
      ];
    }
    if (latestEdu.area) {
      map[latestEdu.area] = [
        { method: 'byLabelText', args: ['specialization'] },
        { method: 'byLabelText', args: ['major'] },
        { method: 'byLabelText', args: ['field of study'] },
        { method: 'byLabelText', args: ['course'] },
      ];
    }

    // ── Links ────────────────────────────────────────────────────
    if (b.linkedin) {
      map[b.linkedin] = [
        { method: 'byLabelText', args: ['linkedin'] },
        { method: 'byPlaceholder', args: ['linkedin'] },
      ];
    }
    if (b.github) {
      map[b.github] = [
        { method: 'byLabelText', args: ['github'] },
        { method: 'byPlaceholder', args: ['github'] },
      ];
    }
    if (b.website) {
      map[b.website] = [
        { method: 'byLabelText', args: ['website'] },
        { method: 'byLabelText', args: ['portfolio'] },
      ];
    }

    return map;
  },

  resumeInputSelectors: [
    'input[type="file"][name*="resume"]',
    'input[type="file"][name*="cv"]',
    'input[type="file"][id*="resume"]',
    '.chatbot-container input[type="file"]',
    'input[type="file"]',
  ],
});
