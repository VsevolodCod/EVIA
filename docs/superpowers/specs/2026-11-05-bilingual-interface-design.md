# EVIA Bilingual Interface Design

## Goal

Provide complete Russian and English interfaces and make new EVIA answers use the selected interface language.

## Scope

Translate visible interface text across authentication, home and import, source analysis tabs, charts and dashboards, chat, reports, settings, account controls, loading and error states, and accessible labels. Preserve user data such as filenames, column names, dataset values, questions already sent, and saved assistant responses as stored.

## Design

Use a small typed RU/EN message catalog with a shared translation helper; no localization dependency is needed for the two supported languages. Add a language choice to settings, persist it in `localStorage` under `evia.language`, and default existing users to Russian. Send a validated `response_language` (`ru` or `en`) with each chat request. Keep the API backward compatible by defaulting missing language to Russian, and add a request-scoped instruction to the agent so each new response follows the selected language. Do not translate model-generated content or dataset content in the frontend.

## Validation

Test initial/default and persisted language selection, representative UI strings and accessible labels in both languages, request payload propagation, API validation/backward compatibility, and agent language instruction. Run the full frontend and backend suites, TypeScript checks, and production build.

## Boundaries

This phase adds only Russian and English. It does not translate existing history or source data, and it does not change analytical calculations or data contracts beyond the optional response-language field.
