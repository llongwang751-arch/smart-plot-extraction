/** 轻量状态：无 Pinia，用 reactive + localStorage 直接持久化登录态。 */
import { reactive } from 'vue'

const KEY = 'plot_web_auth'

function read() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '{}')
  } catch (e) {
    return {}
  }
}

const saved = read()

export const state = reactive({
  token: saved.token || '',
  user: saved.user || null
})

export function getToken() {
  return state.token
}

export function setAuth(token, user) {
  state.token = token || ''
  state.user = user || null
  localStorage.setItem(KEY, JSON.stringify({ token: state.token, user: state.user }))
}

export function setUser(user) {
  state.user = user
  localStorage.setItem(KEY, JSON.stringify({ token: state.token, user: state.user }))
}

export function clearAuth() {
  state.token = ''
  state.user = null
  localStorage.removeItem(KEY)
}

export function isAdmin() {
  return state.user?.role === 'admin'
}

export function displayName() {
  return state.user?.nickname || state.user?.username || '未登录'
}
