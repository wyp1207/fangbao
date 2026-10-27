import { defineStore } from 'pinia'
import { api, type User } from '@/api'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as User | null,
    loading: false,
    checked: false,
  }),
  getters: {
    isLoggedIn: (s) => !!s.user,
    canWrite: (s) => ['admin', 'safety', 'operator'].includes(s.user?.role ?? ''),
    mustChangePassword: (s) => !!s.user?.must_change_password,
  },
  actions: {
    async login(username: string, password: string, totpCode?: string) {
      this.loading = true
      try {
        const res = await api.login(username, password, totpCode)
        this.user = res.user
        this.checked = true
        // 记一笔"这台浏览器登录过"：Cookie 过期后整页刷新也能判断出是会话过期，
        // 而不是用户第一次来（用于登录页清空账号密码并给出提示）
        try { sessionStorage.setItem('jc_signed_in', '1') } catch { /* 隐私模式忽略 */ }
      } finally {
        this.loading = false
      }
    },
    async refreshMe() {
      try {
        this.user = await api.me()
      } catch { /* 保持现状 */ }
    },
    async fetchMe() {
      if (this.checked) return
      try {
        this.user = await api.me()
      } catch {
        this.user = null
      } finally {
        this.checked = true
      }
    },
    async logout() {
      try {
        await api.logout()
      } finally {
        this.user = null
        try { sessionStorage.removeItem('jc_signed_in') } catch { /* ignore */ }
      }
    },
  },
})
