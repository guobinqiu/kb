<template>
  <div class="section-header">
    <div class="section-header-content">
      <slot>
        <h3 v-if="title">{{ title }}</h3>
        <p v-if="description">{{ description }}</p>
      </slot>
    </div>
    <div v-if="$slots.actions" class="section-header-actions"><slot name="actions" /></div>
  </div>
</template>

<script setup>
defineProps({ title: String, description: String })
</script>

<style scoped>
.section-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.section-header-content { min-width: 0; }
.section-header-content h3 { font-size: 16px; font-weight: 650; }
.section-header-content p { margin-top: 5px; font-size: 13px; color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
.section-header-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; flex-wrap: wrap; }
.section-header-actions :deep(.el-button + .el-button) { margin-left: 0; }
@media (max-width: 650px) {
  .section-header { align-items: flex-start; flex-wrap: wrap; }
  .section-header-actions { max-width: 100%; }
}
</style>
