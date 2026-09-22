import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken, isAdmin } from '@/store'

export const MENU = [
  { path: '/home', name: '系统首页', icon: '🏠' },
  { path: '/extract', name: '地图提取', icon: '🗺️' },
  { path: '/chat', name: '智能问答', icon: '💬' },
  { path: '/records', name: '提取记录', icon: '📑' },
  { path: '/plots', name: '地块管理', icon: '📐' },
  { path: '/knowledge', name: '知识库', icon: '📚' },
  { path: '/settings', name: '系统配置', icon: '⚙️', admin: true },
  { path: '/users', name: '用户管理', icon: '👥', admin: true }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: () => import('@/views/Login.vue'), meta: { public: true, title: '登录' } },
    {
      path: '/',
      component: () => import('@/views/Layout.vue'),
      children: [
        { path: '', redirect: '/home' },
        { path: 'home', component: () => import('@/views/Home.vue'), meta: { title: '系统首页' } },
        { path: 'extract', component: () => import('@/views/Extract.vue'), meta: { title: '地图提取' } },
        { path: 'chat', component: () => import('@/views/Chat.vue'), meta: { title: '智能问答' } },
        { path: 'records', component: () => import('@/views/Records.vue'), meta: { title: '提取记录' } },
        { path: 'plots', component: () => import('@/views/Plots.vue'), meta: { title: '地块管理' } },
        { path: 'knowledge', component: () => import('@/views/Knowledge.vue'), meta: { title: '知识库' } },
        { path: 'settings', component: () => import('@/views/Settings.vue'), meta: { title: '系统配置', admin: true } },
        { path: 'users', component: () => import('@/views/Users.vue'), meta: { title: '用户管理', admin: true } }
      ]
    },
    { path: '/:pathMatch(.*)*', redirect: '/home' }
  ]
})

// 权限不只做在菜单上：直达 URL 也要挡住（后端接口另有强制校验）
router.beforeEach((to) => {
  if (to.meta?.public) return true
  if (!getToken()) return { path: '/login', query: { next: to.fullPath } }
  if (to.meta?.admin && !isAdmin()) return { path: '/home' }
  return true
})

export default router
