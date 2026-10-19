# Frontend workspace refactor design

## Scope
Issue #56 changes only the EVIA React workspace. It removes the unused quiet-mode control, makes “Новый анализ” return to the source-upload start screen, and makes desktop workspace panels independently scrollable below a persistent header.

## Navigation
`newAnalysis()` clears the selected source and transient upload/request state. It must not delete the source list, imported files, chat history, or persisted chat-to-source mapping. With no selected source, the existing upload card is rendered in the central area.

## Layout
At desktop widths (1001px and wider), `.app` fills the viewport and prevents document-level workspace overflow. The top bar is fixed in the layout at 72px. `.workspace` fills the remaining viewport height; sidebar, analysis, and chat are independent vertical scroll regions with `min-height: 0`.

At tablet and mobile widths, the existing two-column and stacked layouts retain document scrolling. This avoids trapping content in narrow viewports and preserves the existing responsive information hierarchy.

## Quiet mode
The workspace toggle, localStorage preference, `.quiet` app class, and styles used only by that control are removed. Mascot Gallery keeps its own standalone animation preview control because it is a development gallery and outside the workspace UI.

## Verification
Unit tests cover return-to-upload behavior without source deletion and the absence of the quiet-mode control. Existing CSV upload, source selection, chat-history, frontend test suite, TypeScript check, and production build remain verification gates. Visual smoke checks cover desktop, tablet, and mobile dimensions.
