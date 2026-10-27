import { onBeforeUnmount, onMounted } from 'vue'
import { api } from '@/api'
import { triggerUnauthorized } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { toast } from '@/composables/useToast'

/**
 * 空闲会话守卫：超过 N 分钟没有任何鼠标/键盘/滚动操作，就向服务端问一次"我还登录着吗"。
 * 服务端回 401 → 走全局拦截退回登录页（和"点着点着掉线"同一条路径）。
 *
 * N 从「系统设置 → 空闲多久自动退出（分钟）」读，默认 5 分钟；
 * 为什么不是定时心跳：每天几百次没人看的请求没意义；空闲才探一次，
 * 既不打扰在线用户，也不会让大屏挂一整晚假装还在跑。
 */
const FALLBACK_MINUTES = 5
const CHECK_EVERY_MS = 60_000
const REFRESH_SETTING_MS = 10 * 60_000

function devOverride(): number | null {
  // 只在本地调试用：localStorage 里显式设了才生效，生产不写这玩意
  try {
    const n = Number(localStorage.getItem('jc_idle_minutes'))
    if (Number.isFinite(n) && n > 0) return n
  } catch { /* 隐私模式 */ }
  return null
}

export function useIdleSessionGuard() {
  let lastActive = Date.now()
  let idleMinutes = FALLBACK_MINUTES
  let timer = 0
  let refreshTimer = 0

  const bump = () => { lastActive = Date.now() }
  const events = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'wheel']

  async function loadSetting() {
    const override = devOverride()
    if (override !== null) { idleMinutes = override; return }
    try {
      const res = await api.settings()
      const raw = (res.values as Record<string, unknown>)['security.idle_minutes']
      const n = Number(raw)
      idleMinutes = Number.isFinite(n) && n > 0 ? n : FALLBACK_MINUTES
    } catch {
      idleMinutes = FALLBACK_MINUTES   // 读不到设置就用默认，绝不因为设置接口挂了就永不退出
    }
  }

  async function check() {
    const idle = (Date.now() - lastActive) / 60000
    if (idle < idleMinutes) return
    lastActive = Date.now()      // 先推后，避免同一分钟重复触发

    // 空闲超时 = 主动退出，而不是"问一下还登录着吗"。
    // 之前只探活，服务端 token 还有效就什么都不做，设置形同虚设（QA 实测发现）。
    try {
      await api.logout()
    } catch {
      // 服务端已经失效也无所谓，本地照样清状态
    }
    try { sessionStorage.removeItem('jc_signed_in') } catch { /* ignore */ }
    const auth = useAuthStore()
    auth.user = null
    triggerUnauthorized()        // 复用全局跳转（回登录页并带 expired=1）
    toast(`已空闲 ${Math.round(idleMinutes)} 分钟，自动退出登录`, 'warn', 6000)
  }

  onMounted(() => {
    void loadSetting()
    refreshTimer = window.setInterval(() => { void loadSetting() }, REFRESH_SETTING_MS)
    events.forEach((e) => window.addEventListener(e, bump, { passive: true }))
    window.addEventListener('visibilitychange', bump)
    timer = window.setInterval(() => { void check() }, CHECK_EVERY_MS)
  })

  onBeforeUnmount(() => {
    events.forEach((e) => window.removeEventListener(e, bump))
    window.removeEventListener('visibilitychange', bump)
    window.clearInterval(timer)
    window.clearInterval(refreshTimer)
  })
}
