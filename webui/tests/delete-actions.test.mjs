import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const view = async name => readFile(new URL(`../src/views/${name}`, import.meta.url), 'utf8')

test('organization action deletes both active and legacy inactive rows without restoring', async () => {
  const source = await view('OrganizationsView.vue')
  assert.match(source, /@click="deleteOrg\(selectedOrg\)"/)
  assert.match(source, /t\('common\.delete'\)/)
  assert.match(source, /t\('organizations\.deleteBlocked'\)/)
  assert.doesNotMatch(source, /restoreOrg\(|t\('common\.disable'\)/)
})

test('user action deletes both active and legacy inactive rows without restoring', async () => {
  const source = await view('UsersView.vue')
  assert.match(source, /@click="deleteUser\(row\)"/)
  assert.match(source, /t\('common\.delete'\)/)
  assert.match(source, /t\('users\.deleteBlocked'\)/)
  assert.doesNotMatch(source, /restoreUser\(|t\('common\.disable'\)/)
})
