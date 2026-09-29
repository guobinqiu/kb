<template>
  <section class="workspace-panel users-view">
    <SectionHeader :title="t('users.title')" :description="platformAccounts ? t('workspace.platformAccounts') : selectedOrg?.name || t('users.selectOrg')">
      <template #actions>
        <el-button :icon="Lock" @click="passwordDialog = true">{{ t('workspace.myAccount') }}</el-button>
        <el-button type="primary" :icon="Plus" :disabled="!canManage || (!platformAccounts && !effectiveOrgId) || (effectiveOrgId && isOrgInactive(effectiveOrgId))" @click="dialogVisible = true">{{ t('users.create') }}</el-button>
      </template>
    </SectionHeader>

    <div class="member-toolbar">
      <el-radio-group v-if="currentUser?.role === 'owner'" v-model="platformAccounts" size="small">
        <el-radio-button :value="false">{{ t('workspace.orgAccounts') }}</el-radio-button>
        <el-radio-button :value="true">{{ t('workspace.platformAccounts') }}</el-radio-button>
      </el-radio-group>
      <RefreshButton :loading="loading" :disabled="!platformAccounts && !effectiveOrgId" @click="fetchUsers" />
    </div>

      <el-table v-if="visibleUsers.length || loading" :data="visibleUsers" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" :label="t('auth.name')" min-width="180" />
        <el-table-column :label="t('users.role')" min-width="120"><template #default="{ row }">{{ t(`users.roles.${row.role}`) }}</template></el-table-column>
        <el-table-column :label="t('users.status')" min-width="100"><template #default="{ row }">{{ row.deleted_at ? t('users.disabled') : t('users.active') }}</template></el-table-column>
        <el-table-column :label="t('users.org')" min-width="170" show-overflow-tooltip><template #default="{ row }">{{ orgName(row.org_id) }}</template></el-table-column>
        <el-table-column :label="t('common.actions')" width="132" align="right">
          <template #default="{ row }">
            <el-tooltip :content="t('common.edit')">
              <el-button :disabled="!canManage || row.id === currentUser?.id || (row.role === 'owner' && currentUser?.role !== 'owner')" :icon="Edit" circle size="small" :aria-label="t('common.edit')" @click="openEdit(row)" />
            </el-tooltip>
            <el-tooltip :content="row.deleted_at ? t('common.restore') : t('common.disable')">
              <el-button :disabled="!canManage || row.id === currentUser?.id || (row.role === 'owner' && currentUser?.role !== 'owner')" :icon="row.deleted_at ? RefreshLeft : Delete" circle size="small" :type="row.deleted_at ? 'primary' : 'danger'" plain :aria-label="row.deleted_at ? t('common.restore') : t('common.disable')" :loading="deletingId === row.id" @click="row.deleted_at ? restoreUser(row) : deleteUser(row)" />
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else :description="platformAccounts || effectiveOrgId ? t('users.empty') : t('users.selectOrg')" />

    <el-dialog v-model="dialogVisible" :title="editingId ? t('common.edit') : t('users.create')" width="min(480px, 94vw)">
      <el-form label-position="top" @submit.prevent="submitUser">
        <el-form-item v-if="!platformAccounts" :label="t('users.org')">
          <el-tree-select
            v-model="form.org_id"
            :data="orgTree"
            node-key="id"
            :props="{ label: 'name', children: 'children' }"
            check-strictly
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item v-if="!editingId" :label="t('auth.name')"><el-input v-model.trim="form.name" autocomplete="off" /></el-form-item>
        <el-form-item :label="t('users.role')">
          <el-select v-model="form.role" style="width: 100%">
            <el-option v-for="role in assignableRoles" :key="role" :label="t(`users.roles.${role}`)" :value="role" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!editingId" :label="t('auth.password')"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" /></el-form-item>
      </el-form>
      <template #footer>
        <DialogActions :loading="creating" @cancel="dialogVisible = false" @confirm="submitUser" />
      </template>
    </el-dialog>
    <el-dialog v-model="passwordDialog" :title="t('auth.changePassword')" width="min(420px, 94vw)">
      <el-form label-position="top" @submit.prevent="submitPassword">
        <el-form-item :label="t('auth.oldPassword')"><el-input v-model="passwordForm.old" type="password" autocomplete="current-password" show-password /></el-form-item>
        <el-form-item :label="t('auth.newPassword')"><el-input v-model="passwordForm.new" type="password" autocomplete="new-password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <DialogActions :loading="changingPassword" @cancel="passwordDialog = false" @confirm="submitPassword" />
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Delete, Edit, Lock, Plus, RefreshLeft } from '@element-plus/icons-vue'
import RefreshButton from '../components/RefreshButton.vue'
import SectionHeader from '../components/SectionHeader.vue'
import DialogActions from '../components/DialogActions.vue'
import { changePassword, createUser, getOrgs, getUsers, removeUser, updateUser } from '../utils/kbApi'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '../stores/auth'
import { confirmBox } from '../utils/messageBox'
import { errorMessage, showToast } from '../utils/toast'
import { buildOrgTree, descendantOrgs, isOrgInactive as orgIsInactive } from '../utils/organization'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { currentUser } = storeToRefs(useAuthStore())
const canManage = computed(() => ['owner', 'admin'].includes(currentUser.value?.role))
const assignableRoles = computed(() => form.value.org_id == null ? ['owner'] : ['member', 'admin'])
const appId = computed(() => route.params.app_id)
const orgs = ref([])
const users = ref([])
const selectedOrgId = computed(() => route.query.org_id || null)
const selectedOrg = computed(() => orgs.value.find(org => org.id === selectedOrgId.value))
const platformAccounts = ref(false)
const effectiveOrgId = computed(() => platformAccounts.value ? null : selectedOrgId.value)
const visibleUsers = computed(() => platformAccounts.value ? users.value.filter(user => user.org_id == null) : users.value)
const loading = ref(false)
const creating = ref(false)
const deletingId = ref(null)
const dialogVisible = ref(false)
const editingId = ref(null)
const form = ref({ org_id: null, name: '', password: '', role: 'member' })
const passwordDialog = ref(false)
const passwordForm = ref({ old: '', new: '' })
const changingPassword = ref(false)
let fetchRequestId = 0
let orgsRequestId = 0

function isOrgInactive(orgId) {
  return orgIsInactive(orgs.value, orgId)
}

const orgTree = computed(() => {
  const selectableOrgs = currentUser.value?.role === 'owner' ? orgs.value : descendantOrgs(orgs.value, currentUser.value?.org_id)
  return buildOrgTree(selectableOrgs.map(org => ({ ...org, disabled: isOrgInactive(org.id) })))
})

function orgName(orgId) {
  if (orgId == null) return t('workspace.platformAccounts')
  return orgs.value.find(org => org.id === orgId)?.name || orgId
}

async function fetchOrgs() {
  const requestId = ++orgsRequestId
  try {
    const result = await getOrgs(appId.value, canManage.value)
    if (requestId !== orgsRequestId) return
    orgs.value = result
  } catch (err) {
    if (requestId === orgsRequestId) showToast('error', errorMessage(err))
  }
}

async function fetchUsers() {
  if (!platformAccounts.value && !effectiveOrgId.value) {
    fetchRequestId++
    users.value = []
    loading.value = false
    return
  }
  const requestId = ++fetchRequestId
  const orgId = effectiveOrgId.value
  const globalAccounts = platformAccounts.value
  loading.value = true
  try {
    const result = await getUsers(orgId, canManage.value)
    if (requestId === fetchRequestId && orgId === effectiveOrgId.value && globalAccounts === platformAccounts.value) users.value = result
  } catch (err) {
    if (requestId === fetchRequestId) showToast('error', errorMessage(err))
  } finally {
    if (requestId === fetchRequestId) loading.value = false
  }
}

async function submitUser() {
  const isGlobalOwner = currentUser.value?.role === 'owner' && platformAccounts.value
  if ((!isGlobalOwner && !form.value.org_id) || (!editingId.value && (!form.value.name || !form.value.password)) || creating.value) return
  creating.value = true
  try {
    if (editingId.value) await updateUser(editingId.value, { org_id: form.value.org_id, role: form.value.role })
    else await createUser({ ...form.value })
    if (form.value.org_id && form.value.org_id !== selectedOrgId.value) {
      await router.push({ path: route.path, query: { ...route.query, org_id: form.value.org_id } })
    }
    dialogVisible.value = false
    form.value = { org_id: effectiveOrgId.value, name: '', password: '', role: platformAccounts.value ? 'owner' : 'member' }
    showToast('success', t('users.created'))
    await fetchUsers()
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    creating.value = false
  }
}

function openEdit(user) {
  editingId.value = user.id
  form.value = { org_id: user.org_id, name: user.name, password: '', role: user.role }
  dialogVisible.value = true
}

async function restoreUser(user) {
  deletingId.value = user.id
  try {
    await updateUser(user.id, { deleted_at: null })
    showToast('success', t('users.restored', { name: user.name }))
    await fetchUsers()
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    deletingId.value = null
  }
}

async function deleteUser(user) {
  try {
    await confirmBox(t, t('users.deleteConfirm', { name: user.name }), t('common.delete'), { type: 'warning' })
  } catch {
    return
  }
  deletingId.value = user.id
  try {
    await removeUser(user.id)
    showToast('success', t('users.deleted', { name: user.name }))
    await fetchUsers()
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    deletingId.value = null
  }
}

async function submitPassword() {
  if (!passwordForm.value.old || passwordForm.value.new.length < 8 || changingPassword.value) return
  changingPassword.value = true
  try {
    await changePassword(passwordForm.value.old, passwordForm.value.new)
    passwordDialog.value = false
    passwordForm.value = { old: '', new: '' }
    showToast('success', t('auth.passwordChanged'))
  } catch (err) {
    showToast('error', errorMessage(err))
  } finally {
    changingPassword.value = false
  }
}

watch(dialogVisible, visible => {
  if (!visible) editingId.value = null
  else if (!editingId.value) form.value = { org_id: effectiveOrgId.value, name: '', password: '', role: platformAccounts.value ? 'owner' : 'member' }
})
watch(() => form.value.org_id, orgId => {
  if (orgId == null) form.value.role = 'owner'
  else if (form.value.role === 'owner') form.value.role = 'member'
})
watch([effectiveOrgId, platformAccounts], fetchUsers, { immediate: true })
watch(selectedOrgId, () => { platformAccounts.value = false })
watch(appId, async () => {
  platformAccounts.value = false
  users.value = []
  await fetchOrgs()
})
watch(() => currentUser.value?.role, async () => {
  await fetchOrgs()
  await fetchUsers()
})
onMounted(fetchOrgs)
</script>

<style scoped>
.member-toolbar { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; min-height: 48px; margin-bottom: 10px; }
.member-toolbar > .el-button { margin-left: auto; }
@media (max-width: 650px) { .member-toolbar > .el-button { margin-left: 0; } }
</style>
