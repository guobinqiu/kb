<template>
  <section class="workspace-panel members-view" v-loading="loading">
    <div class="members-toolbar">
      <RefreshButton :loading="loading" @click="refresh" />
    </div>
    <section v-for="group in memberGroups" :key="group.type" class="access-section">
      <div class="access-header">
        <h4>{{ t(group.title) }}</h4>
        <div class="access-actions">
          <el-button :disabled="!canManageMembers" :icon="Plus" @click="openAddDialog(group.type)">{{ t(group.addLabel) }}</el-button>
        </div>
      </div>
      <el-table v-if="group.members.length" :data="group.members" style="width: 100%" @row-click="row => canManageMembers && row.type === 'org' && previewOrg(row)">
        <el-table-column :label="t('members.name')" min-width="180">
          <template #default="{ row }">
            <el-button v-if="row.type === 'org'" :disabled="!canManageMembers" class="member-name" text type="primary" @click.stop="previewOrg(row)">{{ row.name }}</el-button>
            <span v-else>{{ row.name }}</span>
            <p v-if="overriddenOrg(row)" class="directory-hint">{{ t('members.personalOverride', { name: overriddenOrg(row).name }) }}</p>
          </template>
        </el-table-column>
        <el-table-column :label="t('members.role')" min-width="120">
          <template #default="{ row }">{{ t(`members.roles.${row.role}`) }}</template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="100" align="right">
          <template #default="{ row }">
            <el-tooltip :content="t('members.edit')"><el-button :disabled="!canManageMembers" :icon="Edit" circle size="small" :aria-label="t('members.edit')" @click.stop="openEditDialog(row)" /></el-tooltip>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else-if="!loadingMembers" :description="t(group.emptyLabel)" :image-size="64" />
    </section>

    <el-dialog v-model="addDialogVisible" :title="t(memberType === 'user' ? 'members.addUser' : 'members.addOrg')" :width="memberType === 'user' ? 'min(900px, 94vw)' : 'min(600px, 94vw)'" @opened="syncSelectionTree">
      <div class="member-picker" :class="{ 'user-selection': memberType === 'user' }">
        <div class="org-pane">
          <el-input v-model="orgSearch" :placeholder="t('members.searchOrganizations')" :aria-label="t('members.searchOrganizations')" :prefix-icon="Search" clearable :disabled="adding" />
          <el-button v-if="memberType === 'user'" class="all-users" text :type="selectedOrgId === null ? 'primary' : ''" :disabled="adding" @click="selectOrg(null)">{{ t('members.allUsers') }}</el-button>
          <div class="organization-tree" v-loading="loadingDirectory">
            <el-tree
              v-if="directoryTree.length"
              ref="treeRef"
              :data="directoryTree"
              node-key="key"
              :props="{ label: 'name', children: 'children', disabled: 'disabled' }"
              :show-checkbox="memberType === 'org'"
              :highlight-current="memberType === 'user'"
              check-strictly
              default-expand-all
              :expand-on-click-node="false"
              :check-on-click-node="false"
              :check-on-click-leaf="false"
              :filter-node-method="filterDirectoryNode"
              @node-click="data => memberType === 'user' && selectOrg(data.id)"
              @check="handleDirectoryCheck"
            >
              <template #default="{ data }">
                <span class="directory-option">
                  <el-icon><OfficeBuilding /></el-icon>
                  <span>{{ data.name }}</span>
                  <small v-if="memberType === 'org' && data.member">{{ t('members.alreadyAdded') }}</small>
                </span>
              </template>
            </el-tree>
            <el-empty v-else-if="!loadingDirectory" :description="t('members.emptyOrganizations')" :image-size="64" />
          </div>
        </div>
        <div v-if="memberType === 'user'" class="users-pane">
          <el-input v-model="userSearch" :placeholder="t('members.search')" :aria-label="t('members.search')" :prefix-icon="Search" clearable :disabled="adding" />
          <el-table class="user-picker" :data="users" v-loading="loadingUsers" height="320" :empty-text="t('members.noMatchingUsers')">
            <el-table-column width="44">
              <template #default="{ row }">
                <el-checkbox :model-value="isSelected('user', row.id)" :disabled="adding || isExistingMember('user', row.id)" :aria-label="row.name" @change="checked => selectUser(row, checked)" />
              </template>
            </el-table-column>
            <el-table-column :label="t('members.name')" min-width="160">
              <template #default="{ row }">
                <span>{{ row.name }}</span>
                <el-tag v-if="isExistingMember('user', row.id)" size="small" type="info">{{ t('members.alreadyAdded') }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination class="user-pagination" :current-page="usersPage" :page-size="usersPageSize" :total="usersTotal" :pager-count="5" layout="total, prev, pager, next" :disabled="adding" @current-change="changeUsersPage" />
        </div>
      </div>
      <el-form class="member-role-form" label-position="top">
        <el-form-item :label="t('members.role')">
          <el-select v-model="selectedRoles[memberType]" :disabled="adding">
            <el-option v-for="role in addRoles" :key="role" :value="role" :label="t(`members.roles.${role}`)" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="selected-members">
        <span>{{ t('members.selected', { count: selectedMembers.length }) }}</span>
        <el-tag v-for="member in selectedMembers" :key="`${member.type}:${member.id}`" :closable="!adding" @close="deselectMember(member)">
          <el-icon><OfficeBuilding v-if="member.type === 'org'" /><User v-else /></el-icon>
          <span>{{ member.name }} · {{ t(`members.roles.${selectedRoles[member.type]}`) }}</span>
        </el-tag>
      </div>
      <template #footer>
        <DialogActions :loading="adding" :disabled="!canManageMembers || !selectedMembers.length || loadingDirectory || loadingMembers" :confirm-label="t('members.addSelected', { count: selectedMembers.length })" @cancel="addDialogVisible = false" @confirm="addSelectedMembers" />
      </template>
    </el-dialog>

    <el-dialog v-model="editDialogVisible" :title="t('members.edit')" width="min(440px, 94vw)">
      <el-form v-if="editingMember" label-position="top">
        <el-form-item :label="t('members.name')">{{ editingMember.name }}</el-form-item>
        <el-form-item :label="t('members.role')">
          <el-select v-model="editRole" :disabled="saving || removing || !canManageMembers">
            <el-option v-for="role in roles" :key="role" :value="role" :label="t(`members.roles.${role}`)" :disabled="role === 'admin' && editingMember.type === 'org'" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <DialogActions :loading="saving" :disabled="!canManageMembers || removing || editRole === editingMember?.role" :confirm-label="t('common.save')" @cancel="editDialogVisible = false" @confirm="saveMember">
          <el-button type="danger" plain :icon="Delete" :loading="removing" :disabled="!canManageMembers || saving" @click="removeMember">{{ t('members.remove') }}</el-button>
        </DialogActions>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" :title="t('members.directUsers', { name: previewMember?.name })" width="min(520px, 94vw)">
      <el-input v-model="previewSearch" :placeholder="t('members.search')" :aria-label="t('members.search')" :prefix-icon="Search" clearable />
      <div class="preview-users" v-loading="loadingPreview">
        <el-table v-if="previewUsers.length" :data="previewUsers" height="320">
          <el-table-column prop="name" :label="t('auth.name')" min-width="160" show-overflow-tooltip />
        </el-table>
        <el-empty v-else-if="!loadingPreview" :description="t('members.emptyDirectUsers')" :image-size="64" />
      </div>
      <el-pagination class="user-pagination" :current-page="previewPage" :page-size="previewPageSize" :total="previewTotal" :pager-count="5" layout="total, prev, pager, next" @current-change="changePreviewPage" />
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Delete, Edit, OfficeBuilding, Plus, Search, User } from '@element-plus/icons-vue'
import RefreshButton from '../components/RefreshButton.vue'
import DialogActions from '../components/DialogActions.vue'
import { buildOrgTree } from '../utils/organization'
import { addWorkspaceMember, getWorkspaceOrgs, getWorkspaceUsers, getWorkspaceMembers, removeWorkspaceMember, updateWorkspaceMember } from '../utils/kbApi'
import { confirmBox } from '../utils/messageBox'
import { errorMessage, showToast } from '../utils/toast'

const { t } = useI18n()
const route = useRoute()
const workspacePermissions = inject('workspacePermissions', computed(() => ({})))
const refreshWorkspace = inject('refreshWorkspace')
const members = ref([])
const orgs = ref([])
const users = ref([])
const treeRef = ref(null)
const loadingMembers = ref(false)
const loadingDirectory = ref(false)
const loadingUsers = ref(false)
const usersPage = ref(1)
const usersPageSize = ref(20)
const usersTotal = ref(0)
const adding = ref(false)
const removing = ref(false)
const saving = ref(false)
const addDialogVisible = ref(false)
const selectedMembers = ref([])
const memberType = ref('user')
const selectedOrgId = ref(null)
const selectedRoles = ref({ user: 'editor', org: 'editor' })
const roles = ['admin', 'editor', 'viewer']
const orgSearch = ref('')
const userSearch = ref('')
const editDialogVisible = ref(false)
const editingMember = ref(null)
const editRole = ref('')
const previewVisible = ref(false)
const previewMember = ref(null)
const previewUsers = ref([])
const loadingPreview = ref(false)
const previewSearch = ref('')
const previewPage = ref(1)
const previewPageSize = ref(20)
const previewTotal = ref(0)
let membersRequestId = 0
let directoryRequestId = 0
let usersRequestId = 0
let previewRequestId = 0
let userSearchTimer = null
let previewSearchTimer = null
let addSessionId = 0

const loading = computed(() => loadingMembers.value)
const memberGroups = computed(() => [
  { type: 'user', title: 'members.userAccess', addLabel: 'members.addUser', emptyLabel: 'members.emptyUsers', members: members.value.filter(member => member.type === 'user') },
  { type: 'org', title: 'members.orgAccess', addLabel: 'members.addOrg', emptyLabel: 'members.emptyOrgAccess', members: members.value.filter(member => member.type === 'org') },
])
const canManageMembers = computed(() => workspacePermissions.value?.['workspace.members.manage'] === true)
const addRoles = computed(() => memberType.value === 'org' ? roles.filter(role => role !== 'admin') : roles)
const directoryTree = computed(() => {
  return buildOrgTree(orgs.value.map(org => ({
    ...org,
    key: `org:${org.id}`,
    type: 'org',
    member: isExistingMember('org', org.id),
    disabled: adding.value || (memberType.value === 'org' && isExistingMember('org', org.id)),
  })))
})

function overriddenOrg(member) {
  if (member.type !== 'user' || member.org_id == null) return null
  return members.value.find(org => org.type === 'org' && org.org_id === member.org_id)
}

async function fetchMembers() {
  const requestId = ++membersRequestId
  const workspaceId = route.params.workspace_id
  loadingMembers.value = true
  try {
    const result = await getWorkspaceMembers(workspaceId)
    if (requestId === membersRequestId) members.value = result
  } catch (err) {
    if (requestId === membersRequestId) showToast('error', errorMessage(err))
  } finally {
    if (requestId === membersRequestId) loadingMembers.value = false
  }
}

async function fetchDirectory() {
  const requestId = ++directoryRequestId
  if (!canManageMembers.value || !addDialogVisible.value) return
  loadingDirectory.value = true
  try {
    const result = await getWorkspaceOrgs(route.params.workspace_id)
    if (requestId === directoryRequestId) {
      orgs.value = result
      await syncSelectionTree()
    }
  } catch (err) {
    if (requestId === directoryRequestId) showToast('error', errorMessage(err))
  } finally {
    if (requestId === directoryRequestId) loadingDirectory.value = false
  }
}

async function fetchUsers() {
  clearTimeout(userSearchTimer)
  const requestId = ++usersRequestId
  if (!canManageMembers.value || !addDialogVisible.value) return
  users.value = []
  loadingUsers.value = true
  try {
    const result = await getWorkspaceUsers(route.params.workspace_id, {
      page: usersPage.value,
      page_size: usersPageSize.value,
      query: userSearch.value.trim(),
      org_id: selectedOrgId.value ?? undefined,
    })
    if (requestId !== usersRequestId) return
    users.value = result.users
    usersTotal.value = result.total
    usersPage.value = result.page
    usersPageSize.value = result.page_size
  } catch (err) {
    if (requestId === usersRequestId) showToast('error', errorMessage(err))
  } finally {
    if (requestId === usersRequestId) loadingUsers.value = false
  }
}

function changeUsersPage(page) {
  usersPage.value = page
  fetchUsers()
}

function openAddDialog(type) {
  if (!canManageMembers.value || adding.value) return
  selectedMembers.value = []
  memberType.value = type
  selectedOrgId.value = null
  selectedRoles.value = { user: 'editor', org: 'editor' }
  orgSearch.value = ''
  userSearch.value = ''
  orgs.value = []
  users.value = []
  usersPage.value = 1
  usersPageSize.value = 20
  usersTotal.value = 0
  addDialogVisible.value = true
  fetchDirectory()
  if (type === 'user') fetchUsers()
}

function selectOrg(orgId) {
  if (adding.value) return
  selectedOrgId.value = orgId
  treeRef.value?.setCurrentKey(orgId === null ? null : `org:${orgId}`)
  usersPage.value = 1
  fetchUsers()
}

async function syncSelectionTree() {
  await nextTick()
  if (!addDialogVisible.value) return
  treeRef.value?.setCheckedKeys(selectedMembers.value.filter(member => member.type === 'org').map(member => `org:${member.id}`))
  treeRef.value?.setCurrentKey(selectedOrgId.value === null ? null : `org:${selectedOrgId.value}`)
  treeRef.value?.filter(orgSearch.value)
}

function filterDirectoryNode(value, data) {
  const query = value.trim().toLocaleLowerCase()
  return !query || String(data.name || '').toLocaleLowerCase().includes(query)
}

function handleDirectoryCheck(data, state) {
  if (adding.value) return
  selectedMembers.value = [
    ...selectedMembers.value.filter(member => member.type === 'user'),
    ...state.checkedNodes.filter(node => !node.disabled).map(({ type, id, name }) => ({ type, id, name })),
  ]
}

function isExistingMember(type, id) {
  return members.value.some(member => member.type === type && (type === 'org' ? member.org_id : member.user_id) === id)
}

function isSelected(type, id) {
  return selectedMembers.value.some(member => member.type === type && member.id === id)
}

function selectUser(user, checked) {
  if (adding.value || isExistingMember('user', user.id)) return
  if (checked && !isSelected('user', user.id)) {
    selectedMembers.value.push({ type: 'user', id: user.id, name: user.name })
  } else if (!checked) deselectMember({ type: 'user', id: user.id })
}

function deselectMember(member) {
  if (adding.value) return
  selectedMembers.value = selectedMembers.value.filter(item => item.type !== member.type || item.id !== member.id)
  if (member.type === 'org') syncSelectionTree()
}

async function addSelectedMembers() {
  if (!canManageMembers.value || !selectedMembers.value.length || adding.value || loadingDirectory.value || loadingMembers.value) return
  const workspaceId = route.params.workspace_id
  const sessionId = addSessionId
  const memberRoles = { ...selectedRoles.value }
  const selected = [...selectedMembers.value]
  adding.value = true
  let count = 0
  try {
    for (const member of selected) {
      if (route.params.workspace_id !== workspaceId || !canManageMembers.value || sessionId !== addSessionId) break
      await addWorkspaceMember(workspaceId, { type: member.type, id: member.id, role: memberRoles[member.type] })
      count++
      if (route.params.workspace_id !== workspaceId || sessionId !== addSessionId) break
      selectedMembers.value = selectedMembers.value.filter(item => item.type !== member.type || item.id !== member.id)
    }
    if (route.params.workspace_id !== workspaceId || sessionId !== addSessionId) return
    addDialogVisible.value = false
  } catch (err) {
    if (route.params.workspace_id === workspaceId) showToast('error', errorMessage(err))
  } finally {
    adding.value = false
    if (route.params.workspace_id === workspaceId) {
      if (count) showToast('success', t('members.usersAdded', { count }))
      await fetchMembers()
      if (sessionId === addSessionId) await syncSelectionTree()
    }
  }
}

function openEditDialog(member) {
  if (!canManageMembers.value) return
  editingMember.value = member
  editRole.value = member.role
  editDialogVisible.value = true
}

async function saveMember() {
  if (!canManageMembers.value || !editingMember.value || saving.value || removing.value) return
  const member = editingMember.value
  const role = editRole.value
  if (!roles.includes(role) || (member.type === 'org' && role === 'admin')) return
  const workspaceId = route.params.workspace_id
  saving.value = true
  try {
    await updateWorkspaceMember(workspaceId, member.id, member.type, role)
    if (route.params.workspace_id !== workspaceId) return
    editDialogVisible.value = false
    await refreshWorkspace?.()
    if (route.params.workspace_id === workspaceId) await fetchMembers()
  } catch (err) {
    if (route.params.workspace_id === workspaceId) showToast('error', errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function removeMember() {
  if (!canManageMembers.value || !editingMember.value || removing.value || saving.value) return
  const member = editingMember.value
  const workspaceId = route.params.workspace_id
  try {
    await confirmBox(t, t('members.removeConfirm', { name: member.name }), t('members.remove'), { type: 'warning' })
  } catch { return }
  if (route.params.workspace_id !== workspaceId || !canManageMembers.value) return
  removing.value = true
  try {
    await removeWorkspaceMember(workspaceId, member.id, member.type)
    if (route.params.workspace_id !== workspaceId) return
    editDialogVisible.value = false
    await refreshWorkspace?.()
    if (route.params.workspace_id === workspaceId) await fetchMembers()
  } catch (err) {
    if (route.params.workspace_id === workspaceId) showToast('error', errorMessage(err))
  } finally {
    removing.value = false
  }
}

async function previewOrg(member) {
  if (!canManageMembers.value || member.type !== 'org' || member.org_id == null) return
  previewMember.value = member
  previewUsers.value = []
  previewSearch.value = ''
  previewPage.value = 1
  previewPageSize.value = 20
  previewTotal.value = 0
  previewVisible.value = true
  fetchPreviewUsers()
}

async function fetchPreviewUsers() {
  clearTimeout(previewSearchTimer)
  const requestId = ++previewRequestId
  if (!canManageMembers.value || !previewVisible.value || previewMember.value?.org_id == null) return
  previewUsers.value = []
  loadingPreview.value = true
  try {
    const result = await getWorkspaceUsers(route.params.workspace_id, {
      org_id: previewMember.value.org_id,
      page: previewPage.value,
      page_size: previewPageSize.value,
      query: previewSearch.value.trim(),
    })
    if (requestId !== previewRequestId) return
    previewUsers.value = result.users
    previewTotal.value = result.total
    previewPage.value = result.page
    previewPageSize.value = result.page_size
  } catch (err) {
    if (requestId === previewRequestId) showToast('error', errorMessage(err))
  } finally {
    if (requestId === previewRequestId) loadingPreview.value = false
  }
}

function changePreviewPage(page) {
  previewPage.value = page
  fetchPreviewUsers()
}

function cancelAddRequests() {
  clearTimeout(userSearchTimer)
  directoryRequestId++
  usersRequestId++
  addSessionId++
  loadingDirectory.value = false
  loadingUsers.value = false
}

function cancelPreviewRequests() {
  clearTimeout(previewSearchTimer)
  previewRequestId++
  loadingPreview.value = false
}

function refresh() {
  fetchMembers()
}

onMounted(refresh)
watch(orgSearch, value => treeRef.value?.filter(value))
watch(userSearch, () => {
  clearTimeout(userSearchTimer)
  usersRequestId++
  users.value = []
  usersPage.value = 1
  usersTotal.value = 0
  if (!addDialogVisible.value || !canManageMembers.value) return
  loadingUsers.value = true
  userSearchTimer = setTimeout(fetchUsers, 300)
}, { flush: 'sync' })
watch(previewSearch, () => {
  clearTimeout(previewSearchTimer)
  previewRequestId++
  previewUsers.value = []
  previewPage.value = 1
  previewTotal.value = 0
  if (!previewVisible.value || !canManageMembers.value) return
  loadingPreview.value = true
  previewSearchTimer = setTimeout(fetchPreviewUsers, 300)
}, { flush: 'sync' })
watch(addDialogVisible, value => {
  if (!value) cancelAddRequests()
}, { flush: 'sync' })
watch(previewVisible, value => {
  if (!value) cancelPreviewRequests()
}, { flush: 'sync' })
watch(canManageMembers, value => {
  if (!value) {
    cancelAddRequests()
    cancelPreviewRequests()
    previewVisible.value = false
    previewUsers.value = []
    loadingPreview.value = false
    loadingDirectory.value = false
    orgs.value = []
    users.value = []
    selectedMembers.value = []
    addDialogVisible.value = false
    editDialogVisible.value = false
  }
}, { flush: 'sync' })
watch(() => [route.params.app_id, route.params.workspace_id], () => {
  membersRequestId++
  cancelAddRequests()
  cancelPreviewRequests()
  loadingDirectory.value = false
  loadingPreview.value = false
  members.value = []
  orgs.value = []
  users.value = []
  selectedMembers.value = []
  addDialogVisible.value = false
  editDialogVisible.value = false
  previewVisible.value = false
  refresh()
}, { flush: 'post' })
onBeforeUnmount(() => {
  membersRequestId++
  cancelAddRequests()
  cancelPreviewRequests()
})
</script>

<style scoped>
.members-toolbar { display: flex; justify-content: flex-end; margin-bottom: 16px; }
.access-section { max-width: 820px; }
.access-section + .access-section { margin-top: 28px; padding-top: 24px; border-top: 1px solid var(--el-border-color); }
.access-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.access-header h4 { margin: 0; font-size: 14px; font-weight: 650; }
.access-actions { display: flex; align-items: center; gap: 8px; }
.user-picker { margin-top: 10px; }
.member-picker.user-selection { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 20px; }
.org-pane, .users-pane { min-width: 0; }
.all-users { margin-top: 6px; }
.user-selection .organization-tree { height: 332px; }
.member-role-form { width: 200px; max-width: 100%; margin-top: 18px; }
.organization-tree { height: 364px; overflow: auto; margin-top: 10px; padding: 10px 8px; border: 1px solid var(--el-border-color); border-radius: 6px; }
.user-pagination { margin-top: 12px; max-width: 100%; overflow-x: auto; }
.preview-users { height: 320px; margin-top: 10px; }
.selected-members { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 18px; max-height: 140px; overflow: auto; }
.selected-members > span:first-child { width: 100%; font-size: 13px; color: var(--el-text-color-secondary); }
.selected-members .el-tag { max-width: 100%; height: auto; min-height: 26px; }
.selected-members :deep(.el-tag__content) { display: flex; align-items: center; gap: 4px; min-width: 0; white-space: normal; overflow-wrap: anywhere; }
.selected-members .el-icon { flex: none; }
.organization-tree :deep(.el-tree-node__content) { min-height: 34px; height: auto; }
.directory-hint { margin-bottom: 12px; color: var(--el-text-color-secondary); font-size: 13px; }
.member-name { max-width: 100%; height: auto; white-space: normal; overflow-wrap: anywhere; }
.directory-option { display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; }
.directory-option > span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.directory-option .el-icon { flex: none; color: var(--el-text-color-secondary); }
.directory-option small { flex: 0 1 auto; max-width: 45%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--el-text-color-secondary); font-size: 12px; }
@media (max-width: 650px) {
  .member-picker.user-selection { grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .user-selection .organization-tree { height: 180px; }
  .organization-tree { height: 320px; }
}
</style>
