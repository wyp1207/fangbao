import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
// 一期 UI 全用自写组件 + CSS 变量（styles/tokens.css），没有依赖任何组件库，
// 所以不装 Arco、也不引它 400KB 的全量样式。真要换组件库时再装，走按需引入。
import './styles/tokens.css'
import { onUnauthorized } from './api/client'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
app.use(createPinia()).use(router)

// 会话过期：清登录态 → 回登录页（带 expired=1，登录页会清空账号密码并提示）
onUnauthorized(() => {
  const auth = useAuthStore()
  const had = auth.isLoggedIn
  auth.user = null
  try { sessionStorage.removeItem('jc_signed_in') } catch { /* ignore */ }
  const current = router.currentRoute.value
  if (current.name === 'login') return
  void router.push({
    name: 'login',
    query: { ...(current.fullPath !== '/' ? { redirect: current.fullPath } : {}), expired: '1' },
  })
  if (had) console.warn('[auth] 登录已过期，已退回登录页')
})

app.mount('#app')
