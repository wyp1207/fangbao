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
    async login(username: string, password: string) {
      this.loading = true
      try {
        const res = await api.login(username, password)
        this.user = res.user
        this.checked = true
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
      }
    },
  },
})
