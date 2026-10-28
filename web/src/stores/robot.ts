import { defineStore } from 'pinia'
import { api, type AlarmItem, type MapMeta, type StatusSnapshot } from '@/api'

const POLL_MS = 1000
const WS_RETRY_MS = 3000
const ALARM_EVERY = 5 // 每 5 次轮询刷一次告警，够用且省请求

let ws: WebSocket | null = null

export const useRobotStore = defineStore('robot', {
  state: () => ({
    snapshot: null as StatusSnapshot | null,
    maps: [] as MapMeta[],
    currentMap: '' as string,
    alarms: [] as AlarmItem[],
    lastError: '' as string,
    deviceId: 1 as number,
    timer: 0 as number,
    ticks: 0 as number,
    wsConnected: false as boolean,
    wsPoseAt: 0 as number,
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
    /** 位姿 WebSocket：200ms 一帧，配合前端插值，机器人不再"瞬移" */
    startWs() {
      const dev = this.deviceId
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      try {
        ws?.close()
      } catch { /* ignore */ }
      const sock = new WebSocket(`${proto}://${location.host}/api/v1/ws/robot/${dev}`)
      ws = sock
      sock.onopen = () => { this.wsConnected = true }
      sock.onclose = () => {
        this.wsConnected = false
        if (ws !== sock) return
        window.setTimeout(() => { if (this.deviceId === dev) this.startWs() }, WS_RETRY_MS)
      }
      sock.onerror = () => { this.wsConnected = false }
      sock.onmessage = (ev) => {
        try {
          const m = JSON.parse(ev.data)
          if (m.type !== 'state' || !this.snapshot) return
          if (m.pose) this.snapshot.pose = m.pose
          if (m.status) this.snapshot.status = { ...(this.snapshot.status as object), ...m.status } as never
          if (m.online !== undefined) this.snapshot.online = m.online
          if (m.battery !== undefined && this.snapshot.info) this.snapshot.info.battery = m.battery
          this.wsPoseAt = Date.now()
        } catch { /* 忽略坏帧 */ }
      }
    },
    stopWs() {
      try { ws?.close() } catch { /* ignore */ }
      ws = null
      this.wsConnected = false
    },
    async refresh() {
      try {
        this.snapshot = await api.status(this.deviceId)
        this.lastError = ''
      } catch (e) {
        this.lastError = e instanceof Error ? e.message : String(e)
      }
      if (++this.ticks % ALARM_EVERY === 0) await this.refreshAlarms()
    },
    setDevice(id: number) {
      if (this.deviceId === id) return
      this.deviceId = id
      this.snapshot = null
      void this.refresh()
    },
    async refreshAlarms() {
      try {
        this.alarms = (await api.alarms()).items
      } catch {
        /* 告警拉取失败不打断状态轮询 */
      }
    },
    async ackAlarm(id: number) {
      const acked = await api.ackAlarm(id)
      const hit = this.alarms.find((a) => a.id === id)
      if (hit) Object.assign(hit, acked)
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
