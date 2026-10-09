<template>
  <section class="workspace-panel organizations-view" v-loading="loading">
    <SectionHeader :title="t('organizations.title')" :description="selectedOrg?.name || t('organizations.empty')">
      <template #actions>
        <el-button :disabled="!canManage || !selectedOrg || isOrgInactive(selectedOrg.id)" type="primary" :icon="Plus" @click="openCreate">{{ t('organizations.createChild') }}</el-button>
      </template>
    </SectionHeader>

    <div v-if="selectedOrg" class="organization-detail">
      <div class="organization-properties">
        <div><span>{{ t('organizations.name') }}</span><strong>{{ selectedOrg.name }}</strong></div>
        <div><span>{{ t('organizations.parent') }}</span><strong>{{ parentOrg?.name || '-' }}</strong></div>
        <div><span>{{ t('users.status') }}</span><strong>{{ selectedOrg.deleted_at ? t('users.disabled') : t('users.active') }}</strong></div>
      </div>
      <div class="organization-actions">
        <el-button :disabled="!canManage || isOrgInactive(selectedOrg.id)" :icon="Edit" @click="openEdit(selectedOrg)">{{ t('common.edit') }}</el-button>
        <el-button v-if="selectedOrg.deleted_at" :disabled="!canManage" :icon="RefreshLeft" :loading="deletingId === selectedOrg.id" @click="restoreOrg(selectedOrg)">{{ t('common.restore') }}</el-button>
        <el-button v-else :icon="Delete" type="danger" plain :disabled="!canManage || !selectedOrg.parent_id || isOrgInactive(selectedOrg.parent_id) || selectedOrg.id === currentUser?.org_id" :loading="deletingId === selectedOrg.id" @click="deleteOrg(selectedOrg)">{{ t('common.disable') }}</el-button>
      </div>
    </div>

    <div class="subsection-head">
      <h3>{{ t('workspace.children') }}</h3>
      <span>{{ children.length }}</span>
    </div>
    <div v-if="children.length" class="children-list">
      <button v-for="child in children" :key="child.id" type="button" class="child-row" @click="selectOrg(child.id)">
        <el-icon><OfficeBuilding /></el-icon>
        <span>{{ child.name }}</span>
        <small v-if="child.deleted_at">{{ t('users.disabled') }}</small>
        <el-icon><ArrowRight /></el-icon>
      </button>
    </div>
    <el-empty v-else :description="t('workspace.noChildren')" :image-size="72" />

    <el-dialog v-model="dialogVisible" :title="editingId ? t('common.edit') : t('organizations.createChild')" width="min(480px, 94vw)">
      <el-form label-position="top" @submit.prevent="submitOrg">
        <el-form-item :label="t('organizations.parent')">
          <el-tree-select v-model="form.parent_id" :data="tree" node-key="id" :props="{ label: 'name', children: 'children' }" check-strictly :disabled="Boolean(editingId && editingParentId == null)" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('organizations.name')"><el-input v-model.trim="form.name" maxlength="100" @keyup.enter="submitOrg" /></el-form-item>
      </el-form>
      <template #footer>
        <DialogActions :loading="creating" @cancel="dialogVisible = false" @confirm="submitOrg" />
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { ArrowRight, Delete, Edit, OfficeBuilding, Plus, RefreshLeft } from '@element-plus/icons-vue'
import SectionHeader from '../components/SectionHeader.vue'
import DialogActions from '../components/DialogActions.vue'
import { useAuthStore } from '../stores/auth'
import { createOrg, getOrgs, removeOrg, updateOrg } from '../utils/kbApi'
import { confirmBox } from '../utils/messageBox'
import { errorMessage, showToast } from '../utils/toast'
import { buildOrgTree, isOrgInactive as orgIsInactive } from '../utils/organization'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { currentUser } = storeToRefs(useAuthStore())
const refreshWorkspaceOrgs = inject('refreshWorkspaceOrgs', async () => {})
const canManage = computed(() => ['owner', 'admin'].includes(currentUser.value?.role))
const appId = computed(() => route.params.app_id)
const selectedOrgId = computed(() => route.query.org_id)
const orgs = ref([])
const selectedOrg = computed(() => orgs.value.find(org => org.id === selectedOrgId.value))
const parentOrg = computed(() => orgs.value.find(org => org.id === selectedOrg.value?.parent_id))
const children = computed(() => orgs.value.filter(org => org.parent_id === selectedOrgId.value))
const loading = ref(false)
const creating = ref(false)
const deletingId = ref(null)
const dialogVisible = ref(false)
const editingId = ref(null)
const editingParentId = ref(null)
const form = ref({ parent_id: null, name: '' })

const tree = computed(() => buildOrgTree(orgs.value))

function isOrgInactive(orgId) {
  return orgIsInactive(orgs.value, orgId)
}

async function fetchOrgs() {
  if (!appId.value) return
  loading.value = true
  try {
    orgs.value = await getOrgs(appId.value, canManage.value)
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    loading.value = false
  }
}

function selectOrg(id) {
  return router.push({ path: route.path, query: { ...route.query, org_id: id } })
}

function openCreate() {
  editingId.value = null
  form.value = { parent_id: selectedOrgId.value, name: '' }
  dialogVisible.value = true
}

function openEdit(org) {
  editingId.value = org.id
  editingParentId.value = org.parent_id
  form.value = { parent_id: orgs.value.some(item => item.id === org.parent_id) ? org.parent_id : null, name: org.name }
  dialogVisible.value = true
}

async function submitOrg() {
  if (!form.value.name || (!editingId.value && !form.value.parent_id) || creating.value) return
  creating.value = true
  try {
    let created
    if (editingId.value) await updateOrg(editingId.value, {
      name: form.value.name,
      ...(form.value.parent_id && form.value.parent_id !== editingParentId.value ? { parent_id: form.value.parent_id } : {}),
    })
    else created = await createOrg({ parent_id: form.value.parent_id, name: form.value.name })
    dialogVisible.value = false
    showToast('success', t('organizations.created'))
    await Promise.all([fetchOrgs(), refreshWorkspaceOrgs()])
    if (created?.id) selectOrg(created.id)
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    creating.value = false
  }
}

async function restoreOrg(org) {
  deletingId.value = org.id
  try {
    await updateOrg(org.id, { deleted_at: null })
    showToast('success', t('organizations.restored', { name: org.name }))
    await Promise.all([fetchOrgs(), refreshWorkspaceOrgs()])
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    deletingId.value = null
  }
}

async function deleteOrg(org) {
  try {
    await confirmBox(t, t('organizations.deleteConfirm', { name: org.name }), t('common.disable'), { type: 'warning' })
  } catch {
    return
  }
  deletingId.value = org.id
  try {
    await removeOrg(org.id)
    showToast('success', t('organizations.disabled', { name: org.name }))
    await Promise.all([fetchOrgs(), refreshWorkspaceOrgs()])
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    deletingId.value = null
  }
}

onMounted(fetchOrgs)
watch(appId, fetchOrgs)
watch(() => currentUser.value?.role, fetchOrgs)
</script>

<style scoped>
.subsection-head h3 { font-size: 15px; font-weight: 650; }
.organization-detail { padding-bottom: 28px; border-bottom: 1px solid var(--el-border-color-lighter); }
.organization-properties { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; }
.organization-properties > div { display: grid; gap: 7px; min-width: 0; }
.organization-properties span { color: var(--el-text-color-secondary); font-size: 12px; }
.organization-properties strong { overflow: hidden; text-overflow: ellipsis; font-size: 14px; font-weight: 550; }
.organization-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 22px; }
.subsection-head { display: flex; align-items: center; gap: 8px; margin: 28px 0 10px; }
.subsection-head span { color: var(--el-text-color-secondary); font-size: 12px; }
.children-list { border-top: 1px solid var(--el-border-color-lighter); }
.child-row { display: flex; align-items: center; gap: 11px; width: 100%; min-height: 48px; padding: 8px 2px; border: 0; border-bottom: 1px solid var(--el-border-color-lighter); background: none; color: var(--el-text-color-primary); font: inherit; text-align: left; cursor: pointer; }
.child-row:hover { color: var(--el-color-primary); }
.child-row > span { flex: 1; font-size: 13px; }
.child-row small { color: var(--el-text-color-secondary); }
.child-row > .el-icon:last-child { color: var(--el-text-color-secondary); }
@media (max-width: 650px) { .organization-properties { grid-template-columns: 1fr 1fr; } }
</style>
