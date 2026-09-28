<template>
  <section class="workspace-panel workspaces-view" v-loading="loading">
    <SectionHeader :description="t('workspaces.desc')">
      <template #actions><RefreshButton :loading="loading" @click="fetchWorkspaces" /></template>
    </SectionHeader>
    <el-form v-if="canCreateWorkspace" class="create-row" @submit.prevent="create">
      <el-input v-model.trim="name" :placeholder="t('workspaces.namePlaceholder')" maxlength="100" clearable />
      <el-button type="primary" native-type="submit" :loading="creating" :disabled="!name">{{ t('workspaces.create') }}</el-button>
    </el-form>
    <el-table v-if="workspaces.length" :data="workspaces" style="width: 100%" @row-click="openWorkspace">
      <el-table-column prop="name" :label="t('workspaces.name')" min-width="220" show-overflow-tooltip />
      <el-table-column prop="id" label="ID" min-width="220" show-overflow-tooltip />
      <el-table-column :label="t('members.role')" min-width="120">
        <template #default="{ row }">{{ row.role ? t(`members.roles.${row.role}`) : '' }}</template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="160" align="right">
        <template #default="{ row }">
          <el-button text type="primary" @click.stop="openWorkspace(row)">{{ t('apps.enter') }}</el-button>
          <el-button v-if="row.permissions?.['workspace.delete'] === true" text type="danger" :loading="deletingId === row.id" @click.stop="deleteWorkspace(row)">{{ t('common.delete') }}</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else-if="!loading" :description="t('workspaces.empty')" />
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import RefreshButton from '../components/RefreshButton.vue'
import SectionHeader from '../components/SectionHeader.vue'
import { createWorkspace, removeWorkspace } from '../utils/kbApi'
import { useAppsStore } from '../stores/apps'
import { errorMessage, showToast } from '../utils/toast'
import { confirmBox } from '../utils/messageBox'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const appsStore = useAppsStore()
const workspaces = computed(() => appsStore.workspacesByApp[route.params.app_id] || [])
const canCreateWorkspace = computed(() => appsStore.workspacePermissionsByApp[route.params.app_id]?.['workspace.create'] === true)
const name = ref('')
const loading = ref(false)
const creating = ref(false)
const deletingId = ref(null)

async function fetchWorkspaces() {
  loading.value = true
  try {
    await appsStore.fetchWorkspaces(route.params.app_id)
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    loading.value = false
  }
}

function openWorkspace(workspace) {
  router.push(`/apps/${route.params.app_id}/workspaces/${workspace.id}/files`)
}

async function create() {
  if (!canCreateWorkspace.value || !name.value || creating.value) return
  const appId = route.params.app_id
  creating.value = true
  try {
    const workspace = await createWorkspace(appId, name.value)
    if (route.params.app_id !== appId) return
    name.value = ''
    await fetchWorkspaces()
    if (route.params.app_id === appId) openWorkspace(workspace)
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    creating.value = false
  }
}

async function deleteWorkspace(workspace) {
  if (workspace.permissions?.['workspace.delete'] !== true) return
  const appId = route.params.app_id
  try {
    await confirmBox(t, t('workspaces.deleteConfirm', { name: workspace.name }), t('common.delete'), { type: 'warning' })
  } catch {
    return
  }
  if (route.params.app_id !== appId || workspaces.value.find(row => row.id === workspace.id)?.permissions?.['workspace.delete'] !== true) return
  deletingId.value = workspace.id
  try {
    await removeWorkspace(workspace.id)
    showToast('success', t('workspaces.deleted', { name: workspace.name }))
    await fetchWorkspaces()
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    deletingId.value = null
  }
}

onMounted(fetchWorkspaces)
watch(() => route.params.app_id, fetchWorkspaces, { flush: 'post' })
</script>

<style scoped>
.create-row { display: flex; gap: 10px; max-width: 560px; margin-bottom: 22px; }
.create-row .el-input { min-width: 0; }
@media (max-width: 600px) { .create-row { flex-direction: column; } }
</style>
