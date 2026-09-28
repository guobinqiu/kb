<template>
  <div class="preference-controls">
    <el-dropdown trigger="click" @command="setLang">
      <el-button class="preference-button" text :icon="Compass" :aria-label="t('language.title')" :title="t('language.title')" />
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="zh">
            <span class="language-label">简体中文</span>
            <el-icon v-if="locale === 'zh'"><Check /></el-icon>
          </el-dropdown-item>
          <el-dropdown-item command="en">
            <span class="language-label">English</span>
            <el-icon v-if="locale === 'en'"><Check /></el-icon>
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
    <el-tooltip :content="themeLabel" placement="bottom">
      <el-button class="preference-button" text :icon="theme === 'light' ? Moon : Sunny" :aria-label="themeLabel" @click="toggleTheme" />
    </el-tooltip>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { Check, Compass, Moon, Sunny } from '@element-plus/icons-vue'
import { useThemeStore } from '../stores/theme'

const { t, locale } = useI18n()
const themeStore = useThemeStore()
const { theme } = storeToRefs(themeStore)
const themeLabel = computed(() => t(theme.value === 'light' ? 'theme.switchToDark' : 'theme.switchToLight'))

function setLang(value) {
  locale.value = value
  localStorage.setItem('rag_lang', value)
}

function toggleTheme() {
  themeStore.setTheme(theme.value === 'light' ? 'dark' : 'light')
}
</script>

<style scoped>
.preference-controls { display: flex; align-items: center; gap: 4px; }
.preference-button { width: 34px; height: 34px; padding: 0; border-radius: 6px; font-size: 17px; }
.language-label { display: inline-block; min-width: 94px; }
</style>
