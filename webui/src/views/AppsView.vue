<template>
  <main v-if="isPlatformAdmin" class="apps-view">
    <div class="monitor-section">
      <div class="monitor-head">
        <div>
          <h2>{{ t('apps.title') }}</h2>
          <p>{{ t('apps.desc') }}</p>
        </div>
      </div>
      <el-form v-if="isPlatformAdmin" class="app-create-form" @submit.prevent="createApp">
        <el-form-item>
          <el-input
            v-model.trim="newAppId"
            :placeholder="t('apps.appIdPlaceholder')"
            :maxlength="40"
            clearable
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model.trim="newAppName"
            :placeholder="t('apps.namePlaceholder')"
            clearable
          />
        </el-form-item>
        <el-button type="primary" :loading="creating" native-type="submit">{{ t('apps.create') }}</el-button>
      </el-form>
      <div v-if="apps.length" class="trace-table-wrap apps-table-wrap">
        <el-table :data="apps" style="width: 100%">
          <el-table-column prop="name" :label="t('apps.name')" min-width="180" show-overflow-tooltip />
          <el-table-column label="app_id" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.app_id }}</template>
          </el-table-column>
          <el-table-column v-if="isPlatformAdmin" label="api_key" min-width="360" show-overflow-tooltip>
            <template #default="{ row }">
              <div v-if="row.api_key" class="copy-cell">
                <span class="chunk-id">{{ row.api_key }}</span>
                <el-button :icon="CopyDocument" circle size="small" @click.stop="copyText(row.api_key)" />
              </div>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('common.actions')" min-width="184">
            <template #default="{ row }">
              <div class="app-row-actions">
                <el-button type="primary" size="small" @click="selectApp(row)">{{ t('apps.enter') }}</el-button>
                <el-button :disabled="!isPlatformAdmin" type="danger" size="small" plain @click="deleteApp(row)">{{ t('common.delete') }}</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div v-else class="trace-empty">{{ t('apps.empty') }}</div>
    </div>
  </main>
  <main v-else class="apps-view" v-loading="!appsReady"><el-empty v-if="appsReady" :description="t('apps.empty')" /></main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useActiveAppStore } from '../stores/activeApp'
import { useAppsStore } from '../stores/apps'
import { useAuthStore } from '../stores/auth'
import { CopyDocument } from '@element-plus/icons-vue'
import { copyText } from '../utils/format'
import { errorMessage, showToast } from '../utils/toast'
import { confirmBox } from '../utils/messageBox'

const router = useRouter()
const { t } = useI18n()
const activeAppStore = useActiveAppStore()
const authStore = useAuthStore()

const appsStore = useAppsStore()
const { apps } = storeToRefs(appsStore)
const { currentUser } = storeToRefs(authStore)
const isPlatformAdmin = computed(() => currentUser.value?.is_platform_admin === true)
const newAppName = ref('')
const newAppId = ref('')
const creating = ref(false)
const appsReady = ref(false)
function selectApp(app) {
  const id = app?.id ?? app?.app_id
  if (!id) return
  activeAppStore.appId = id
  router.push(`/apps/${id}/workspaces`)
}

async function createApp() {
  if (!newAppName.value) {
    showToast('error', t('apps.nameRule'))
    return
  }
  if (!/^[A-Za-z][A-Za-z0-9_]{1,39}$/.test(newAppId.value)) {
    showToast('error', t('apps.appIdRule'))
    return
  }
  creating.value = true
  const name = newAppName.value
  try {
    await appsStore.createApp(name, newAppId.value)
    newAppName.value = ''
    newAppId.value = ''
    showToast('success', t('apps.created', { name }))
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    creating.value = false
  }
}

async function deleteApp(app) {
  const id = app?.id ?? app?.app_id
  const name = app?.name ?? app?.app_id
  if (!id) return
  try {
    await confirmBox(t, t('apps.deleteConfirm', { name }), t('common.delete'), { type: 'warning' })
    await appsStore.deleteApp(id)
    if (activeAppStore.appId === id) activeAppStore.appId = ''
    showToast('success', t('apps.deleted', { name }))
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    showToast('error', errorMessage(err))
  }
}

onMounted(async () => {
  try {
    if (!currentUser.value) await authStore.fetchCurrentUser()
    await appsStore.fetchApps()
  } finally {
    appsReady.value = true
  }
})
watch([currentUser, apps, appsReady], ([user, available, ready]) => {
  if (!ready || !user || user.role === 'owner' || !available.length) return
  const id = available[0].id ?? available[0].app_id
  router.replace(`/apps/${id}/workspaces`)
}, { immediate: true })
</script>
