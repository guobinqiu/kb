import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'

export const useAuthStore = defineStore('auth', () => {
  const authToken = ref(localStorage.getItem('rag_token') || '')
  const currentUser = ref(null)
  let currentUserRequest = null

  function setToken(token) {
    authToken.value = token
    localStorage.setItem('rag_token', token)
    applyAuthHeader()
  }

  function applyAuthHeader() {
    if (authToken.value) axios.defaults.headers.common.Authorization = `Bearer ${authToken.value}`
    else delete axios.defaults.headers.common.Authorization
  }

  function clearAuth() {
    authToken.value = ''
    currentUser.value = null
    localStorage.removeItem('rag_token')
    delete axios.defaults.headers.common.Authorization
  }

  async function fetchCurrentUser() {
    if (!currentUserRequest) {
      currentUserRequest = axios.get('/api/v1/auth/me')
        .then(response => {
          currentUser.value = response.data?.user || response.data
          applyAuthHeader()
          return currentUser.value
        })
        .finally(() => { currentUserRequest = null })
    }
    return currentUserRequest
  }

  if (authToken.value) applyAuthHeader()

  return { authToken, currentUser, setToken, applyAuthHeader, clearAuth, fetchCurrentUser }
})
