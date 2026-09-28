<template>
  <div class="dialog-actions">
    <slot />
    <el-button @click="$emit('cancel')">{{ t('common.cancel') }}</el-button>
    <el-button type="primary" :loading="loading" :disabled="disabled" @click="$emit('confirm')">
      {{ confirmLabel || t('common.confirm') }}
    </el-button>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

defineProps({ loading: Boolean, disabled: Boolean, confirmLabel: String })
defineEmits(['cancel', 'confirm'])
const { t } = useI18n()
</script>

<style scoped>
.dialog-actions { display: flex; justify-content: flex-end; align-items: center; gap: 8px; flex-wrap: wrap; }
.dialog-actions :deep(.el-button + .el-button) { margin-left: 0; }
</style>
