import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'

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

  function lock(minutes?: number) {
    if (minutes && minutes > 0) idleMinutes.value = minutes
    password.value = ''
    error.value = ''
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
      error.value = e instanceof Error ? e.message : '密码不正确'
      return false
    } finally {
      busy.value = false
    }
  }

  return { locked, password, busy, error, idleMinutes, lock, unlock }
})
