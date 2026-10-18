# EVIA integration implementation plan

**Goal:** Integrate the user's 40-state vector pack into issue #1 / PR #2, preserving identifiers and artwork.
**Architecture:** A typed local catalog, reusable accessible image component, pure event-to-state resolver, and an explicit gallery at `?mascot=1`. No timer-based fake analysis stages; unsupported backend stages remain gallery-only. Existing isolated issue worktree is reused.
**Tech stack:** React, TypeScript, local SVG, CSS, Vitest/Testing Library.

User supplied the integration pack and instructed implementation after the proposed mascot/gallery design. This is refinement of the mascot in the existing open issue, not a new backend task.

- [x] Write failing tests for catalog assets, accessible labels, event precedence, upload, retry, cancellation and partial tool errors.
- [x] Copy all 40 SVG unchanged into frontend/public/mascot; generate a typed catalog from supplied states.json. Add EviaMascot and compatibility wrapper.
- [x] Add typed transport errors and map known error statuses; persist request-specific mascot state in Entry. Prioritize uploading, active source request, upload failure, connection failure, draft, response, uploaded source, welcome/waiting.
- [x] Add decorative mascot to metadata loading and empty table, with existing text preserved. Add local gallery with all states, selectable preview, size and quiet controls.
- [x] Replace old mascot CSS with gentle floating/entrance styles, disabled by quiet and reduced-motion; no animation-driven status transitions.
- [x] Run frontend tests/build, backend smoke tests, inspect SVG safety and production asset delivery. Document results, limitations and gallery URL in README.
- [x] Commit and push to existing PR #2; do not merge.

## Verification

- 23 frontend tests passed; TypeScript and Vite build passed without chunk warnings after separating app/gallery entry chunks.
- 13 backend tests passed, including dev and production HTTP integration.
- Live production HTTP: gallery HTML and all 40 SVG served successfully with correct content type and byte-for-byte match to the supplied originals.
- Independent code review found a reduced-motion CSS specificity issue; fixed and re-reviewed successfully by inspection.
- `git diff --check` passed. No changes to original integration pack; no runtime data or secrets staged.
- Browser visual QA was attempted but macOS ScreenCaptureKit failed with error -3811. No visual or computed-style browser pass is claimed.
- Assets are simplified vector artwork. Animation is whole-image entrance/float, not eye/limb rigging. Future backend stages remain catalog/gallery-only.
- Delivery continues in existing issue #1 / PR #2; no merge.
