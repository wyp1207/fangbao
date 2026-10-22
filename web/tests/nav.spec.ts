import { describe, expect, it } from 'vitest'
import { NAV } from '@/config/nav'

describe('导航配置', () => {
  it('8 个一级分组，首页在第一项', () => {
    expect(NAV.length).toBe(8)
    expect(NAV[0].label).toBe('首页')
    expect(NAV[0].route).toBe('dashboard')
  })

  it('除了首页，其余分组要么有 items，要么有 route', () => {
    for (const g of NAV.slice(1)) {
      expect(Boolean(g.items?.length || g.route), `${g.label} 既没有子项也没有路由`).toBe(true)
    }
  })

  it('子项 name 全局唯一（重复会导致路由高亮错乱）', () => {
    const names = NAV.flatMap((g) => g.items?.map((i) => i.name) ?? [])
    expect(new Set(names).size).toBe(names.length)
  })

  it('每个子项都有中文 label', () => {
    for (const g of NAV) {
      for (const item of g.items ?? []) {
        expect(item.label.trim().length, item.name).toBeGreaterThan(0)
      }
    }
  })
})
