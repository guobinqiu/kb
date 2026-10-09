import { defineStore } from 'pinia'
import { ref } from 'vue'
import { errorMessage, showToast } from '../utils/toast'
import { useActiveAppStore } from './activeApp'
import { createApp as createKbApp, getApps, getWorkspaces, removeApp } from '../utils/kbApi'

export const useAppsStore = defineStore('apps', () => {
  const apps = ref([])
  const workspacesByApp = ref({})
  const workspacePermissionsByApp = ref({})
  const workspaceRequests = new Map()

  async function fetchApps() {
    try {
      apps.value = await getApps()
      const activeAppStore = useActiveAppStore()
      if (activeAppStore.appId && !apps.value.some(app => app.app_id === activeAppStore.appId)) {
        activeAppStore.appId = ''
        activeAppStore.databaseStatus = null
      }
    } catch (err) { showToast('error', errorMessage(err)) }
  }

  async function createApp(name, appId) {
    const created = await createKbApp(name, appId)
    await fetchApps()
    return created
  }

  async function fetchWorkspaces(appId) {
    const requestId = (workspaceRequests.get(appId) || 0) + 1
    workspaceRequests.set(appId, requestId)
    workspacePermissionsByApp.value[appId] = {}
    const result = await getWorkspaces(appId)
    if (workspaceRequests.get(appId) === requestId) {
      workspacesByApp.value[appId] = result.workspaces
      workspacePermissionsByApp.value[appId] = result.permissions
    }
    return result.workspaces
  }

  async function deleteApp(id) {
    await removeApp(id)
    delete workspacesByApp.value[id]
    delete workspacePermissionsByApp.value[id]
    await fetchApps()
  }

  return { apps, workspacesByApp, workspacePermissionsByApp, fetchApps, fetchWorkspaces, createApp, deleteApp }
})
