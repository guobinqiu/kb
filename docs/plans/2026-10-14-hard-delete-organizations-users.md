# Organization and User Hard Delete Implementation Plan

**Goal:** Replace organization and user deactivation with permanent, guarded deletion so an empty enterprise can be deleted.

**Architecture:** Keep the existing `DELETE` API paths, but make their DAO operations delete rows inside a transaction after checking references. An owner may delete an empty root organization; a non-owner may not delete their own organization. Retain `deleted_at` reads only to display and clean up legacy inactive records; remove restore controls and PATCH-based restoration.

**Tech Stack:** FastAPI, psycopg/PostgreSQL, pytest, Vue 3, Element Plus, vue-i18n.

## Global Constraints

- Deletion never cascades through child organizations, users, workspaces, files, or index data.
- A blocked delete returns HTTP 409 and leaves all rows unchanged.
- Do not delete any production data or deploy this change as part of implementation.
- Preserve unrelated code formatting and behavior.

---

### Task 1: Guarded user deletion

**Files:** `kb_api/tests/test_delete_cleanup.py`, `kb_api/api/dao/users.py`, `kb_api/api/routes/users.py`, `kb_api/api/schemas.py`.

**Interfaces:** `UsersDAO.delete_user(user_id: str) -> bool` removes one unreferenced row; raises `ValueError("User has related data")` for any `workspace_user`, `workspaces.created_by`, or `files.created_by` reference. The route maps that error to 409. `UserUpdate` no longer accepts `deleted_at`.

- [ ] Write tests proving unreferenced user deletion removes the row and releases the unique name, while references block deletion without changing membership or attribution.
- [ ] Run `kb_api/.venv/bin/pytest -q kb_api/tests/test_delete_cleanup.py -k user` and confirm the new tests fail because the row remains.
- [ ] In one transaction, check references and execute `DELETE FROM users WHERE id = %s`; map `ValueError` to 409 at the route and remove PATCH restoration.
- [ ] Run the same test command and confirm all user-delete tests pass.

### Task 2: Guarded organization deletion, including root

**Files:** `kb_api/tests/test_delete_cleanup.py`, `kb_api/tests/test_nodes_softdelete.py`, `kb_api/api/dao/orgs.py`, `kb_api/api/routes/orgs.py`, `kb_api/api/schemas.py`.

**Interfaces:** `OrgsDAO.delete_org(org_id: str) -> bool` removes one organization only if it has no child organization, user, or `workspace_org` reference; raises `ValueError("Org has related data")` otherwise. `OrgUpdate` no longer accepts `deleted_at`. Owner can remove an empty root; current user's own organization remains protected.

- [ ] Write tests proving an empty root can be removed followed by its App, and proving each reference type blocks deletion with 409.
- [ ] Run `kb_api/.venv/bin/pytest -q kb_api/tests/test_delete_cleanup.py -k org` and confirm the new tests fail on the old root/soft-delete behavior.
- [ ] Implement guarded SQL deletion and 409 mapping; remove root prohibition for owner and PATCH restoration.
- [ ] Replace tests that require soft-delete/restore with tests for permanent removal and run the organization-focused tests again.

### Task 3: UI wording and legacy inactive-row cleanup

**Files:** `webui/src/views/OrganizationsView.vue`, `webui/src/views/UsersView.vue`, `webui/src/i18n/locales/zh.json`, `webui/src/i18n/locales/en.json`, `docs/api.md`, `README.md`.

**Interfaces:** Existing `removeOrg` and `removeUser` API helpers remain unchanged. Both views offer `Delete` for active and legacy-inactive rows; neither offers `Restore`.

- [ ] Update buttons, confirmation text, success text, and documentation to say permanent deletion and explain 409 prerequisites.
- [ ] Run `npm run build` in `webui` and correct any template/import errors.
- [ ] Run the complete backend test suite and update existing soft-delete expectations to the approved guarded-delete behavior.

## Self-review

- The plan covers user, organization, root, enterprise, legacy inactive rows, UI, API, and tests.
- Cross-app workspace/file references remain intact until explicitly removed.
- No production data operation is included.
