import { onBeforeUnmount, onMounted } from 'vue'
import { api } from '@/api'
import { useLockStore } from '@/stores/lock'
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
const REFRESH_SETTING_MS = 60_000

export function useIdleSessionGuard() {
  let lastActive = Date.now()
  let idleMinutes = FALLBACK_MINUTES
  let enabled = true
  let timer = 0
  let refreshTimer = 0

  const bump = () => { lastActive = Date.now() }
  const events = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'wheel']

  async function loadSetting() {
    try {
      const res = await api.settings()
      const v = res.values as Record<string, unknown>
      // 先看总开关，再取分钟数；关掉后 idleMinutes 不再起作用
      enabled = v['security.idle_lock_enabled'] !== false
      const n = Number(v['security.idle_minutes'])
      idleMinutes = Number.isFinite(n) && n > 0 ? n : FALLBACK_MINUTES
    } catch {
      // 读不到就按默认开、5 分钟，绝不因为设置接口挂了就永不锁屏
      enabled = true
      idleMinutes = FALLBACK_MINUTES
    }
  }

  async function check() {
    if (!enabled) return
    const idle = (Date.now() - lastActive) / 60000
    if (idle < idleMinutes) return
    lastActive = Date.now()

    // 空闲超时 = 锁屏，不是退出登录。
    // 值班大屏半夜没人看，退出登录等于把现场画面关掉；锁屏既保护操作权限又能继续显示。
    const lock = useLockStore()
    lock.lock(Math.round(idleMinutes))
    toast(`已空闲 ${Math.round(idleMinutes)} 分钟，屏幕已锁定`, 'warn', 6000)
  }

  // 设置页保存后立刻生效，不用等下一次轮询
  const onSettingsSaved = () => { void loadSetting() }

  onMounted(() => {
    void loadSetting()
    refreshTimer = window.setInterval(() => { void loadSetting() }, REFRESH_SETTING_MS)
    window.addEventListener('jc:settings-updated', onSettingsSaved)
    events.forEach((e) => window.addEventListener(e, bump, { passive: true }))
    window.addEventListener('visibilitychange', bump)
    timer = window.setInterval(() => { void check() }, CHECK_EVERY_MS)
  })

  onBeforeUnmount(() => {
    events.forEach((e) => window.removeEventListener(e, bump))
    window.removeEventListener('visibilitychange', bump)
    window.removeEventListener('jc:settings-updated', onSettingsSaved)
    window.clearInterval(timer)
    window.clearInterval(refreshTimer)
  })
}
