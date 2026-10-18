# EVIA design polish — issue #1

User-directed design: one EVIA wordmark; remove slogans, duplicate instructions and large mock banner. Keep a compact explicit test-model label, errors, CSV requirements, sample limitations and optional chat help. Retain functional controls and accessibility. Use raised rounded buttons with a lower lip, press feedback and visible keyboard focus, inspired by the supplied CSS. No new dependencies, fonts or remote assets.

- Update existing rendering assertions to the new concise labels; no new tests for cosmetic-only styling.
- Edit source React/HTML (not generated dist), remove unused CSS for deleted blocks, unify EVIA labels.
- Refine surface/color/spacing/button styles while preserving responsive breakpoints, disabled states and reduced-motion.
- Run frontend tests/build and local HTTP smoke tests. Attempt visual QA with available computer-use tools; report any limitation accurately.
- Update existing PR #2, do not merge.

## Result and verification

Implemented in the existing issue branch. Removed old wordmark, hero slogan, onboarding strip, footer, large mock banner and redundant labels; retained source/profile facts and actionable errors. The same EVIA spelling is used in visible frontend text, accessible labels, browser title and launcher.

23 frontend tests passed; TypeScript/Vite build passed; 13 backend tests passed. `git diff --check` passed. Source code reviewed independently; minor pagination border/radius inconsistency corrected.

Browser QA succeeded in Chrome on macOS: desktop empty workspace and responsive 400×673 viewport (top and chat below fold) visually inspected. Confirmed EVIA heading, compact test-model badge, green raised primary buttons, disabled send control and absence of removed slogans. Console showed 0 messages. Mobile emulation and DevTools were switched off afterwards. This was visual smoke QA, not a full cross-browser/keyboard/loaded-dataset accessibility audit.

Existing PR #2 is updated; no merge performed. Generated dist rebuilt locally, not committed.
