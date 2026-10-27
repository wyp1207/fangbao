import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/pages/Login.vue') },
  { path: '/m/task/:id', name: 'mobile-check', component: () => import('@/pages/MobileCheck.vue') },
  { path: '/m/wo/:id', name: 'mobile-wo', component: () => import('@/pages/MobileWorkOrder.vue') },
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
        { path: 'env', name: 'env', component: () => import('@/pages/EnvMonitor.vue') },

        // 巡检管理
        { path: 'tasks', name: 'tasks', component: () => import('@/pages/Tasks.vue') },
        { path: 'inspection', name: 'inspection', component: () => import('@/pages/Inspection.vue') },
        { path: 'work-orders', name: 'work-orders', component: () => import('@/pages/WorkOrders.vue') },
        { path: 'task-runs', name: 'task-runs', component: () => import('@/pages/TaskRuns.vue') },
        { path: 'task-templates', name: 'task-templates', component: () => import('@/pages/TaskTemplates.vue') },
        { path: 'points', name: 'points', component: () => import('@/pages/Points.vue') },
        { path: 'task-calendar', name: 'task-calendar', component: () => import('@/pages/PlaceholderPage.vue') },

        // 告警中心
        { path: 'alarms', name: 'alarms', component: () => import('@/pages/Alarms.vue') },
        { path: 'ai-results', name: 'ai-results', component: () => import('@/pages/AiResults.vue') },
        { path: 'keys', name: 'api-keys', component: () => import('@/pages/ApiKeys.vue'), meta: { roles: ['admin', 'sysadmin'] } },
        { path: 'alarm-rules', name: 'alarm-rules', component: () => import('@/pages/AlarmRules.vue') },

        // 数据查询
        { path: 'history', redirect: '/history/tasks' },
        { path: 'history/tasks', name: 'history-tasks', component: () => import('@/pages/History.vue'), meta: { tab: 'tasks' } },
        { path: 'history/alarms', name: 'history-alarms', component: () => import('@/pages/History.vue'), meta: { tab: 'alarms' } },
        { path: 'reports/print', name: 'report-print', component: () => import('@/pages/ReportPrint.vue') },
        { path: 'reports', name: 'reports', component: () => import('@/pages/Reports.vue') },
        { path: 'run-data', name: 'run-data', component: () => import('@/pages/RunData.vue') },

        // 设备管理
        { path: 'robots', name: 'robots', component: () => import('@/pages/RobotProfile.vue') },
        { path: 'peripherals', name: 'peripherals', component: () => import('@/pages/Peripherals.vue'), meta: { roles: ['admin', 'sysadmin', 'operator'] } },
        { path: 'peripherals', name: 'peripherals', component: () => import('@/pages/Peripherals.vue'), meta: { roles: ['admin', 'sysadmin', 'operator'] } },
        { path: 'cameras', name: 'cameras', component: () => import('@/pages/Cameras.vue') },
        { path: 'sensor-gateways', name: 'sensor-gateways', component: () => import('@/pages/SensorGateways.vue') },
        { path: 'env-device', name: 'env-device', component: () => import('@/pages/EnvDevices.vue') },

        // 录像管理
        { path: 'record/plan', name: 'record-plan', component: () => import('@/pages/RecordPlan.vue') },
        { path: 'record/playback', name: 'record-playback', component: () => import('@/pages/RecordPlayback.vue') },

        // 系统管理
        { path: 'messages', name: 'messages', component: () => import('@/pages/Messages.vue') },
        { path: 'users', name: 'users', component: () => import('@/pages/Users.vue'), meta: { roles: ['admin', 'sysadmin'] } },
        { path: 'system-status', name: 'system-status', component: () => import('@/pages/SystemStatus.vue'), meta: { roles: ['admin', 'sysadmin'] } },
        { path: 'settings', name: 'settings', component: () => import('@/pages/Settings.vue'), meta: { roles: ['admin', 'sysadmin', 'secadmin'] } },
        { path: 'notify', name: 'notify', component: () => import('@/pages/NotifyChannels.vue'), meta: { roles: ['admin', 'sysadmin', 'secadmin'] } },
        { path: 'oplog', name: 'oplog', component: () => import('@/pages/AuditLogs.vue'), meta: { roles: ['admin', 'auditor'] } },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  const wasLoggedIn = auth.isLoggedIn
  await auth.fetchMe()
  if (to.name !== 'login' && !auth.isLoggedIn) {
    // 之前登录过又掉线 = 会话过期，登录页要清空账号密码并提示
    let signedBefore = false
    try { signedBefore = sessionStorage.getItem('jc_signed_in') === '1' } catch { /* ignore */ }
    const expired = wasLoggedIn || signedBefore ? '1' : ''
    if (signedBefore) {
      try { sessionStorage.removeItem('jc_signed_in') } catch { /* ignore */ }
    }
    return {
      name: 'login',
      query: {
        ...(to.fullPath !== '/' ? { redirect: to.fullPath } : {}),
        ...(expired ? { expired } : {}),
      },
    }
  }
  if (to.name === 'login' && auth.isLoggedIn) return { name: 'dashboard' }
  // 页面级权限：URL 直接输也不能看（后端仍会 403，这里只是别让人看到页面骨架）
  const need = (to.meta?.roles as string[] | undefined) ?? []
  if (need.length && !need.includes(auth.user?.role ?? '')) {
    return { name: 'robot-status', query: { denied: '1' } }
  }
  return true
})

export default router
