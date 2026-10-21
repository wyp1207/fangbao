import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/pages/Login.vue') },
    {
      path: '/',
      component: () => import('@/layouts/ConsoleLayout.vue'),
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'dashboard', name: 'dashboard', component: () => import('@/pages/Dashboard.vue') },
        { path: 'map', name: 'map', component: () => import('@/pages/MapPage.vue') },
        { path: 'tasks', name: 'tasks', component: () => import('@/pages/Tasks.vue') },
        { path: 'alarms', name: 'alarms', component: () => import('@/pages/Alarms.vue') },
        { path: 'history', name: 'history', component: () => import('@/pages/History.vue') },
        { path: 'settings', name: 'settings', component: () => import('@/pages/Settings.vue') },
        { path: 'users', name: 'users', component: () => import('@/pages/Users.vue') },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.fetchMe()
  if (to.name !== 'login' && !auth.isLoggedIn) return { name: 'login' }
  if (to.name === 'login' && auth.isLoggedIn) return { name: 'dashboard' }
  return true
})

export default router
