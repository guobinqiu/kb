<template>
  <main class="workspace-view">
    <header class="workspace-heading">
      <div class="workspace-heading-row">
        <div>
          <h2>{{ isSearchPage ? t('nav.search') : isChatPage ? t('nav.llm') : isWorkspacesPage ? t('nav.workspaces') : selectedOrg?.name || appName }}</h2>
          <p v-if="!isStandalonePage && parentOrg">{{ t('organizations.parent') }}: {{ parentOrg.name }}</p>
        </div>
        <el-button v-if="!isStandalonePage && parentOrg && selectableOrgIds.has(parentOrg.id)" :icon="ArrowUp" @click="selectOrg(parentOrg.id)">{{ t('workspace.parent') }}</el-button>
      </div>
    </header>

    <div class="workspace-body" :class="{ 'without-tree': isStandalonePage }">
      <aside v-if="!isStandalonePage" class="organization-nav" v-loading="loading">
        <div class="organization-nav-head">
          <span>{{ t('organizations.title') }}</span>
          <RefreshButton :loading="loading" @click="fetchOrgs" />
        </div>
        <el-tree
          v-if="tree.length"
          ref="treeRef"
          :data="tree"
          node-key="id"
          :default-expanded-keys="expandedKeys"
          :current-node-key="selectedOrgId"
          :expand-on-click-node="false"
          highlight-current
          @node-click="org => selectOrg(org.id)"
        >
          <template #default="{ data }">
            <span class="organization-tree-label" :class="{ 'read-only': !selectableOrgIds.has(data.id) }">
              <el-icon><OfficeBuilding /></el-icon>
              <span>{{ data.name }}</span>
              <span v-if="data.deleted_at" class="inactive-dot" :title="t('users.disabled')" />
            </span>
          </template>
        </el-tree>
        <el-empty v-else-if="!loading" :description="t('organizations.empty')" :image-size="64" />
      </aside>

      <section class="workspace-content">
        <router-view />
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, provide, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowUp, OfficeBuilding } from '@element-plus/icons-vue'
import RefreshButton from '../components/RefreshButton.vue'
import { useAppsStore } from '../stores/apps'
import { useAuthStore } from '../stores/auth'
import { getOrgs } from '../utils/kbApi'
import { buildOrgTree, descendantOrgs } from '../utils/organization'
import { errorMessage, showToast } from '../utils/toast'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { apps } = storeToRefs(useAppsStore())
const { currentUser } = storeToRefs(useAuthStore())
const orgs = ref([])
const loading = ref(false)
const treeRef = ref(null)
const appId = computed(() => route.params.app_id)
const isWorkspacesPage = computed(() => route.path.endsWith('/workspaces'))
const isSearchPage = computed(() => route.path.endsWith('/search'))
const isChatPage = computed(() => route.path.endsWith('/llm'))
const isStandalonePage = computed(() => isWorkspacesPage.value || isSearchPage.value || isChatPage.value)
const appName = computed(() => apps.value.find(app => app.app_id === appId.value)?.name || appId.value)
const selectedOrgId = computed(() => route.query.org_id || null)
const selectedOrg = computed(() => orgs.value.find(org => org.id === selectedOrgId.value))
const parentOrg = computed(() => orgs.value.find(org => org.id === selectedOrg.value?.parent_id))
const selectableOrgIds = computed(() => new Set((currentUser.value?.role === 'owner' ? orgs.value : descendantOrgs(orgs.value, currentUser.value?.org_id)).map(org => org.id)))
const expandedKeys = computed(() => {
  const ids = []
  for (let org = selectedOrg.value; org; org = orgs.value.find(item => item.id === org.parent_id)) ids.unshift(org.id)
  return ids.length ? ids : orgs.value.filter(org => !orgs.value.some(parent => parent.id === org.parent_id)).map(org => org.id)
})
const tree = computed(() => buildOrgTree(orgs.value))

async function fetchOrgs() {
  if (!appId.value || isStandalonePage.value) return
  loading.value = true
  try {
    orgs.value = await getOrgs(appId.value, ['owner', 'admin'].includes(currentUser.value?.role))
    if (!isStandalonePage.value && !selectableOrgIds.value.has(selectedOrgId.value) && selectableOrgIds.value.size) {
      router.replace({ path: route.path, query: { org_id: currentUser.value?.role === 'owner' ? tree.value[0].id : currentUser.value.org_id } })
    }
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    loading.value = false
  }
}

function selectOrg(id) {
  if (selectableOrgIds.value.has(id) && id !== selectedOrgId.value) router.push({ path: route.path, query: { org_id: id } })
}

watch(selectedOrgId, id => {
  treeRef.value?.setCurrentKey(id)
  for (const ancestorId of expandedKeys.value) treeRef.value?.store.nodesMap[ancestorId]?.expand()
})
watch(appId, fetchOrgs)
watch(isStandalonePage, value => { if (!value) fetchOrgs() })
onMounted(fetchOrgs)
provide('refreshWorkspaceOrgs', fetchOrgs)
</script>

<style scoped>
.workspace-view { min-height: calc(100vh - 62px); background: var(--el-bg-color); }
.workspace-heading { padding: 22px 32px 20px; border-bottom: 1px solid var(--el-border-color); }
.workspace-heading-row { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.workspace-heading h2 { font-size: 22px; font-weight: 650; line-height: 1.3; }
.workspace-heading p { margin-top: 4px; color: var(--el-text-color-secondary); font-size: 12px; }
.workspace-body { display: grid; grid-template-columns: 250px minmax(0, 1fr); min-height: calc(100vh - 165px); }
.workspace-body.without-tree { display: block; }
.organization-nav { min-width: 0; padding: 20px 12px; border-right: 1px solid var(--el-border-color); }
.organization-nav-head { display: flex; align-items: center; justify-content: space-between; padding: 0 8px 12px; font-size: 12px; font-weight: 650; color: var(--el-text-color-secondary); }
.organization-nav :deep(.el-tree-node__content) { min-height: 36px; height: auto; border-radius: 4px; }
.organization-tree-label { min-width: 0; display: flex; align-items: center; gap: 7px; font-size: 13px; }
.organization-tree-label > span:not(.inactive-dot) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.organization-tree-label .el-icon { flex: none; color: var(--el-text-color-secondary); }
.organization-tree-label.read-only { color: var(--el-text-color-secondary); cursor: default; }
.inactive-dot { flex: none; width: 6px; height: 6px; border-radius: 50%; background: var(--el-color-danger); }
.workspace-content { min-width: 0; display: flex; flex-direction: column; }
:deep(.workspace-panel) { padding: 24px 32px 32px; }
@media (max-width: 800px) {
  .workspace-heading { padding: 18px 18px 16px; }
  .workspace-body { display: block; }
  .organization-nav { border-right: 0; border-bottom: 1px solid var(--el-border-color); padding: 10px 12px; max-height: 230px; overflow: auto; }
  :deep(.workspace-panel) { padding: 18px; }
}
</style>
