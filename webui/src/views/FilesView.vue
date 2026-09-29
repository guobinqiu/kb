<template>
  <section class="workspace-panel files-view">
    <input ref="uploadInput" type="file" :accept="supportedFileTypes" multiple hidden @change="uploadSelectedFiles" />
    <input ref="replaceInput" type="file" :accept="supportedFileTypes" hidden @change="replaceSelectedFile" />
    <SectionHeader :title="t('files.title')" :description="t('files.desc')" />
    <button
      type="button"
      class="upload-zone"
      :class="{ dragging }"
      :disabled="!canUploadFiles || uploading"
      :aria-busy="uploading"
      @click="uploadInput?.click()"
      @dragover.prevent="dragging = canUploadFiles && !uploading"
      @dragleave.prevent="dragging = false"
      @drop.prevent="dropFiles"
    >
      <el-icon :class="{ 'is-loading': uploading }"><Loading v-if="uploading" /><UploadFilled v-else /></el-icon>
      <span class="upload-title">{{ uploading ? t('files.uploading') : t('files.choose') }}</span>
      <span class="upload-types">{{ t('files.supportedTypes', { types: supportedFileTypes.split(',').join(', ') }) }}</span>
    </button>

    <div class="file-toolbar">
      <span v-if="polling" class="polling-label">{{ t('files.processing') }}</span>
      <RefreshButton :loading="loading" @click="fetchFiles()" />
    </div>
    <div class="file-list">
      <div class="docs-head">
        <div class="docs-title">
          <h3>{{ t('files.list') }}</h3>
          <span class="docs-count">{{ files.length }}</span>
        </div>
      </div>
      <el-table v-if="files.length || loading" :data="files" v-loading="loading" style="width: 100%">
        <el-table-column prop="id" :label="t('files.fileId')" min-width="300" show-overflow-tooltip>
          <template #default="{ row }"><span class="file-id">{{ row.id }}</span></template>
        </el-table-column>
        <el-table-column prop="filename" :label="t('files.filename')" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.filename || row.name }}</template>
        </el-table-column>
        <el-table-column :label="t('files.status')" min-width="130">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('files.updatedAt')" min-width="170">
          <template #default="{ row }">{{ shortTime(row.updated_at || row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('files.error')" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ indexErrorMessage(row.error) }}</template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="156" align="right">
          <template #default="{ row }">
            <el-tooltip :content="t('workspace.viewChunks')">
              <el-button :icon="View" circle size="small" :disabled="!canReadFiles" :aria-label="t('workspace.viewChunks')" @click="viewChunks(row)" />
            </el-tooltip>
            <el-tooltip :content="t('files.replace')">
              <el-button :icon="Upload" circle size="small" :aria-label="t('files.replace')" :loading="replacingId === row.id" :disabled="!canManageFile(row, 'upload') || isProcessing(row.status)" @click="chooseReplacement(row)" />
            </el-tooltip>
            <el-tooltip :content="t('common.delete')">
              <el-button :icon="Delete" circle size="small" type="danger" plain :aria-label="t('common.delete')" :loading="deletingId === row.id" :disabled="!canManageFile(row, 'delete') || isProcessing(row.status)" @click="deleteFile(row)" />
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else :description="t('files.empty')" />
    </div>
  </section>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Delete, Loading, Upload, UploadFilled, View } from '@element-plus/icons-vue'
import RefreshButton from '../components/RefreshButton.vue'
import SectionHeader from '../components/SectionHeader.vue'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '../stores/auth'
import { getFiles, removeFile, replaceFile, uploadFile } from '../utils/kbApi'
import { confirmBox } from '../utils/messageBox'
import { shortTime } from '../utils/format'
import { errorMessage, indexErrorMessage, showToast } from '../utils/toast'

const PROCESSING_STATUSES = new Set(['uploaded', 'indexing', 'deleting'])
const supportedFileTypes = '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md'
const route = useRoute()
const router = useRouter()
const { t, te } = useI18n()
const workspacePermissions = inject('workspacePermissions', computed(() => ({})))
const { currentUser } = storeToRefs(useAuthStore())
const appId = computed(() => route.params.app_id)
const files = ref([])
const workspaceId = computed(() => route.params.workspace_id)
const loading = ref(false)
const uploading = ref(false)
const dragging = ref(false)
const deletingId = ref(null)
const replacingId = ref(null)
const replaceTarget = ref(null)
const replaceInput = ref(null)
const uploadInput = ref(null)
let pollTimer = null
let fetchRequestId = 0

const polling = computed(() => files.value.some(file => isProcessing(file.status)))
const canReadFiles = computed(() => workspacePermissions.value?.['workspace.files.read'] === true)
const canUploadFiles = computed(() => workspacePermissions.value?.['workspace.files.upload'] === true)

function canManageFile(file, action) {
  return workspacePermissions.value?.[`workspace.files.${action}`] === true && (
    workspacePermissions.value?.['workspace.members.manage'] === true ||
    (file.created_by != null && file.created_by === currentUser.value?.id)
  )
}

function viewChunks(file) {
  if (!canReadFiles.value) return
  router.push({ path: `/apps/${appId.value}/workspaces/${workspaceId.value}/chunks`, query: { file_ids: file.id, filename: file.filename || file.name } })
}

function isProcessing(status) {
  return PROCESSING_STATUSES.has(status)
}

function statusType(status) {
  if (status === 'indexed') return 'success'
  if (status === 'failed' || status === 'delete_failed') return 'danger'
  if (status === 'indexing' || status === 'deleting') return 'warning'
  return 'info'
}

function statusLabel(status) {
  const key = `files.statuses.${status}`
  return te(key) ? t(key) : status
}

async function fetchFiles({ quiet = false } = {}) {
  if (!workspaceId.value || !canReadFiles.value) return
  const requestId = ++fetchRequestId
  const selectedWorkspaceId = workspaceId.value
  if (!quiet) loading.value = true
  try {
    const result = await getFiles(selectedWorkspaceId)
    if (requestId !== fetchRequestId || selectedWorkspaceId !== workspaceId.value) return
    files.value = result.files
    syncPolling()
  } catch (err) {
    if (!quiet && requestId === fetchRequestId) showToast('error', errorMessage(err))
  } finally {
    if (!quiet && requestId === fetchRequestId) loading.value = false
  }
}

function syncPolling() {
  if (polling.value && !pollTimer) pollTimer = window.setInterval(() => fetchFiles({ quiet: true }), 3000)
  if (!polling.value && pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function uploadSelectedFiles(event) {
  const selectedFiles = Array.from(event.target.files || [])
  event.target.value = ''
  await uploadFiles(selectedFiles)
}

async function dropFiles(event) {
  dragging.value = false
  await uploadFiles(Array.from(event.dataTransfer?.files || []))
}

async function uploadFiles(selectedFiles) {
  if (!canUploadFiles.value || !workspaceId.value || !selectedFiles.length || uploading.value) return
  uploading.value = true
  const selectedWorkspaceId = workspaceId.value
  let count = 0
  for (const file of selectedFiles) {
    if (workspaceId.value !== selectedWorkspaceId || !canUploadFiles.value) break
    try {
      await uploadFile(file, selectedWorkspaceId)
      count++
    } catch (err) {
      showToast('error', `${file.name}: ${errorMessage(err)}`)
    }
  }
  uploading.value = false
  if (count) {
    showToast('success', t('files.uploaded', { count }))
  }
  await fetchFiles()
}

function chooseReplacement(file) {
  if (!canManageFile(file, 'upload') || isProcessing(file.status)) return
  replaceTarget.value = file
  replaceInput.value.value = ''
  replaceInput.value.click()
}

async function replaceSelectedFile(event) {
  const file = event.target.files?.[0]
  const target = replaceTarget.value
  if (!file || !target || !canManageFile(target, 'upload') || isProcessing(target.status)) return
  replacingId.value = target.id
  try {
    await replaceFile(workspaceId.value, target.id, file)
    showToast('success', t('files.replaced', { name: target.filename || target.name }))
    await fetchFiles()
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    await fetchFiles()
    replacingId.value = null
    event.target.value = ''
  }
}

async function deleteFile(file) {
  if (!canManageFile(file, 'delete') || isProcessing(file.status)) return
  const selectedWorkspaceId = workspaceId.value
  try {
    await confirmBox(t, t('files.deleteConfirm', { name: file.filename || file.name }), t('common.delete'), { type: 'warning' })
  } catch {
    return
  }
  if (workspaceId.value !== selectedWorkspaceId || !canManageFile(file, 'delete')) return
  deletingId.value = file.id
  try {
    await removeFile(selectedWorkspaceId, file.id)
    showToast('success', t('files.deleteSubmitted', { name: file.filename || file.name }))
    await fetchFiles()
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    await fetchFiles()
    deletingId.value = null
  }
}

watch([workspaceId, canReadFiles], () => {
  fetchRequestId++
  loading.value = false
  files.value = []
  replaceTarget.value = null
  syncPolling()
  fetchFiles()
}, { immediate: true })
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.upload-zone { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; width: 100%; min-height: 150px; margin: 8px 0 16px; padding: 24px 20px; border: 1px dashed var(--el-border-color); border-radius: 6px; background: var(--el-fill-color-extra-light); color: var(--el-text-color-primary); font: inherit; cursor: pointer; }
.upload-zone:hover:not(:disabled), .upload-zone.dragging { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.upload-zone:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.upload-zone:disabled { cursor: not-allowed; opacity: 0.5; }
.upload-zone[aria-busy="true"] { cursor: wait; }
.upload-zone .el-icon { font-size: 28px; color: var(--el-color-primary); pointer-events: none; }
.upload-title { font-size: 14px; line-height: 1.5; pointer-events: none; }
.upload-types { max-width: 100%; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; color: var(--el-text-color-secondary); pointer-events: none; }
.docs-title h3 { font-size: 15px; font-weight: 650; }
.file-toolbar { display: flex; align-items: center; gap: 16px; min-height: 48px; margin-bottom: 10px; }
.file-toolbar > .el-button { margin-left: auto; }
.file-list { min-width: 0; }
.docs-head { display: flex; align-items: center; min-height: 42px; }
.docs-title { display: flex; align-items: center; gap: 8px; }
.docs-count { font-size: 12px; color: var(--el-text-color-secondary); }
.polling-label { color: var(--el-color-warning); font-size: 12px; }
.file-id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; user-select: text; }
@media (max-width: 650px) { .file-toolbar { flex-wrap: wrap; } }
</style>
