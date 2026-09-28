import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import AppsView from '../views/AppsView.vue'
import WorkspaceView from '../views/WorkspaceView.vue'
import OrganizationsView from '../views/OrganizationsView.vue'
import UsersView from '../views/UsersView.vue'
import FilesView from '../views/FilesView.vue'
import ChunksView from '../views/ChunksView.vue'
import SearchView from '../views/SearchView.vue'
import LlmView from '../views/LlmView.vue'
import WorkspacesView from '../views/WorkspacesView.vue'
import WorkspaceShellView from '../views/WorkspaceShellView.vue'
import MembersView from '../views/MembersView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/apps', component: AppsView },
    {
      path: '/apps/:app_id',
      component: WorkspaceView,
      children: [
        { path: 'organizations', component: OrganizationsView },
        { path: 'users', component: UsersView },
        { path: 'workspaces', component: WorkspacesView },
        { path: 'search', component: SearchView },
        { path: 'llm', component: LlmView },
      ],
    },
    {
      path: '/apps/:app_id/workspaces/:workspace_id',
      component: WorkspaceShellView,
      redirect: to => `/apps/${to.params.app_id}/workspaces/${to.params.workspace_id}/files`,
      children: [
        { path: 'members', component: MembersView },
        { path: 'files', component: FilesView },
        { path: 'chunks', component: ChunksView },
      ],
    },
    { path: '/apps/:app_id/database', redirect: to => `/apps/${to.params.app_id}/workspaces` },
    { path: '/database', redirect: '/apps' },
    { path: '/upload', redirect: '/apps' },
    { path: '/llm', redirect: '/apps' },
    { path: '/', redirect: '/apps' },
    { path: '/:pathMatch(.*)*', redirect: '/apps' },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('rag_token')
  if (!token && !to.meta.public) return { path: '/login' }
  if (token && to.path === '/login') return { path: '/apps' }
})

export default router
