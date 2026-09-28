export function buildOrgTree(orgs) {
  const byId = new Map(orgs.map(org => [org.id, { ...org, children: [] }]))
  const roots = []
  for (const org of byId.values()) {
    const parent = byId.get(org.parent_id)
    if (parent) parent.children.push(org)
    else roots.push(org)
  }
  return roots
}

export function isOrgInactive(orgs, orgId) {
  const byId = new Map(orgs.map(org => [org.id, org]))
  for (let org = byId.get(orgId); org; org = byId.get(org.parent_id)) {
    if (org.deleted_at) return true
  }
  return false
}

export function descendantOrgs(orgs, rootId) {
  if (!rootId) return []
  const children = new Map()
  const byId = new Map(orgs.map(org => [org.id, org]))
  for (const org of orgs) {
    if (!children.has(org.parent_id)) children.set(org.parent_id, [])
    children.get(org.parent_id).push(org)
  }
  const result = []
  const pending = [rootId]
  const seen = new Set()
  while (pending.length) {
    const id = pending.pop()
    if (seen.has(id)) continue
    seen.add(id)
    const org = byId.get(id)
    if (org) result.push(org)
    for (const child of children.get(id) || []) pending.push(child.id)
  }
  return result
}
