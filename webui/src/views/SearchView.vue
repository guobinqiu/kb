<template>
  <section class="workspace-panel search-view">
    <p class="search-scope">{{ t('search.accessibleWorkspaces') }}</p>
    <!-- Search Section -->
    <div class="search-section">
      <div class="search-row-1">
        <el-radio-group v-model="mode">
          <el-radio-button value="hybrid" :disabled="!sparseAvailable">{{ t('search.modeValues.hybrid') }}</el-radio-button>
          <el-radio-button value="dense">{{ t('search.modeValues.dense') }}</el-radio-button>
          <el-radio-button value="sparse" :disabled="!sparseAvailable">{{ t('search.modeValues.sparse') }}</el-radio-button>
        </el-radio-group>
      </div>
      <div class="search-row-3">
        <div class="scope-controls">
          <span class="scope-title">File IDs</span>
          <el-input v-model.trim="fileIdsText" :placeholder="t('search.fileIdsPlaceholder')" class="scopes" />
        </div>
      </div>
      <div class="search-row-3">
        <div class="topk-control">
          <span class="topk-label">{{ t('search.topK') }}</span>
          <el-select v-model="topK" style="width: 110px">
            <el-option :value="3" label="3" />
            <el-option :value="5" label="5" />
            <el-option :value="10" label="10" />
            <el-option :value="20" label="20" />
          </el-select>
        </div>
      </div>
      <div class="search-row-3">
        <el-checkbox v-if="rerankVisible" v-model="rerank" class="rerank-control">{{ t('search.rerank') }}</el-checkbox>
        <div v-if="rerankVisible && rerank" class="fetchk-control">
          <span class="cand-label" :title="t('search.rerankFetchKTitle')">{{ t('search.rerankFetchK') }}</span>
          <el-input-number v-model="rerankFetchK" :min="topK" :max="100" :title="t('search.rerankFetchKTitle')" style="width: 120px" />
        </div>
      </div>
      <div class="search-row-2">
        <div class="search-input-wrap">
          <el-input v-model="query" :placeholder="t('search.placeholder')" @keyup.enter="doSearch" />
          <el-button type="primary" :disabled="!query.trim() || searching" :loading="searching" @click="doSearch">{{ searching ? t('search.searching') : t('search.submit') }}</el-button>
        </div>
      </div>
    </div>

    <!-- Results -->
    <div v-if="resultCount > 0" class="results-section">
      <div class="results-bar">
        <span class="results-count">{{ t('search.resultCount', { count: resultCount }) }}</span>
        <span class="results-mode">{{ t('search.mode') }}: {{ t(`search.modeValues.${lastSearch?.mode || 'dense'}`) }}</span>
        <span class="results-mode">{{ t('search.accessibleWorkspaces') }}</span>
        <span class="results-mode">{{ t('search.files') }}: {{ lastSearch?.fileIds?.length ? lastSearch.fileIds.length : t('common.all') }}</span>
        <span v-if="searchTime !== null" class="results-elapsed">{{ t('search.elapsed') }}: {{ searchTime }}ms</span>
      </div>
      <div v-for="workspace in workspaceGroups" :key="workspace.id" class="workspace-results">
        <h4>{{ workspace.name }}</h4>
        <div v-for="(r, i) in workspace.results" :key="r.id || i" class="result-card">
          <div class="result-head">
            <div class="result-file">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              <span>{{ r.metadata?.filename || t('search.unknownFile') }}</span>
            </div>
            <span v-if="typeof r.score === 'number'" class="result-score">{{ t('search.score') }}: {{ formatScore(r.score) }}</span>
          </div>
          <p class="result-body" v-html="escapeHtml(r.content)"></p>
        </div>
      </div>
    </div>
    <div v-if="noResults" class="no-results">
      <p>{{ t('search.noResults') }}</p>
      <p class="no-results-hint">{{ t('search.noResultsHint') }}</p>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import axios from '../utils/api'
import { useAppsStore } from '../stores/apps'
import { parseFileIds, escapeHtml } from '../utils/format'
import { errorMessage, showToast } from '../utils/toast'

const API = '/api/v1'
const { t } = useI18n()
const route = useRoute()
const appsStore = useAppsStore()

const query = ref('')
const mode = ref('dense')
const topK = ref(5)
const rerank = ref(false)
const rerankVisible = ref(false)
const rerankFetchK = ref(20)
const sparseAvailable = ref(false)
const fileIdsText = ref('')
const workspaceGroups = ref([])
const resultCount = computed(() => workspaceGroups.value.reduce((count, workspace) => count + workspace.results.length, 0))
const searchTime = ref(null)
const lastSearch = ref(null)
const searching = ref(false)
const noResults = ref(false)
let searchRequestId = 0

function searchFileIds() {
  return parseFileIds(fileIdsText.value)
}

function formatScore(score) {
  return Number(score).toFixed(4)
}

async function doSearch() {
  if (!query.value.trim()) return
  if (searching.value) return
  const currentRequest = ++searchRequestId
  if (rerankVisible.value && rerank.value && rerankFetchK.value < topK.value) rerankFetchK.value = topK.value
  searching.value = true
  noResults.value = false
  workspaceGroups.value = []
  searchTime.value = null
  try {
    if (!appsStore.apps.length) await appsStore.fetchApps()
    const app = appsStore.apps.find(item => item.id === route.params.app_id)
    if (!app) throw new Error('App not found')
    const fileIds = searchFileIds()
    const body = {
      query: query.value,
      mode: mode.value,
      top_k: topK.value,
      rerank: rerankVisible.value && rerank.value,
    }
    if (fileIds.length) body.file_ids = fileIds
    if (rerankVisible.value && rerank.value) body.rerank_fetch_k = rerankFetchK.value
    const workspaces = await appsStore.fetchWorkspaces(app.id)
    const res = workspaces.length
      ? await axios.post(`${API}/rag/search`, body, { headers: { 'X-App-Id': app.app_id } })
      : { data: { results: [], elapsed_ms: 0 } }
    if (currentRequest !== searchRequestId) return
    const workspaceNames = new Map(workspaces.map(workspace => [workspace.id, workspace.name]))
    const grouped = new Map()
    for (const result of res.data.results || []) {
      const workspaceId = result.metadata?.workspace_id || ''
      if (!grouped.has(workspaceId)) grouped.set(workspaceId, { id: workspaceId, name: workspaceNames.get(workspaceId) || workspaceId || t('search.unknownWorkspace'), results: [] })
      grouped.get(workspaceId).results.push(result)
    }
    workspaceGroups.value = [...grouped.values()]
    searchTime.value = res.data.elapsed_ms
    lastSearch.value = {
      query: query.value,
      mode: mode.value,
      topK: topK.value,
      rerank: rerankVisible.value && rerank.value,
      rerankFetchK: rerankVisible.value && rerank.value ? rerankFetchK.value : null,
      fileIds,
    }
    noResults.value = resultCount.value === 0
  } catch (err) {
    if (currentRequest === searchRequestId) showToast('error', errorMessage(err, 'Search failed'))
  }
  if (currentRequest === searchRequestId) searching.value = false
}

async function fetchConfig() {
  try {
    const res = await axios.get(`${API}/rag/config`)
    sparseAvailable.value = Boolean(res.data.capabilities?.sparse_vector)
    mode.value = res.data.mode || mode.value
    topK.value = res.data.top_k ?? topK.value
    rerankVisible.value = Boolean(res.data.rerank)
    rerank.value = Boolean(res.data.rerank)
    rerankFetchK.value = res.data.rerank_fetch_k ?? rerankFetchK.value
  } catch (err) { showToast('error', errorMessage(err)) }
}

onMounted(fetchConfig)
</script>

<style scoped>
.search-scope { margin-bottom: 20px; font-size: 13px; color: var(--el-text-color-secondary); }
.workspace-results + .workspace-results { border-top: 1px solid var(--el-border-color); }
.workspace-results h4 { padding: 16px 0 4px; font-size: 14px; font-weight: 650; }
</style>
