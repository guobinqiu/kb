import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = async path => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('failed files expose the KB3-style retry action', async () => {
  const view = await source('views/FilesView.vue')
  assert.match(view, /:icon="RefreshRight" circle size="small"/)
  assert.match(view, /:disabled="row\.status !== 'failed' \|\| !row\.s3_url \|\| !canManageFile\(row, 'upload'\)"/)
  assert.match(view, /@click="retryIndex\(row\)"/)
  assert.match(view, /await retryFile\(selectedWorkspaceId, file\)/)
  assert.match(view, /t\('files\.retrySubmitted', \{ name: file\.filename \}\)/)
})

test('retry reuses the existing object and filename', async () => {
  const api = await source('utils/kbApi.js')
  assert.match(api, /export async function retryFile\(workspaceId, file\)/)
  assert.match(api, /s3_url: file\.s3_url/)
  assert.match(api, /filename: file\.filename/)
  assert.match(api, /content_type: file\.mime_type/)
})

test('retry labels match KB3 copy', async () => {
  const zh = JSON.parse(await source('i18n/locales/zh.json'))
  const en = JSON.parse(await source('i18n/locales/en.json'))
  assert.equal(zh.files.retry, '重新索引')
  assert.equal(zh.files.retrySubmitted, '{name} 已提交重新索引')
  assert.equal(en.files.retry, 'Retry indexing')
  assert.equal(en.files.retrySubmitted, '{name} submitted for reindexing')
})
