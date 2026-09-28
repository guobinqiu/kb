<template>
  <el-tooltip :content="t('common.refresh')" placement="top">
    <el-button
      class="refresh-button"
      text
      :icon="Refresh"
      :loading="loading"
      :disabled="disabled || loading"
      :aria-label="t('common.refresh')"
      :aria-busy="loading"
      @click="$emit('click', $event)"
    >{{ t('common.refresh') }}</el-button>
  </el-tooltip>
</template>

<script setup>
import { Refresh } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

defineProps({ loading: Boolean, disabled: Boolean })
defineEmits(['click'])
const { t } = useI18n()
</script>

<style scoped>
.refresh-button { width: 96px; height: 32px; flex-shrink: 0; }
</style>
