import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const login = vi.fn()
const me = vi.fn()
const logout = vi.fn()

vi.mock('@/api', () => ({
  api: {
    login: (...a: unknown[]) => login(...a),
    me: (...a: unknown[]) => me(...a),
    logout: (...a: unknown[]) => logout(...a),
  },
}))

import { useAuthStore } from '@/stores/auth'

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    login.mockReset()
    me.mockReset()
    logout.mockReset()
  })

  it('登录后写入用户并可写', async () => {
    login.mockResolvedValue({ user: { id: 1, username: 'u', role: 'operator' } })
    const s = useAuthStore()
    await s.login('u', 'p')
    expect(s.isLoggedIn).toBe(true)
    expect(s.canWrite).toBe(true)
  })

  it('角色权限矩阵：viewer 不能写，safety 能写', async () => {
    const s = useAuthStore()
    s.user = { id: 2, username: 'v', role: 'viewer' }
    expect(s.canWrite).toBe(false)
    s.user = { id: 3, username: 's', role: 'safety' }
    expect(s.canWrite).toBe(true)
    s.user = { id: 4, username: 'a', role: 'admin' }
    expect(s.canWrite).toBe(true)
  })

  it('初始密码标记透出给强制改密遮罩', () => {
    const s = useAuthStore()
    s.user = { id: 5, username: 'n', role: 'operator', must_change_password: true }
    expect(s.mustChangePassword).toBe(true)
    s.user = { ...s.user, must_change_password: false }
    expect(s.mustChangePassword).toBe(false)
  })

  it('登出后清空用户', async () => {
    logout.mockResolvedValue({ ok: true })
    const s = useAuthStore()
    s.user = { id: 1, username: 'u', role: 'admin' }
    await s.logout()
    expect(s.user).toBeNull()
    expect(s.isLoggedIn).toBe(false)
  })
})
