# Frontend Workspace Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore predictable workspace navigation and make desktop panels stay available without visual overlap.

**Architecture:** Keep the existing component tree and API contract. `App.tsx` owns the selected-source state, so the navigation fix remains a local state transition. CSS creates a bounded desktop workspace with three independently scrollable columns; responsive breakpoints retain the established document-flow layouts.

**Tech Stack:** React 18, TypeScript, Vitest, Testing Library, CSS Grid/Flexbox, Vite.

---

### Task 1: Specify reset-to-upload navigation

**Files:**
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/App.tsx:303-325`

- [ ] **Step 1: Write the failing test**

```tsx
it("returns to the CSV start screen without removing the selected source", async () => {
  setup();
  render(<App />);
  await select("A");

  fireEvent.click(screen.getByRole("button", { name: "Новый анализ" }));

  expect(screen.getByRole("heading", { name: "Добавьте CSV" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "A" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- --run src/App.test.tsx -t "returns to the CSV start screen"`

Expected: FAIL because `newAnalysis()` preserves `selectedId` and the source inspector remains rendered.

- [ ] **Step 3: Implement the local state transition**

In `newAnalysis()`, replace the selected-source dependent branch with a reset that calls `setSelectedId(null)`, clears active request state and upload error state, resets the view to `overview`, and moves focus to the upload card’s file-picker button on the next animation frame.

- [ ] **Step 4: Run the focused test**

Run: `npm test -- --run src/App.test.tsx -t "returns to the CSV start screen"`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "fix(frontend): return new analysis to upload screen"
```

### Task 2: Remove quiet mode from the workspace

**Files:**
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/App.tsx:100-106,317-325,460,637-649,797,830`
- Modify: `frontend/src/styles.css:329-369,1252-1257,1486-1499`
- Modify: `frontend/src/components/Icon.tsx:9,30-35`

- [ ] **Step 1: Write the failing test**

```tsx
it("does not render the obsolete quiet-mode workspace control", async () => {
  setup();
  render(<App />);
  await screen.findByText(/Тестовая модель/);

  expect(screen.queryByRole("button", { name: "Тихий режим" })).not.toBeInTheDocument();
  expect(localStorage.getItem("linza.quiet")).toBeNull();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- --run src/App.test.tsx -t "obsolete quiet-mode"`

Expected: FAIL because the control exists and the old test persists its preference.

- [ ] **Step 3: Remove only workspace-specific quiet mode**

Remove `quiet` state and `toggleQuiet()` from `App.tsx`, the sidebar control, `quiet` props passed by the workspace to `Evia`, the `quiet` icon definition, and the associated workspace CSS. Keep `EviaMascot` and Mascot Gallery’s own animation-preview API intact.

- [ ] **Step 4: Run focused tests**

Run: `npm test -- --run src/App.test.tsx src/features/mascot/mascot.test.tsx`

Expected: PASS; mascot gallery still verifies its isolated `quiet` prop.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/styles.css frontend/src/components/Icon.tsx
git commit -m "refactor(frontend): remove quiet mode control"
```

### Task 3: Bound desktop workspace panels and retain responsive flow

**Files:**
- Modify: `frontend/src/styles.css:154-179,897-970,1362-1565`
- Modify: `frontend/src/features/sources/analytics.css:8-25`

- [ ] **Step 1: Add a regression assertion for the layout contract**

Create `frontend/src/workspace-layout.test.ts` that reads `styles.css` and asserts the desktop media rule contains a bounded `.workspace` height, `overflow: hidden`, and independent vertical scrolling for `.sidebar`, `.analysis`, and `.chat-panel`; assert the narrow breakpoint restores visible overflow. This guards the CSS contract that jsdom cannot lay out.

- [ ] **Step 2: Run the new test to verify it fails**

Run: `npm test -- --run src/workspace-layout.test.ts`

Expected: FAIL because the desktop workspace only has `min-height` and the sidebar/analysis are not bounded scroll regions.

- [ ] **Step 3: Implement the desktop layout contract**

Add a desktop media block for `min-width: 1001px` that gives `.app` a viewport-bounded height, `.workspace` the remaining `calc(100dvh - 72px)` height and hidden overflow, and all three columns `min-height: 0; overflow-y: auto`. Make `.chat-content` flex and scroll within the chat panel. Remove the analytics-only `:has()` sticky chat rule because fixed behavior now applies consistently to every source view. Restore normal workspace/document overflow below 1001px.

- [ ] **Step 4: Run focused layout test**

Run: `npm test -- --run src/workspace-layout.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles.css frontend/src/features/sources/analytics.css frontend/src/workspace-layout.test.ts
git commit -m "fix(frontend): stabilize workspace panel scrolling"
```

### Task 4: Verify the full frontend contract

**Files:**
- No production changes expected.

- [ ] **Step 1: Run frontend tests**

Run: `npm test -- --run`

Expected: all test files pass.

- [ ] **Step 2: Run type-check and production build**

Run: `npm run build`

Expected: TypeScript exits 0 and Vite emits `dist/`.

- [ ] **Step 3: Run visual smoke checks**

Start the app with the existing local launcher. Check 1440px desktop: persistent sidebar/chat and scrollable analysis; 900px tablet: accessible two-column layout; 390px mobile: no horizontal page overflow, visible CSV action, source list and chat composer.

- [ ] **Step 4: Commit any verification-only adjustment**

```bash
git status --short
git add <changed-files>
git commit -m "test(frontend): cover workspace navigation"
```
