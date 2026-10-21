import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/pages/Login.vue') },
    // 驾驶舱是整屏大屏，独立于后台布局，避免叠两层顶栏
    { path: '/dashboard', name: 'dashboard', component: () => import('@/pages/Dashboard.vue') },
    {
      path: '/',
      component: () => import('@/layouts/ConsoleLayout.vue'),
      children: [
        { path: '', redirect: '/robot-status' },
        // 实时监控
        { path: 'robot-status', name: 'robot-status', component: () => import('@/pages/RobotStatus.vue') },
        { path: 'map', name: 'map', component: () => import('@/pages/MapPage.vue') },
        { path: 'video', name: 'video', component: () => import('@/pages/VideoLive.vue') },
        { path: 'room', name: 'room', component: () => import('@/pages/VideoLive.vue'), props: { group: '充电房' } },
        { path: 'env', name: 'env', component: () => import('@/pages/PlaceholderPage.vue') },

        // 巡检管理
        { path: 'tasks', name: 'tasks', component: () => import('@/pages/Tasks.vue') },
        { path: 'points', name: 'points', component: () => import('@/pages/Points.vue') },
        { path: 'task-calendar', name: 'task-calendar', component: () => import('@/pages/PlaceholderPage.vue') },

        // 告警中心
        { path: 'alarms', name: 'alarms', component: () => import('@/pages/Alarms.vue') },
        { path: 'alarm-rules', name: 'alarm-rules', component: () => import('@/pages/AlarmRules.vue') },

        // 数据查询
        { path: 'history', redirect: '/history/tasks' },
        { path: 'history/tasks', name: 'history-tasks', component: () => import('@/pages/History.vue'), meta: { tab: 'tasks' } },
        { path: 'history/alarms', name: 'history-alarms', component: () => import('@/pages/History.vue'), meta: { tab: 'alarms' } },
        { path: 'run-data', name: 'run-data', component: () => import('@/pages/PlaceholderPage.vue') },

        // 设备管理
        { path: 'robots', name: 'robots', component: () => import('@/pages/RobotProfile.vue') },
        { path: 'cameras', name: 'cameras', component: () => import('@/pages/Cameras.vue') },
        { path: 'env-device', name: 'env-device', component: () => import('@/pages/PlaceholderPage.vue') },

        // 录像管理
        { path: 'record/plan', name: 'record-plan', component: () => import('@/pages/PlaceholderPage.vue') },
        { path: 'record/playback', name: 'record-playback', component: () => import('@/pages/PlaceholderPage.vue') },

        // 系统管理
        { path: 'users', name: 'users', component: () => import('@/pages/Users.vue') },
        { path: 'settings', name: 'settings', component: () => import('@/pages/Settings.vue') },
        { path: 'oplog', name: 'oplog', component: () => import('@/pages/PlaceholderPage.vue') },
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
