<template>
  <main class="workspace-shell">
    <header class="shell-header">
      <h2>{{ workspace?.name || route.params.workspace_id }}</h2>
    </header>
    <router-view />
  </main>
</template>

<script setup>
import { computed, onMounted, provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAppsStore } from '../stores/apps'
import { getWorkspace } from '../utils/kbApi'
import { errorMessage, showToast } from '../utils/toast'

const route = useRoute()
const appsStore = useAppsStore()
const workspaceDetail = ref(null)
let workspaceRequestId = 0
const workspace = computed(() => workspaceDetail.value?.workspace || (appsStore.workspacesByApp[route.params.app_id] || []).find(item => item.id === route.params.workspace_id))
const workspacePermissions = computed(() => workspaceDetail.value?.permissions || {})

provide('workspacePermissions', workspacePermissions)
provide('refreshWorkspace', fetchWorkspace)

async function fetchWorkspace() {
  const requestId = ++workspaceRequestId
  const workspaceId = route.params.workspace_id
  workspaceDetail.value = null
  try {
    await appsStore.fetchWorkspaces(route.params.app_id)
    const detail = await getWorkspace(workspaceId)
    if (requestId === workspaceRequestId) workspaceDetail.value = detail
  } catch (err) {
    if (requestId === workspaceRequestId) showToast('error', errorMessage(err))
  }
}

onMounted(fetchWorkspace)
watch(() => [route.params.app_id, route.params.workspace_id], fetchWorkspace, { flush: 'post' })
</script>

<style scoped>
.workspace-shell { min-height: calc(100vh - 64px); background: var(--el-bg-color); }
.shell-header { padding: 20px 32px 16px; border-bottom: 1px solid var(--el-border-color); }
.shell-header h2 { font-size: 22px; font-weight: 650; overflow-wrap: anywhere; }
.workspace-shell :deep(.workspace-panel) { min-width: 0; padding: 24px 32px 32px; }
@media (max-width: 700px) {
  .shell-header { padding: 16px 18px; }
  .workspace-shell :deep(.workspace-panel) { padding: 18px; }
}
</style>
