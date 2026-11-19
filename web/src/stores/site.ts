import { defineStore } from 'pinia'
import { api, type DeviceItem, type SiteItem } from '@/api'
import { useRobotStore } from '@/stores/robot'

/**
 * 场站上下文：整个控制台只有一份「当前场站」。
 *
 * 之前首页拿 devices 的 station 字符串做去重，列表页各自不过滤，切了场站
 * 还能看到别站的地图/模板/任务。现在统一由这个 store 提供：
 * - 选中值写 localStorage（jc_site_id），刷新后还停在同一个场站；
 * - 默认取第一个启用场站，不为了“页面好看”自动造场站；
 * - 切站时若当前设备不属于该站，自动落到该站第一台；该站没有设备就清空，
 *   免得首页继续显示上一站的机器人数据。
 */

const SITE_KEY = 'jc_site_id'

let loadPromise: Promise<void> | null = null
let devicesPending: { siteId: number; promise: Promise<void> } | null = null

function readSaved(): number {
  try {
    return Number(localStorage.getItem(SITE_KEY) ?? 0) || 0
  } catch {
    return 0
  }
}

function save(id: number) {
  try {
    localStorage.setItem(SITE_KEY, String(id))
  } catch { /* 隐私模式/测试环境没有 storage，不影响本次会话 */ }
}

export const useSiteStore = defineStore('site', {
  state: () => ({
    sites: [] as SiteItem[],
    currentSiteId: null as number | null,
    /** 当前场站的设备；首页/设备台账都直接用它，避免各自再请求一遍 */
    devices: [] as DeviceItem[],
    loaded: false,
  }),
  getters: {
    enabledSites: (s) => s.sites.filter((x) => x.status === 1),
    currentSite: (s) => s.sites.find((x) => x.id === s.currentSiteId) ?? null,
    currentSiteName: (s) => s.sites.find((x) => x.id === s.currentSiteId)?.name ?? '未分场站',
    siteOptions: (s) =>
      s.sites.filter((x) => x.status === 1).map((x) => ({ value: String(x.id), label: x.name })),
  },
  actions: {
    /** 拉场站列表并选定当前场站：优先 localStorage 里仍启用的那个，否则第一个启用站。 */
    async load() {
      if (this.loaded) return
      if (!loadPromise) {
        loadPromise = (async () => {
          const rows = await api.sites()
          this.sites = rows
          const enabled = rows.filter((s) => s.status === 1)
          const pool = enabled.length ? enabled : rows
          const saved = readSaved()
          const pick = pool.find((s) => s.id === saved) ?? pool[0] ?? null
          this.currentSiteId = pick?.id ?? null
          if (pick) {
            save(pick.id)
            await this.loadDevices()
          }
          this.loaded = true
        })().finally(() => { loadPromise = null })
      }
      await loadPromise
    },

    /**
     * 拉当前场站的设备，并把机器人切到该站第一台（当前设备已属于该站就不动）。
     * 同一场站的并发调用复用同一个请求：首页 mount 和布局层同时触发时只打一次。
     */
    async loadDevices(force = false) {
      const siteId = this.currentSiteId
      if (siteId == null) {
        this.devices = []
        return
      }
      if (!force && devicesPending && devicesPending.siteId === siteId) {
        return devicesPending.promise
      }
      const promise = (async () => {
        const rows = await api.devices(siteId)
        if (this.currentSiteId !== siteId) return   // 请求期间又切站了，丢弃
        this.devices = rows
        this.syncRobot(rows)
      })()
      devicesPending = { siteId, promise }
      try {
        await promise
      } finally {
        if (devicesPending?.promise === promise) devicesPending = null
      }
    },

    /** 当前设备不属于本站就自动切到该站第一台；本站没有设备则清空当前设备。 */
    syncRobot(rows: DeviceItem[]) {
      const robot = useRobotStore()
      if (rows.some((d) => d.id === robot.deviceId)) return
      if (rows.length) robot.setDevice(rows[0].id)
      else robot.clearDevice()
    },

    async setSite(id: number) {
      if (id === this.currentSiteId) return
      const target = this.sites.find((s) => s.id === id && s.status === 1)
      if (!target) return
      // 先落本地和 store：下拉立刻反馈，列表页的 watch 也能马上响应
      this.currentSiteId = id
      save(id)
      this.devices = []
      try {
        await this.loadDevices(true)
      } catch (e) {
        // 设备列表拉不到时场站仍算切过去了，但必须让调用方知道失败
        this.devices = []
        throw e
      }
    },
  },
})
