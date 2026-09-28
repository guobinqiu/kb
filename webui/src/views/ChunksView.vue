<template>
  <section class="workspace-panel database-view">
    <SectionHeader :title="t('database.chunkList')" :description="route.query.filename">
      <template #actions><RefreshButton :loading="loading" @click="refresh" /></template>
    </SectionHeader>

    <section class="management-panel chunks-card">
      <div class="chunk-filter">
        <span>{{ t('database.fileIds') }}</span>
        <el-input v-model.trim="fileIdsText" :placeholder="t('database.fileIdsPlaceholder')" @keyup.enter="refresh" />
        <el-button :disabled="loading" @click="refresh">{{ t('common.search') }}</el-button>
      </div>
      <el-table
        v-if="chunks.length || loading"
        ref="chunksTableRef"
        :data="chunks"
        style="width: 100%"
        max-height="620"
        v-loading="loading"
        @scroll="onChunksScroll"
      >
        <el-table-column prop="id" :label="t('database.chunkId')" min-width="140" show-overflow-tooltip />
        <el-table-column :label="t('database.fileId')" min-width="170" show-overflow-tooltip>
          <template #default="{ row }"><span class="chunk-id">{{ row.file_id }}</span></template>
        </el-table-column>
        <el-table-column prop="filename" :label="t('database.filename')" min-width="140" show-overflow-tooltip />
        <el-table-column prop="s3_url" :label="t('database.s3Url')" min-width="240" show-overflow-tooltip />
        <el-table-column prop="chunk_index" :label="t('database.chunkIndex')" min-width="110" />
        <el-table-column :label="t('database.createdAt')" min-width="160">
          <template #default="{ row }">{{ shortTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('database.content')" min-width="320">
          <template #default="{ row }">
            <el-tooltip placement="top" popper-class="chunk-content-tooltip">
              <template #content><div class="chunk-content-tooltip-body">{{ row.content }}</div></template>
              <span class="chunk-content">{{ row.content }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else :description="t('database.vectorEmpty')" />
      <div v-if="loading && chunks.length" class="chunk-loading">{{ t('common.loading') }}</div>
    </section>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import RefreshButton from '../components/RefreshButton.vue'
import SectionHeader from '../components/SectionHeader.vue'
import { getChunks } from '../utils/kbApi'
import { parseFileIds, shortTime } from '../utils/format'
import { errorMessage, showToast } from '../utils/toast'

const { t } = useI18n()
const route = useRoute()
const chunks = ref([])
const fileIdsText = ref(String(route.query.file_ids || ''))
const cursor = ref(null)
const hasMore = ref(false)
const loading = ref(false)
const chunksTableRef = ref(null)
let requestId = 0

function clearChunks() {
  requestId++
  chunks.value = []
  cursor.value = null
  hasMore.value = false
  loading.value = false
}

async function fetchNext() {
  if (!route.params.workspace_id) return
  if (loading.value || !hasMore.value && chunks.value.length) return
  const currentRequest = ++requestId
  loading.value = true
  try {
    const result = await getChunks(route.params.workspace_id, {
      fileIds: parseFileIds(fileIdsText.value),
      cursor: cursor.value,
    })
    if (currentRequest !== requestId) return
    chunks.value = chunks.value.concat(result.chunks || [])
    cursor.value = result.next_cursor || null
    hasMore.value = Boolean(result.has_more)
  } catch (error) {
    if (currentRequest === requestId) showToast('error', errorMessage(error))
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}

function refresh() {
  clearChunks()
  fetchNext()
}

function onChunksScroll(event) {
  const wrap = chunksTableRef.value?.scrollBarRef?.wrapRef
  if (!wrap || !hasMore.value) return
  const scrollTop = event?.scrollTop ?? wrap.scrollTop
  if (scrollTop + wrap.clientHeight >= wrap.scrollHeight - 24) fetchNext()
}

onMounted(refresh)
onBeforeUnmount(clearChunks)
watch(() => route.params.workspace_id, refresh)
watch(() => route.query.file_ids, fileIds => {
  fileIdsText.value = String(fileIds || '')
  refresh()
})
</script>
