import { ElMessage } from 'element-plus'

export function showToast(type, text) {
  ElMessage({
    type,
    message: text,
    duration: 3000,
    showClose: type === 'error',
  })
}

export function indexErrorMessage(error) {
  if (error == null) return ''
  return typeof error === 'string' ? error : JSON.stringify(error, null, 2)
}

export function errorMessage(error, fallback = 'Request failed') {
  const data = error?.response?.data
  if (data != null) return indexErrorMessage(data)
  return error?.message || fallback
}
