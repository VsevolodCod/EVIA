# EVIA Workspace Redesign

## Goal

Make EVIA feel calm, polished, and easy to present by separating the crowded three-column workspace into focused pages while preserving every existing feature and data workflow.

## Audience and demo entry

The primary audience is a first-time evaluator seeing the product during a live demo. After sign-in, they should immediately understand where data comes from and how to begin an analysis. The default page is therefore the source home, with a prominent new-analysis action.

## Page structure

### Home

- Shows available data sources as compact, scannable cards.
- Keeps the primary “Новый анализ” action prominent.
- Provides CSV upload and PostgreSQL connection entry points.
- Shows recent activity and recent conversations without exposing the full history list at all times.
- Selecting a source opens its analysis workspace.

### Source analysis

- Focuses the full content area on one selected source.
- Shows the source name, type, availability, and a concise dataset summary.
- Retains the existing source sections: Overview, Columns, Quality, Data, Schema, and Result.
- Keeps chart palette controls and PDF export available when a report or dashboard supports them.
- Offers an explicit action to open EVIA chat with the current source attached.

### Chat

- Uses the full workspace for the conversation and composer.
- Keeps the current source visible and switchable from the chat context control.
- Preserves saved conversations, archived conversations, retry behavior, pending state, tool results, and report attachment.
- Provides a clear path back to the source and to an analysis result.

### Reports

- Presents saved dashboards as a searchable/scannable gallery.
- Opening a report focuses the page on that dashboard.
- Preserves report editing, chart color palettes, source context, PDF export, and opening the originating chat where available.

### Import and connection flows

- CSV upload and PostgreSQL setup remain complete workflows, presented in focused pages or overlays with a clear close/back action.
- On successful completion, EVIA opens the new or selected source in its analysis workspace.
- Existing progress, encoding/separator support, reimport, failure reporting, retry, and source selection remain intact.

## Navigation and state

- Desktop uses a compact persistent left navigation; mobile uses the existing bottom navigation pattern.
- The top-level navigation contains Home, the current source analysis entry when a source is selected, Chat, and Reports. Account and settings remain in the global shell.
- The current page, source ID, and source subsection are represented in the URL so refresh and browser back/forward restore context.
- Chat links retain the selected source and conversation ID. Report links retain the report ID and originating context when available.
- Page changes do not clear in-progress drafts, loaded history, or the current source selection.
- The existing API contracts and backend behavior are unchanged.

## Visual direction

- Use a neutral, light canvas with EVIA green reserved for primary actions, active navigation, and meaningful status.
- Keep charts on a distinct, color-accessible palette rather than using green as the default for every series.
- Establish consistent page widths, heading hierarchy, spacing, card borders, and control styles.
- Show one primary task per screen. Supporting information is revealed when relevant rather than persistently occupying side columns.
- Preserve the current light, dark, and system theme choices.
- Maintain responsive layouts, readable chart/table overflow, visible keyboard focus, and reduced-motion preferences.

## Feature preservation

The redesign must keep all current product capabilities available: authentication and account settings; source list and refresh; CSV upload, reimport, original downloads, and deletion; PostgreSQL setup and status; source overview, columns, quality, preview, schema, and analysis results; chat history, archive, retry, attachments, and tool results; saved dashboards, palette editing, and PDF export; theme selection; mobile navigation.

No backend, database schema, API contract, or model-provider behavior changes are included.

## Error and loading behavior

- Loading and failure states appear inside the page or flow they belong to.
- Existing retry actions remain adjacent to the failure message.
- A failed upload or chat request must not navigate away or discard the user’s source/context.
- Empty states explain the next useful action, especially on Home, Reports, and Chat.
- A missing or deleted source encountered through a deep link returns the user to Home with a clear message.

## Acceptance criteria

1. Sign-in opens Home with sources and a clear new-analysis action.
2. Opening a source shows its focused analysis workspace without the persistent chat and source-history columns.
3. All six analysis sections remain reachable and preserve their current behaviors.
4. Opening chat from a source retains that source; returning restores the prior analysis subsection.
5. Reports can be browsed and opened independently, and palette editing/PDF export still work.
6. CSV upload and PostgreSQL connection still lead to the resulting source workspace.
7. Direct refresh and browser back/forward preserve the selected page and relevant source/report context.
8. Desktop and mobile screens remain usable, with the mobile bottom navigation retained.
9. No feature listed in Feature preservation is removed or made unreachable.

## Verification scenarios

- Sign in, inspect Home, and open an existing source.
- Visit each analysis subsection and return to the prior subsection using browser navigation.
- Open chat from the source, send a question, open its tool result, and return to the chat.
- Open a saved report, change its palette, export PDF, then return to Reports.
- Upload a CSV and confirm the imported source opens; separately open PostgreSQL setup and select a connected source.
- Refresh deep links for Home, source analysis, Chat, and a saved report.
- Repeat the core journey at desktop and mobile viewport widths and with light/dark/system themes.
