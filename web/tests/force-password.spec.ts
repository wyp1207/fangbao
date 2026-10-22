import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const changePassword = vi.fn()
const me = vi.fn()

vi.mock('@/api', () => ({
  api: {
    changePassword: (...a: unknown[]) => changePassword(...a),
    me: (...a: unknown[]) => me(...a),
  },
}))

import ForcePasswordChange from '@/components/ForcePasswordChange.vue'
import { useAuthStore } from '@/stores/auth'

function mountWith(user: { must_change_password?: boolean }) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAuthStore()
  store.user = { id: 1, username: 'admin', role: 'admin', ...user }
  store.checked = true
  const wrapper = mount(ForcePasswordChange, { global: { plugins: [pinia] } })
  return { wrapper, store }
}

describe('强制改密遮罩', () => {
  beforeEach(() => {
    changePassword.mockReset()
    me.mockReset()
  })

  it('标记为 false 时不渲染', () => {
    const { wrapper } = mountWith({ must_change_password: false })
    expect(wrapper.find('.force-mask').exists()).toBe(false)
  })

  it('标记为 true 时盖住界面，规则不满足按钮禁用', async () => {
    const { wrapper } = mountWith({ must_change_password: true })
    expect(wrapper.find('.force-mask').exists()).toBe(true)
    const btn = wrapper.find('.force-box button')
    expect(btn.attributes('disabled')).toBeDefined()

    const inputs = wrapper.findAll('.force-box input[type="password"]')
    // 纯数字：不满足"含字母"
    await inputs[1].setValue('12345678')
    await inputs[2].setValue('12345678')
    expect(wrapper.find('.force-box button').attributes('disabled')).toBeDefined()

    await inputs[1].setValue('Abcd1234')
    await inputs[2].setValue('Abcd1234')
    expect(wrapper.find('.force-box button').attributes('disabled')).toBeUndefined()
  })

  it('两次输入不一致会提示且不能提交', async () => {
    const { wrapper } = mountWith({ must_change_password: true })
    const inputs = wrapper.findAll('.force-box input[type="password"]')
    await inputs[1].setValue('Abcd1234')
    await inputs[2].setValue('Abcd9999')
    expect(wrapper.text()).toContain('两次输入不一致')
    expect(wrapper.find('.force-box button').attributes('disabled')).toBeDefined()
  })

  it('改密成功后刷新用户，遮罩消失', async () => {
    const { wrapper, store } = mountWith({ must_change_password: true })
    changePassword.mockResolvedValue({ ok: true })
    me.mockImplementation(async () => {
      store.user = { id: 1, username: 'admin', role: 'admin', must_change_password: false }
      return store.user
    })

    const inputs = wrapper.findAll('.force-box input[type="password"]')
    await inputs[0].setValue('Init12345')
    await inputs[1].setValue('Abcd1234')
    await inputs[2].setValue('Abcd1234')
    await wrapper.find('.force-box button').trigger('click')
    await new Promise((r) => setTimeout(r, 0))

    expect(changePassword).toHaveBeenCalledWith('Init12345', 'Abcd1234')
    await wrapper.vm.$nextTick()
    expect(store.mustChangePassword).toBe(false)
    expect(wrapper.find('.force-mask').exists()).toBe(false)
  })
})
