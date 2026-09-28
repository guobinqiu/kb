# WebUI Shared Components Implementation Plan

**Goal:** Share repeated headers, dialog actions and organization helpers without changing permissions or API behavior.

**Architecture:** Presentation components accept slots and emit user actions. Organization helpers operate on the arrays supplied by each page; each page retains its own visibility filtering and data loading.

**Tech Stack:** Vue 3, Element Plus, Vue I18n, Vite.

## Global Constraints

- No frontend test files or Git commits.
- Preserve permission checks, requests, selection behavior and dialog content.
- Leave tables and full business dialogs in their existing pages.

## Steps

1. Add `SectionHeader.vue`: optional title/description, default content slot, actions slot; shared spacing and responsive layout.
2. Add `DialogActions.vue`: cancel/confirm events, loading/disabled props, custom confirm label, slot for extra actions. Retain existing cancel behavior.
3. Replace repeated section headers and dialog footers in Files, Chunks, Workspaces, Users, Organizations and Members.
4. Add `buildOrgTree(orgs)` and `isOrgInactive(orgs, orgId)` to `utils/organization.js`. Call them from existing pages after their existing filtering/decorating steps.
5. Run `npm --prefix webui run build`, `git diff --check`, and one-off organization-helper behavior checks. Verify served assets at `http://localhost:5175/`; inspect the browser if available.
