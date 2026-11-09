import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import { ApiError } from '@/api/client'

/**
 * 全屏锁屏：空闲超时不再"退出登录"，而是锁屏等本人输密码解锁。
 * 为什么改：值班大屏半夜没人看，退出登录等于把现场画面关掉；
 * 锁屏既保护操作权限，又能让大屏继续显示。
 */
export const useLockStore = defineStore('lock', () => {
  const locked = ref(false)
  const password = ref('')
  const busy = ref(false)
  const error = ref('')
  const idleMinutes = ref(5)
  // 会话过期（后端重启/令牌失效）时，解锁注定失败，必须引导重新登录而不是让用户反复试密码
  const expired = ref(false)

  /** /auth/verify 的 401 有两种：密码错（业务失败）和会话失效（未登录/令牌过期）。
   *  只有后者才把人踢去重新登录，否则打错一次密码就误判成过期。 */
  function sessionGone(e: unknown): boolean {
    if (!(e instanceof ApiError) || e.status !== 401) return false
    return !/密码|尝试次数/.test(e.message || '')
  }

  function lock(minutes?: number) {
    if (minutes && minutes > 0) idleMinutes.value = minutes
    password.value = ''
    error.value = ''
    expired.value = false
    locked.value = true
  }

  async function unlock() {
    if (!password.value) {
      error.value = '请输入密码'
      return false
    }
    busy.value = true
    error.value = ''
    try {
      await api.verifyPassword(password.value)
      locked.value = false
      password.value = ''
      return true
    } catch (e) {
      if (sessionGone(e)) {
        expired.value = true
        error.value = '登录已过期，请重新登录'
      } else {
        error.value = e instanceof Error ? e.message : '密码不正确'
      }
      return false
    } finally {
      busy.value = false
    }
  }

  return { locked, password, busy, error, idleMinutes, expired, lock, unlock }
})
