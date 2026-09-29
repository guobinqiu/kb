<template>
  <main class="platform-accounts-view">
    <UsersView platform-accounts />
  </main>
</template>

<script setup>
import UsersView from './UsersView.vue'
</script>

<style scoped>
.platform-accounts-view { padding: 24px; }
@media (max-width: 650px) { .platform-accounts-view { padding: 16px; } }
</style>
