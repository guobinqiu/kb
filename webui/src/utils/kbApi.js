import axios from './api'

const API = '/api/v1'

function rows(data, key) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.[key])) return data[key]
  if (Array.isArray(data?.items)) return data.items
  return []
}

export async function getApps() {
  const response = await axios.get(`${API}/apps`)
  return rows(response.data, 'apps')
}

export async function createApp(name, appId) {
  const response = await axios.post(`${API}/apps`, { name, app_id: appId })
  return {
    app: response.data?.app,
    org: response.data?.org,
  }
}

export async function removeApp(id) {
  await axios.delete(`${API}/apps/${encodeURIComponent(id)}`)
}

export async function getOrgs(appId, includeDisabled = false) {
  const response = await axios.get(`${API}/orgs`, { params: { app_id: appId, include_disabled: includeDisabled } })
  return rows(response.data, 'orgs')
}

export async function createOrg(payload) {
  const response = await axios.post(`${API}/orgs`, payload)
  return response.data
}

export async function removeOrg(id) {
  await axios.delete(`${API}/orgs/${encodeURIComponent(id)}`)
}

export async function updateOrg(id, payload) {
  const response = await axios.put(`${API}/orgs/${encodeURIComponent(id)}`, payload)
  return response.data
}

export async function purgeOrg(id) {
  await axios.delete(`${API}/orgs/${encodeURIComponent(id)}/permanent`)
}

export async function getUsers(orgId, includeDisabled = false) {
  const params = { include_disabled: includeDisabled }
  if (orgId) params.org_id = orgId
  const response = await axios.get(`${API}/users`, { params })
  return rows(response.data, 'users')
}

export async function createUser(payload) {
  const response = await axios.post(`${API}/users`, payload)
  return response.data
}

export async function removeUser(id) {
  await axios.delete(`${API}/users/${encodeURIComponent(id)}`)
}

export async function updateUser(id, payload) {
  const response = await axios.put(`${API}/users/${encodeURIComponent(id)}`, payload)
  return response.data
}

export async function changePassword(oldPassword, newPassword) {
  const response = await axios.patch(`${API}/auth/password`, { old_password: oldPassword, new_password: newPassword })
  return response.data
}

export async function getWorkspaces(appId) {
  const response = await axios.get(`${API}/apps/${encodeURIComponent(appId)}/workspaces`)
  return response.data
}

export async function getWorkspace(workspaceId) {
  const response = await axios.get(`${API}/workspaces/${encodeURIComponent(workspaceId)}`)
  return response.data
}

export async function createWorkspace(appId, name) {
  const response = await axios.post(`${API}/apps/${encodeURIComponent(appId)}/workspaces`, { name })
  return response.data.workspace
}

export async function removeWorkspace(workspaceId) {
  await axios.delete(`${API}/workspaces/${encodeURIComponent(workspaceId)}`)
}

export async function getWorkspaceMembers(workspaceId) {
  const response = await axios.get(`${API}/workspaces/${encodeURIComponent(workspaceId)}/members`)
  return response.data.members
}

export async function getWorkspaceOrgs(workspaceId) {
  const response = await axios.get(`${API}/workspaces/${encodeURIComponent(workspaceId)}/orgs`)
  return response.data.orgs
}

export async function getWorkspaceUsers(workspaceId, { org_id, page = 1, page_size = 20, query = '' } = {}) {
  const params = { page, page_size, query }
  if (org_id != null) params.org_id = org_id
  const response = await axios.get(`${API}/workspaces/${encodeURIComponent(workspaceId)}/users`, { params })
  return response.data
}

export async function addWorkspaceMember(workspaceId, { type, id, role }) {
  const response = await axios.post(`${API}/workspaces/${encodeURIComponent(workspaceId)}/members`, { type, id, role })
  return response.data.member
}

export async function updateWorkspaceMember(workspaceId, membershipId, type, role) {
  const response = await axios.put(`${API}/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(membershipId)}`, { role }, { params: { type } })
  return response.data.member
}

export async function removeWorkspaceMember(workspaceId, membershipId, type) {
  await axios.delete(`${API}/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(membershipId)}`, { params: { type } })
}

export async function getFiles(workspaceId) {
  const response = await axios.get(`${API}/workspaces/${encodeURIComponent(workspaceId)}/files`)
  return {
    files: rows(response.data, 'files'),
    total: response.data?.total,
  }
}

export async function getFile(workspaceId, fileId) {
  const response = await axios.get(`${API}/workspaces/${encodeURIComponent(workspaceId)}/files/${encodeURIComponent(fileId)}`)
  return response.data.file || response.data
}

export async function getChunks(workspaceId, { fileIds = [], limit = 50, cursor = null } = {}) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor) params.set('cursor', cursor)
  fileIds.forEach(fileId => params.append('file_ids', fileId))
  const response = await axios.get(`${API}/workspaces/${encodeURIComponent(workspaceId)}/chunks?${params}`)
  return response.data
}

async function uploadDirect(workspaceId, file, fileId) {
  const base = `${API}/workspaces/${encodeURIComponent(workspaceId)}/files`
  const prepared = await axios.post(`${base}/upload-url`, {
    ...(fileId ? { file_id: fileId } : {}),
    filename: file.name,
    content_type: file.type || 'application/octet-stream',
  })
  const upload = prepared.data
  const result = await fetch(upload.upload_url, {
    method: 'PUT',
    headers: { 'Content-Type': upload.content_type },
    body: file,
  })
  if (!result.ok) {
    const detail = await result.text()
    throw new Error(`MinIO upload failed (${result.status}): ${detail || result.statusText}`)
  }
  const completed = await axios.post(`${base}/${encodeURIComponent(upload.file_id)}/complete`, {
    object_key: upload.object_key,
    filename: upload.filename,
    content_type: upload.content_type,
  })
  return completed.data
}

export async function uploadFile(file, workspaceId) {
  return uploadDirect(workspaceId, file)
}

export async function replaceFile(workspaceId, id, file) {
  return uploadDirect(workspaceId, file, id)
}

export async function removeFile(workspaceId, id) {
  await axios.delete(`${API}/workspaces/${encodeURIComponent(workspaceId)}/files/${encodeURIComponent(id)}`)
}
