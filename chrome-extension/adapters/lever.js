/**
 * LevelUpX AutoFill — Lever Adapter
 *
 * Lever uses standard HTML forms with straightforward field names.
 */

window.LevelUpXLever = window.LevelUpXBaseAdapter.create({
  name: 'Lever',
  hostPatterns: ['jobs.lever.co'],

  formDetector() {
    return !!document.querySelector('.application-form, form[action*="apply"], .postings-btn-wrapper');
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
        { method: 'byLabelText', args: ['full name'] },
        { method: 'byLabelText', args: ['name'] },
        { method: 'byPlaceholder', args: ['full name'] },
      ],
      [b.email]: [
        { method: 'byName', args: ['email'] },
        { method: 'bySelector', args: ['input[type="email"]'] },
        { method: 'byLabelText', args: ['email'] },
      ],
      [b.phone]: [
        { method: 'byName', args: ['phone'] },
        { method: 'bySelector', args: ['input[type="tel"]'] },
        { method: 'byLabelText', args: ['phone'] },
      ],
      [b.linkedin]: [
        { method: 'bySelector', args: ['input[name*="urls[LinkedIn]"]'] },
        { method: 'bySelector', args: ['input[name*="linkedin"]'] },
        { method: 'byLabelText', args: ['linkedin'] },
      ],
      [b.github]: [
        { method: 'bySelector', args: ['input[name*="urls[GitHub]"]'] },
        { method: 'bySelector', args: ['input[name*="github"]'] },
        { method: 'byLabelText', args: ['github'] },
      ],
      [b.website]: [
        { method: 'bySelector', args: ['input[name*="urls[Portfolio]"]'] },
        { method: 'bySelector', args: ['input[name*="website"]'] },
        { method: 'byLabelText', args: ['website'] },
        { method: 'byLabelText', args: ['portfolio'] },
      ],
      [loc.city]: [
        { method: 'byLabelText', args: ['location'] },
        { method: 'byLabelText', args: ['city'] },
        { method: 'byPlaceholder', args: ['location'] },
        { method: 'byPlaceholder', args: ['city'] },
      ],
    };

    // ── Current work ─────────────────────────────────────────────
    if (latestWork.company) {
      map[latestWork.company] = [
        { method: 'byLabelText', args: ['current company'] },
        { method: 'byLabelText', args: ['company name'] },
        { method: 'byLabelText', args: ['current employer'] },
      ];
    }
    if (latestWork.position || b.title) {
      map[latestWork.position || b.title] = [
        { method: 'byLabelText', args: ['current title'] },
        { method: 'byLabelText', args: ['job title'] },
        { method: 'byLabelText', args: ['current role'] },
      ];
    }

    // ── Education ────────────────────────────────────────────────
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
        { method: 'byLabelText', args: ['education level'] },
      ];
    }
    if (latestEdu.area) {
      map[latestEdu.area] = [
        { method: 'byLabelText', args: ['major'] },
        { method: 'byLabelText', args: ['field of study'] },
      ];
    }

    return map;
  },

  resumeInputSelectors: [
    'input[type="file"][name*="resume"]',
    'input[type="file"][name*="cv"]',
    '.application-form input[type="file"]',
    'input[type="file"]',
  ],
});
