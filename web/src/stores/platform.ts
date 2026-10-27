import { defineStore } from 'pinia'
import { api } from '@/api'

/**
 * 平台级外观设置（系统设置 → 平台）。
 *
 * 这三个键以前只在设置页里能改、代码里没人读，属于"假开关"；
 * 现在页面标题、默认场站、故障横幅都真的按这里的值走。
 */
export const usePlatformStore = defineStore('platform', {
  state: () => ({
    name: '智能巡检机器人管理平台',
    site: '默认场站',
    bannerOnFault: true,
    loaded: false,
  }),
  actions: {
    async load() {
      try {
        const res = await api.settings()
        const v = res.values as Record<string, unknown>
        if (typeof v['platform.name'] === 'string' && v['platform.name']) {
          this.name = v['platform.name'] as string
        }
        if (typeof v['platform.site'] === 'string' && v['platform.site']) {
          this.site = v['platform.site'] as string
        }
        if (typeof v['platform.banner_on_fault'] === 'boolean') {
          this.bannerOnFault = v['platform.banner_on_fault'] as boolean
        }
        this.applyTitle()
      } catch {
        // 设置读不到就用默认值，不影响使用
      } finally {
        this.loaded = true
      }
    },
    applyTitle() {
      try {
        document.title = this.name
      } catch { /* SSR/测试环境没有 document */ }
    },
  },
})
