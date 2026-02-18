/**
 * LevelUpX AutoFill — Greenhouse Adapter
 *
 * Greenhouse uses standard HTML forms with name attributes like:
 * job_application[first_name], job_application[last_name], etc.
 */

window.LevelUpXGreenhouse = window.LevelUpXBaseAdapter.create({
  name: 'Greenhouse',
  hostPatterns: ['greenhouse.io'],

  formDetector() {
    return !!(
      document.querySelector('#application_form, form#job_application, [id*="application"]') ||
      document.querySelector('form[action*="application"], form[action*="apply"]') ||
      document.querySelector('input[name*="first_name"], input[name*="job_application"]') ||
      document.querySelector('[class*="application"], [data-controller*="application"]')
    );
  },

  fieldMap(profile) {
    const b = profile.basics || {};
    const loc = b.location || {};
    const latestWork = (profile.work && profile.work[0]) || {};
    const latestEdu = (profile.education && profile.education[0]) || {};

    const map = {
      // ── Standard contact fields ────────────────────────────────
      [b.firstName]: [
        { method: 'byName', args: ['first_name'] },
        { method: 'bySelector', args: ['input[name="job_application[first_name]"]'] },
        { method: 'byLabelText', args: ['first name'] },
        { method: 'byPlaceholder', args: ['first name'] },
      ],
      [b.lastName]: [
        { method: 'byName', args: ['last_name'] },
        { method: 'bySelector', args: ['input[name="job_application[last_name]"]'] },
        { method: 'byLabelText', args: ['last name'] },
        { method: 'byPlaceholder', args: ['last name'] },
      ],
      [b.email]: [
        { method: 'byName', args: ['email'] },
        { method: 'bySelector', args: ['input[name="job_application[email]"]'] },
        { method: 'bySelector', args: ['input[type="email"]'] },
        { method: 'byLabelText', args: ['email'] },
      ],
      [b.phone]: [
        { method: 'byName', args: ['phone'] },
        { method: 'bySelector', args: ['input[name="job_application[phone]"]'] },
        { method: 'bySelector', args: ['input[type="tel"]'] },
        { method: 'byLabelText', args: ['phone'] },
      ],
      [b.linkedin]: [
        { method: 'bySelector', args: ['input[name*="linkedin"]'] },
        { method: 'byLabelText', args: ['linkedin'] },
        { method: 'byLabelText', args: ['linkedin profile'] },
        { method: 'byPlaceholder', args: ['linkedin'] },
      ],
      [b.website || b.github]: [
        { method: 'bySelector', args: ['input[name*="website"]'] },
        { method: 'byLabelText', args: ['website'] },
        { method: 'byLabelText', args: ['portfolio'] },
        { method: 'byPlaceholder', args: ['website'] },
      ],
      [loc.city]: [
        { method: 'bySelector', args: ['input[name*="location"]'] },
        { method: 'byLabelText', args: ['location'] },
        { method: 'byLabelText', args: ['city'] },
        { method: 'byPlaceholder', args: ['location'] },
        { method: 'byPlaceholder', args: ['city'] },
      ],
    };

    // ── Current work fields ──────────────────────────────────────
    if (latestWork.company) {
      map[latestWork.company] = [
        { method: 'byName', args: ['current_company'] },
        { method: 'byLabelText', args: ['current company'] },
        { method: 'byLabelText', args: ['company name'] },
        { method: 'byLabelText', args: ['current employer'] },
        { method: 'byPlaceholder', args: ['company'] },
      ];
    }
    if (latestWork.position || b.title) {
      map[latestWork.position || b.title] = [
        { method: 'byName', args: ['current_title'] },
        { method: 'byLabelText', args: ['current title'] },
        { method: 'byLabelText', args: ['job title'] },
        { method: 'byLabelText', args: ['current role'] },
        { method: 'byLabelText', args: ['current position'] },
        { method: 'byPlaceholder', args: ['title'] },
      ];
    }

    // ── Education fields ─────────────────────────────────────────
    if (latestEdu.institution) {
      map[latestEdu.institution] = [
        { method: 'byLabelText', args: ['school'] },
        { method: 'byLabelText', args: ['university'] },
        { method: 'byLabelText', args: ['college'] },
        { method: 'byLabelText', args: ['institution'] },
        { method: 'byPlaceholder', args: ['school'] },
        { method: 'byPlaceholder', args: ['university'] },
      ];
    }
    if (latestEdu.studyType) {
      map[latestEdu.studyType] = [
        { method: 'byLabelText', args: ['degree'] },
        { method: 'byLabelText', args: ['highest degree'] },
        { method: 'byLabelText', args: ['education level'] },
      ];
    }
    if (latestEdu.area) {
      map[latestEdu.area] = [
        { method: 'byLabelText', args: ['major'] },
        { method: 'byLabelText', args: ['field of study'] },
        { method: 'byLabelText', args: ['area of study'] },
        { method: 'byLabelText', args: ['specialization'] },
      ];
    }

    // ── Address fields ───────────────────────────────────────────
    if (loc.region) {
      map[loc.region] = [
        { method: 'byLabelText', args: ['state'] },
        { method: 'byLabelText', args: ['province'] },
        { method: 'byLabelText', args: ['region'] },
      ];
    }
    if (loc.country) {
      map[loc.country] = [
        { method: 'byLabelText', args: ['country'] },
      ];
    }

    // ── GitHub (separate from website) ───────────────────────────
    if (b.github) {
      map[b.github] = [
        { method: 'bySelector', args: ['input[name*="github"]'] },
        { method: 'byLabelText', args: ['github'] },
        { method: 'byPlaceholder', args: ['github'] },
      ];
    }

    return map;
  },

  resumeInputSelectors: [
    'input[type="file"][name*="resume"]',
    'input[type="file"][name*="cv"]',
    'input[type="file"][id*="resume"]',
    'input[type="file"]',
  ],
});
