<template>
  <main class="login-view">
    <el-form class="login-card" label-position="top" @submit.prevent="login">
      <div>
        <h2>{{ t('auth.title') }}</h2>
      </div>
      <el-form-item :label="t('auth.name')">
        <el-input v-model.trim="loginForm.name" autocomplete="username" />
      </el-form-item>
      <el-form-item :label="t('auth.password')">
        <el-input v-model="loginForm.password" type="password" show-password autocomplete="current-password" />
      </el-form-item>
      <el-button type="primary" class="login-submit" native-type="submit">{{ t('auth.login') }}</el-button>
      <div v-if="loginError" class="upload-feedback error">{{ loginError }}</div>
    </el-form>
  </main>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import axios from '../utils/api'
import { useAuthStore } from '../stores/auth'
import { errorMessage } from '../utils/toast'

const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const loginForm = ref({ name: 'admin', password: '' })
const loginError = ref('')

async function login() {
  loginError.value = ''
  try {
    const res = await axios.post('/api/v1/auth/login', {
      name: loginForm.value.name,
      password: loginForm.value.password,
    })
    authStore.setToken(res.data.access_token)
    await authStore.fetchCurrentUser()
    router.push('/apps')
  } catch (err) {
    loginError.value = errorMessage(err)
  }
}
</script>
