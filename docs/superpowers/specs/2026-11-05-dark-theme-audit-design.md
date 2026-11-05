# EVIA Dark Theme Audit Design

## Goal

Make EVIA's dark theme coherent, readable, and visually complete across desktop and mobile without changing light-theme behavior or application functionality.

## Scope

Audit the home/source-import screen, source overview, columns, quality, data, schema, analysis results, chat, reports, settings, account menu, and authentication views. Review empty, loading, error, selected, hover, focus, and disabled states as well as charts, tables, dialogs, forms, and navigation.

## Design

Use the existing `data-theme="dark"` preference and CSS variables as the source of truth. Consolidate repeated dark surfaces, text, muted text, borders, and control colors into theme tokens where practical. Fix remaining component-specific light-only colors in focused component styles; preserve chart-series colors while ensuring gridlines, legends, labels, tooltips, and selected states remain legible. Keep the light theme unchanged.

## Validation

Use representative desktop and mobile viewports for each route and state. Add focused regression tests for theme selection/persistence and component behavior where possible. Run the frontend test suite, TypeScript checks, and production build. Check the final diff for accidental light-theme changes.

## Boundaries

This phase changes only visual presentation. It does not add languages, alter analytics behavior, or change backend contracts.
