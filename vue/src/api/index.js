/** 统一请求层：自动带登录凭证、401 跳登录、180 秒超时（适配长耗时提取任务）。 */
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { clearAuth, getToken } from '@/store'

const http = axios.create({ baseURL: '/api', timeout: 180000 })

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const status = err.response?.status
    const detail = err.response?.data?.detail || err.message || '请求失败'
    if (status === 401) {
      clearAuth()
      if (!location.hash.startsWith('#/login')) {
        ElMessage.warning('登录状态已失效，请重新登录')
        location.hash = '#/login'
      }
    } else if (!(err.config || {}).silent) {
      ElMessage.error(String(detail).slice(0, 240))
    }
    return Promise.reject(new Error(typeof detail === 'string' ? detail : JSON.stringify(detail)))
  }
)

export default http

/** 瓦片走 <img> 加载，带不了请求头，所以凭证拼在查询串里。 */
export function tileUrl(template) {
  const token = getToken()
  if (!template) return ''
  return token ? `${template}${template.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}` : template
}

export const api = {
  // 账号
  login: (data) => http.post('/auth/login', data),
  register: (data) => http.post('/auth/register', data),
  me: () => http.get('/auth/me'),
  profile: (data) => http.put('/auth/profile', data),
  password: (data) => http.post('/auth/password', data),

  // 用户管理
  users: (params) => http.get('/users', { params }),
  createUser: (data) => http.post('/users', data),
  updateUser: (id, data) => http.put(`/users/${id}`, data),
  deleteUser: (id) => http.delete(`/users/${id}`),

  // 概览
  dashboard: () => http.get('/dashboard'),
  health: () => http.get('/health'),

  // 配置
  configSchema: () => http.get('/config/schema'),
  saveConfig: (values) => http.put('/config', { values }),
  configStatus: () => http.get('/config/status'),
  testConfig: (target) => http.post('/config/test', { target }),

  // 地块
  plots: (params) => http.get('/plots', { params }),
  plot: (id) => http.get(`/plots/${id}`),
  plotOptions: () => http.get('/plots/options'),
  plotGeojson: (params) => http.get('/plots/geojson', { params }),
  createPlot: (data) => http.post('/plots', data),
  updatePlot: (id, data) => http.put(`/plots/${id}`, data),
  deletePlot: (id) => http.delete(`/plots/${id}`),
  samplePlots: (data) => http.post('/plots/sample', data),

  // 提取
  extractContext: () => http.get('/extract/context'),
  runExtract: (data) => http.post('/extract/run', data),
  savePlots: (data) => http.post('/extract/save-plots', data),

  // 记录
  records: (params) => http.get('/records', { params }),
  record: (id) => http.get(`/records/${id}`),
  saveRecordPlots: (id, region = '') => http.post(`/records/${id}/save-plots`, null, { params: { region } }),
  deleteRecord: (id) => http.delete(`/records/${id}`),
  geojsonUrl: (id) => `/api/extract/geojson/${id}`,

  // 知识库
  kbDocs: (params) => http.get('/knowledge/docs', { params }),
  kbStatus: () => http.get('/knowledge/status'),
  kbText: (data) => http.post('/knowledge/text', data),
  kbUpload: (form) => http.post('/knowledge/upload', form),
  kbDelete: (id) => http.delete(`/knowledge/docs/${id}`),
  kbSearch: (data) => http.post('/knowledge/search', data),

  // 问答
  sessions: () => http.get('/chat/sessions'),
  createSession: () => http.post('/chat/sessions'),
  renameSession: (id, title) => http.put(`/chat/sessions/${id}`, { title }),
  deleteSession: (id) => http.delete(`/chat/sessions/${id}`),
  messages: (id) => http.get(`/chat/sessions/${id}/messages`),
  ask: (data) => http.post('/chat/ask', data),

  // 地图
  basemaps: () => http.get('/maps/basemaps'),
  checkTiles: () => http.post('/maps/check'),
  tileError: (params) => http.get('/maps/last-error', { params })
}
