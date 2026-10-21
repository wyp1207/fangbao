import { defineStore } from 'pinia'
import { api, type MapMeta, type StatusSnapshot } from '@/api'

const POLL_MS = 1000

export const useRobotStore = defineStore('robot', {
  state: () => ({
    snapshot: null as StatusSnapshot | null,
    maps: [] as MapMeta[],
    currentMap: '' as string,
    lastError: '' as string,
    timer: 0 as number,
  }),
  getters: {
    online: (s) => s.snapshot?.online ?? false,
    /** 数据新鲜度：超过 3s 未更新，UI 必须标“数据过期”（方案 §10） */
    stale: (s) => (s.snapshot ? s.snapshot.age_s > 3 : true),
    battery: (s) => s.snapshot?.info?.battery ?? null,
    estop: (s) => s.snapshot?.info?.driver_port ?? null,
    robotState: (s) => s.snapshot?.status?.status ?? 'UNKNOWN',
    pose: (s) => s.snapshot?.pose ?? null,
  },
  actions: {
    async refresh() {
      try {
        this.snapshot = await api.status()
        this.lastError = ''
      } catch (e) {
        this.lastError = e instanceof Error ? e.message : String(e)
      }
    },
    async loadMaps() {
      this.maps = await api.maps()
      const current = await api.currentMap()
      this.currentMap = current.name
    },
    start() {
      if (this.timer) return
      void this.refresh()
      this.timer = window.setInterval(() => void this.refresh(), POLL_MS)
    },
    stop() {
      if (this.timer) {
        window.clearInterval(this.timer)
        this.timer = 0
      }
    },
  },
})
