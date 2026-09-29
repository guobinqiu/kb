<template>
  <div class="workspace-scope" v-loading="loading">
    <span class="scope-label">{{ t('workspaceScope.label') }}</span>
    <div v-if="workspaces.length" class="scope-options" role="group" :aria-label="t('workspaceScope.label')">
      <button
        v-for="workspace in workspaces"
        :key="workspace.id"
        type="button"
        class="scope-option"
        :class="{ selected: modelValue.includes(workspace.id) }"
        :aria-pressed="modelValue.includes(workspace.id)"
        :disabled="disabled || loading"
        @click="toggleWorkspace(workspace.id)"
      >
        {{ workspace.name }}
      </button>
    </div>
    <span v-else-if="!loading" class="scope-empty">{{ t('workspaceScope.empty') }}</span>
    <span v-if="workspaces.length && !modelValue.length" class="scope-empty">{{ t('workspaceScope.required') }}</span>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppsStore } from '../stores/apps'
import { errorMessage, showToast } from '../utils/toast'

const props = defineProps({
  appId: { type: String, default: '' },
  modelValue: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()
const appsStore = useAppsStore()
const workspaces = ref([])
const loading = ref(false)
let requestId = 0

function toggleWorkspace(id) {
  emit('update:modelValue', props.modelValue.includes(id)
    ? props.modelValue.filter(value => value !== id)
    : [...props.modelValue, id])
}

watch(() => props.appId, async appId => {
  const currentRequest = ++requestId
  workspaces.value = []
  emit('update:modelValue', [])
  loading.value = Boolean(appId)
  if (!appId) return
  try {
    const result = await appsStore.fetchWorkspaces(appId)
    if (currentRequest !== requestId) return
    workspaces.value = result
    emit('update:modelValue', result.map(workspace => workspace.id))
  } catch (err) {
    if (currentRequest === requestId) showToast('error', errorMessage(err))
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}, { immediate: true })

onBeforeUnmount(() => { requestId++ })
</script>

<style scoped>
.workspace-scope { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; min-height: 40px; }
.scope-label { font-size: 13px; color: var(--el-text-color-secondary); }
.scope-options { display: flex; flex-wrap: wrap; gap: 8px; min-width: 0; max-width: 100%; }
.scope-option { padding: 7px 12px; min-height: 32px; max-width: 100%; border: 1px solid var(--el-border-color); border-radius: 4px; background: var(--el-bg-color); color: var(--el-text-color-regular); font: inherit; font-size: 13px; line-height: 1.5; overflow-wrap: anywhere; cursor: pointer; }
.scope-option:hover:not(:disabled) { border-color: var(--el-color-primary); }
.scope-option.selected { background: var(--el-color-primary); color: #fff; border-color: var(--el-color-primary); }
.scope-option:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.scope-option:disabled { opacity: 0.6; cursor: not-allowed; }
.scope-empty { font-size: 13px; color: var(--el-text-color-secondary); }
</style>
