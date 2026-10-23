<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import MapCanvas from '@/components/MapCanvas.vue'
import ScadaPanel from '@/components/ScadaPanel.vue'
import VideoBox from '@/components/VideoBox.vue'
import AnimatedNumber from '@/components/AnimatedNumber.vue'
import DarkSelect from '@/components/DarkSelect.vue'
import TopNav from '@/components/TopNav.vue'
import UserMenu from '@/components/UserMenu.vue'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/client'
import { useRobotStore } from '@/stores/robot'
import { api, type MapMeta, type NavPoint } from '@/api'
import logoUrl from '@/assets/logo.png'

const robot = useRobotStore()
const auth = useAuthStore()
const router = useRouter()

const mapMeta = ref<MapMeta | null>(null)
const points = ref<NavPoint[]>([])
const trail = ref<{ x: number; y: number }[]>([])
const mapError = ref('')
const now = ref(new Date())
const controlTab = ref<'ptz' | 'chassis'>('ptz')

// ---- 锁屏 ----
const locked = ref(false)
const lockPwd = ref('')
const lockBusy = ref(false)
const lockError = ref('')

function lockScreen() {
  lockPwd.value = ""
  lockError.value = ""
  locked.value = true
}

async function unlock() {
  lockBusy.value = true
  lockError.value = ""
  try {
    await api.verifyPassword(lockPwd.value)
    locked.value = false
    lockPwd.value = ""
  } catch (e) {
    lockError.value = e instanceof Error ? e.message : "密码不正确"
  } finally {
    lockBusy.value = false
  }
}

// ---- 全屏 ----
// 首页内嵌视频：取第一路可用视频源（可见光/热红外分开挑）
const videoRows = ref<{
  id: number; name: string; group_name: string; stream_name: string
  go2rtc_url: string | null; show_on_dashboard?: boolean
}[]>([])

/** 只有显式勾了「首页显示」的摄像头才上大屏——测试流不该自己冒出来 */
const dashVideos = computed(() => videoRows.value.filter((v) => v.show_on_dashboard && v.go2rtc_url))
const visibleVideo = computed(() => {
  const pool = dashVideos.value
  // 优先云台/球机：机载广角画面畸变，不能当大屏主画面
  return pool.find((x) => /云台|PTZ|球机/i.test(x.name)) ??
    pool.find((x) => !/机载|广角|鱼眼/.test(x.name)) ??
    pool[0] ?? null
})
const thermalVideo = computed(() =>
  dashVideos.value.find((x) => /热|红外|thermal/i.test(x.name + x.group_name)) ?? null)
const visibleStream = computed(() => visibleVideo.value?.go2rtc_url ?? '')
const thermalStream = computed(() => thermalVideo.value?.go2rtc_url ?? '')

// 消息中心未读数（和消息页用同一个 localStorage 时间戳）
const msgUnread = ref(0)


const READ_KEY = 'jc_msg_read_ts'
async function refreshMsgUnread() {
  try {
    const res = await api.messages()
    const readTs = Number(localStorage.getItem(READ_KEY) ?? 0)
    msgUnread.value = res.items.filter((m) => m.ts > readTs).length
  } catch { /* 消息拿不到不影响大屏 */ }
}
const devices = ref<{ id: number; name: string; station: string }[]>([])
const site = ref('')
const deviceId = ref('1')

const sites = computed(() => {
  const names = [...new Set(devices.value.map((d) => d.station).filter(Boolean))]
  return (names.length ? names : ['未分场站']).map((n) => ({ value: n, label: n }))
})
// 设备下拉列出全部设备（含其他场站的），选谁就自动切到它的场站。
// 之前按场站过滤，结果"实验室"里的两台在默认场站下根本选不到。
const deviceOptions = computed(() =>
  devices.value.map((d) => ({
    value: String(d.id),
    label: d.station && d.station !== site.value ? `${d.name}（${d.station}）` : d.name,
  })),
)

function onSite(v: string) {
  site.value = v
  const hit = devices.value.find((d) => d.station === v)
  if (hit) {
    deviceId.value = String(hit.id)
    robot.setDevice(hit.id)          // 真切数据源，别只改个名字
    void api.videos(Number(deviceId.value)).then((rows) => { videoRows.value = rows as never }).catch(() => undefined)
    void loadMap()
    toast('已切换到场站 ' + v + '（设备 ' + hit.name + '）', 'ok')
  } else {
    toast('该场站暂无设备', 'warn')
  }
}
function onDevice(v: string) {
  deviceId.value = v
  const hit = devices.value.find((d) => String(d.id) === v)
  robot.setDevice(Number(v))
  toast('已切换到 ' + (hit?.name ?? v), 'ok')
  // 换设备就刷新视频与地图，避免还显示上一台的画面
  void api.videos(Number(deviceId.value)).then((rows) => { videoRows.value = rows as never }).catch(() => undefined)
  void loadEnv()
  void loadTrend()
  void loadCaps()
  void loadRuns()
  void loadFeed()
  // 切设备时重建定时器：先清掉旧的，否则每切一次就多 3 个轮询
  timers.forEach((t) => window.clearInterval(t))
  timers = []
  timers.push(window.setInterval(loadEnv, 15000))
  timers.push(window.setInterval(loadTrend, 60000))
  timers.push(window.setInterval(loadRuns, 10000))
  timers.push(window.setInterval(loadFeed, 15000))
  timers.push(window.setInterval(pollUnread, 30000))

  // 切设备时把场站也对齐，否则下拉显示"全部"、后面地图/健康还停在旧设备
  const d = devices.value.find((x) => String(x.id) === v)
  if (d?.station && d.station !== site.value) site.value = d.station
}
function goAlarms(status: 'unacked' | 'acked') {
  void router.push({ name: 'alarms', query: { status } })
}

function goPoint(p: { name?: string }) {
  void router.push({ name: 'map', query: { map: robot.currentMap, point: p.name ?? '' } })
}

function goVideo(v: { id: number } | null) {
  // 带 source id 过去，视频页直接选中同一路；没有就落到默认第一路
  void router.push({ name: 'video', query: v ? { source: String(v.id) } : {} })
}

function openVideo(which: string) {
  toast(`${which}通道未接入：真机联调后按 RTSP / WebRTC 接入`, 'warn', 3000)
}
const busyMotion = ref(false)
type FeedRow = { id: number; ts: string; text: string; level: string; badge: string; link: string }
const msgTab = ref<'patrol' | 'alarm' | 'control'>('alarm')
const tabTitle = computed(() => ({ patrol: '巡检消息', alarm: '告警内容', control: '控制指令' }[msgTab.value]))
// 未读：记录每个 tab 见过的最大 id，轮询发现更大就点亮红点
const lastSeen = ref<Record<string, number>>({ patrol: 0, alarm: 0, control: 0 })
const unread = ref<Record<string, boolean>>({ patrol: false, alarm: false, control: false })

function markSeen() {
  const top = feedRows.value[0]?.id ?? 0
  lastSeen.value[msgTab.value] = Math.max(lastSeen.value[msgTab.value] ?? 0, top)
  unread.value[msgTab.value] = false
}

async function pollUnread() {
  for (const kind of ['patrol', 'alarm', 'control'] as const) {
    if (kind === msgTab.value) continue
    try {
      const top = (await api.dashboardFeed(kind, 1)).items[0]?.id ?? 0
      if (top > (lastSeen.value[kind] ?? 0)) unread.value[kind] = true
    } catch { /* 忽略 */ }
  }
}
const feedRows = ref<FeedRow[]>([])
const msgRows = computed(() => feedRows.value)

async function loadFeed() {
  try {
    feedRows.value = (await api.dashboardFeed(msgTab.value, 30)).items
    markSeen()
  } catch {
    feedRows.value = []
  }
}

function openMsg(row: FeedRow) {
  void router.push(row.link)     // 和后端页面一一对应：告警/任务执行/系统日志
}
const alarmUnacked = computed(() => robot.alarms.filter((a) => !a.acked_at).length)
const alarmAcked = computed(() => robot.alarms.filter((a) => !!a.acked_at).length)
const alarmCritical = computed(() => robot.alarms.filter((a) => a.level === 'critical').length)

// 今日任务状态（右半边）
type RunRow = { id: number; name: string; status: string; steps?: number; ok?: number }
const runs = ref<RunRow[]>([])
const runStats = computed(() => {
  const st = { total: runs.value.length, planned: 0, running: 0, done: 0, failed: 0, cancelled: 0 }
  for (const r of runs.value) {
    if (r.status in st) (st as Record<string, number>)[r.status] += 1
  }
  return st
})
const currentRun = computed(() => runs.value.find((r) => r.status === 'running') ?? null)
const runStatusText = computed(() => {
  const map: Record<string, string> = {
    planned: '待执行', running: '正在执行', done: '已完成', failed: '失败', cancelled: '已取消',
  }
  return currentRun.value ? (map[currentRun.value.status] ?? currentRun.value.status) : '当前无任务'
})
const runEta = computed(() => {
  const r = currentRun.value
  if (!r || !r.steps) return '—'
  const left = Math.max(0, r.steps - (r.ok ?? 0))
  return left ? `${left} 个点位（约 ${left * 3} 分钟）` : '收尾中'
})

async function loadRuns() {
  try {
    const res = await api.taskRuns({ limit: 50 })
    runs.value = ((res as unknown as { items?: RunRow[] }).items ?? [])
  } catch {
    runs.value = []
  }
}
const caps = ref<{ actions?: string[] }>({})

async function loadCaps() {
  try {
    const id = Number(deviceId.value)
    caps.value = Number.isFinite(id) ? await api.robotCapabilities(id) : {}
  } catch {
    caps.value = {}
  }
}
const canStand = computed(() => (caps.value.actions ?? []).includes("stand_up"))

/** X30 的起立/趴下是切换指令；写开关没开会直接 403，提示原因 */
async function doMotion(action: 'stand' | 'lie') {
  busyMotion.value = true
  try {
    await api.robotMotion(Number(deviceId.value), action)
    toast(action === 'stand' ? '已发送起立指令' : '已发送趴下指令', 'ok', 3000)
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : '指令发送失败'
    toast(msg, e instanceof ApiError && e.code === 'WRITE_LOCKED' ? 'warn' : 'danger', 5000)
  } finally {
    busyMotion.value = false
  }
}

function tryControl() {
  toast('写操作未开放：需真机联调通过 + 现场授权签字（采集表 01 表 15–17 行）', 'warn', 3200)
}


const pose = computed(() => robot.pose)
const galileo = computed(() => robot.snapshot?.galileo ?? {})
const unacked = computed(() => robot.alarms.filter((a) => !a.acked_at))
const acked = computed(() => robot.alarms.filter((a) => a.acked_at))
const imageUrl = computed(() => (robot.currentMap ? api.mapPng(1, robot.currentMap) : ''))

const clock = computed(() => {
  const d = now.value
  const p = (n: number) => String(n).padStart(2, '0')
  return {
    time: `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`,
    date: `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())} 星期${'日一二三四五六'[d.getDay()]}`,
  }
})

const mode = computed(() => robot.snapshot?.status?.status ?? 'UNKNOWN')
const battery = computed(() => robot.snapshot?.info?.battery ?? null)
const estop = computed(() => robot.snapshot?.info?.driver_port ?? null)
const version = computed(() => robot.snapshot?.info?.info?.version ?? '—')
const slam = computed(() => robot.snapshot?.info?.slam_type ?? '—')
const updated = computed(() => (robot.snapshot ? robot.snapshot.age_s.toFixed(1) + 's 前' : '—'))

const RING_C = 2 * Math.PI * 42
const donut = computed(() => {
  const total = robot.alarms.length
  return {
    total,
    unacked: unacked.value.length,
    acked: acked.value.length,
    red: total ? (unacked.value.length / total) * RING_C : 0,
    green: total ? (acked.value.length / total) * RING_C : 0,
  }
})

type EnvSummary = Record<string, { name: string; unit: string; value: number | null; ts: string | null; calibrated: boolean }>
const env = ref<EnvSummary>({})

// 环境面板只显示"这台设备上真有"的传感器（X30 有 SF6/温湿度，JCROB 可能是噪声）
const envSensors = ref<{ name: string; unit: string; value: number | null }[]>([])

function fmtEnv(v: number | null): string {
  if (v === null || v === undefined) return '--'
  const abs = Math.abs(v)
  if (abs >= 100) return v.toFixed(1)      // 114.3
  if (abs >= 10) return v.toFixed(1)       // 33.2
  return v.toFixed(2)                      // 7.60
}

const envCells = computed(() =>
  envSensors.value.map((s) => ({
    label: s.name,
    unit: s.unit,
    value: s.value === null ? null : fmtEnv(s.value),
  })),
)

const envCount = computed(() => envSensors.value.length)

// 近 7 日告警趋势（真实统计）
type TrendDay = { date: string; warn: number; critical: number; total: number }
const trend = ref<TrendDay[]>([])
const trendTotal = computed(() => trend.value.reduce((n, d) => n + d.total, 0))
const trendPeak = computed(() => Math.max(1, ...trend.value.map((d) => d.total)))

function barH(n: number): number {
  return n ? Math.max(6, (n / trendPeak.value) * 100) : 0
}

async function loadTrend() {
  try {
    trend.value = (await api.alarmStats(7)).series
  } catch { /* 统计失败不影响大屏 */ }
}

async function loadEnv() {
  try {
    const id = Number(deviceId.value)
    // 按设备取：切换设备后这里拿到的就是那台设备自己的传感器
    const rows = await api.sensors(Number.isFinite(id) ? id : undefined)
    envSensors.value = rows.map((s) => ({
      name: s.name,
      unit: s.unit,
      value: s.latest?.value ?? null,
    }))
  } catch {
    envSensors.value = []   // 该设备没接传感器就空着，不显示别人的数据
  }
}

function num(v: unknown, digits = 2): string {
  return typeof v === 'number' ? v.toFixed(digits) : '—'
}

async function loadMap() {
  try {
    await robot.loadMaps()
    const meta = robot.maps.find((m) => m.name === robot.currentMap) ?? robot.maps[0] ?? null
    mapMeta.value = meta
    if (meta) points.value = (await api.navPoints(1, meta.name, '')).points
  } catch (e) {
    mapError.value = e instanceof Error ? e.message : '地图加载失败'
  }
}

let timers: number[] = []
onMounted(async () => {
  robot.start()
  void api.videos(Number(deviceId.value)).then((rows) => { videoRows.value = rows as never }).catch(() => undefined)
  void loadEnv()
  void loadTrend()
  void loadCaps()
  void loadRuns()
  void loadFeed()
  // 切设备时重建定时器：先清掉旧的，否则每切一次就多 3 个轮询
  timers.forEach((t) => window.clearInterval(t))
  timers = []
  timers.push(window.setInterval(loadEnv, 15000))
  timers.push(window.setInterval(loadTrend, 60000))
  timers.push(window.setInterval(loadRuns, 10000))
  timers.push(window.setInterval(loadFeed, 15000))
  timers.push(window.setInterval(pollUnread, 30000))
  void api.devices().then((rows) => {
    devices.value = rows.map((d) => ({ id: d.id, name: d.name, station: d.station }))
    site.value = rows[0]?.station ?? '未分场站'
  }).catch(() => undefined)
  await loadMap()
  timers.push(window.setInterval(() => { now.value = new Date() }, 1000))
  void refreshMsgUnread()
  timers.push(window.setInterval(refreshMsgUnread, 15000))
  timers.push(window.setInterval(() => {
    const p = robot.pose
    if (!p || typeof p.x !== 'number' || typeof p.y !== 'number') return
    trail.value.push({ x: p.x, y: p.y })
    if (trail.value.length > 200) trail.value.shift()
  }, 1000))
})
onBeforeUnmount(() => {
  robot.stop()
  timers.forEach((t) => window.clearInterval(t))
  timers = []
})

async function logout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="board">
    <!-- 顶栏：左 logo+标签 / 中间大标题 / 右标签+用户 -->
    <header class="hdr">
      <div class="logo">
        <span class="logo-badge"><img class="logo-img" :src="logoUrl" alt="logo" /></span>
        <span class="brand">AI防爆巡检</span>
      </div>

      <div class="hdr-center">
        <TopNav :start="0" :end="4" />
        <div class="board-title">
          <span class="wing l" />
          <h1>智能巡检机器人管理平台</h1>
          <span class="wing r" />
        </div>
        <TopNav :start="4" />
      </div>

      <div class="hdr-right">
        <router-link class="icon-btn" :to="{ name: 'alarms' }" title="告警">
          <span class="bell" />{{ unacked.length }}
        </router-link>
        <UserMenu />
      </div>
    </header>


    <div class="subbar">
      <div class="sb-left">
        <div class="field"><label>当前场站</label><DarkSelect :model-value="site" :options="sites" width="190px" @update:model-value="onSite" /></div>
        <div class="field"><label>当前设备</label><DarkSelect :model-value="deviceId" :options="deviceOptions" width="170px" @update:model-value="onDevice" /></div>
        <span class="tool-icons">
          <button class="ti" type="button" title="锁定屏幕" @click="lockScreen">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <rect x="3" y="7" width="10" height="7" rx="1.2" />
              <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
            </svg>
          </button>
          <button class="ti" type="button" :title="`告警：${unacked.length} 条未确认`" @click="goAlarms('unacked')">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M8 2.2a3.6 3.6 0 0 0-3.6 3.6v2.4L3.2 11h9.6l-1.2-2.8V5.8A3.6 3.6 0 0 0 8 2.2Z" />
              <path d="M6.4 12.6a1.6 1.6 0 0 0 3.2 0" />
            </svg>
            <em v-if="unacked.length" class="ti-badge">{{ unacked.length }}</em>
          </button>
          <button class="ti" type="button" title="消息中心" @click="router.push({ name: 'messages' })">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <rect x="2" y="3.5" width="12" height="9" rx="1.2" />
              <path d="M2.4 4.4 8 8.6l5.6-4.2" />
            </svg>
            <em v-if="msgUnread" class="ti-badge">{{ msgUnread }}</em>
          </button>

        </span>
      </div>

      <div class="clock"><b>{{ clock.time }}</b><i>{{ clock.date }}</i></div>

      <div class="sb-right">
        <div class="stat"><label>电量</label><b class="gold"><AnimatedNumber :value="battery" suffix="%" /></b><span class="battery"><i :style="{ width: (battery ?? 0) + '%' }" /></span></div>
        <div class="stat"><label>在线状态</label><b :class="robot.online ? 'green' : 'red'">{{ robot.online ? '在线' : '离线' }}</b></div>
        <div class="stat"><label>重定位状态</label><b class="green">{{ robot.online ? '定位成功' : '未知' }}</b></div>
        <div class="stat"><label>机器人状态</label><b class="gold">{{ mode }}</b></div>
        <div class="stat"><label>服务器状态</label><b class="green">已连接</b></div>
      </div>
    </div>

    <!-- 主体：左视频 / 中地图 / 右统计 -->
    <div class="body">
      <aside class="col left">
        <ScadaPanel title="可见光视频" tone="cyan" class="grow" body-class="no-pad">
          <div class="embed">
            <iframe v-if="visibleStream" :src="visibleStream" title="可见光" allow="autoplay; fullscreen" />
            <div v-else class="embed-empty">
              <b>视频通道未接入</b>
              <span>真机联调后，在「设备管理 → 摄像头」勾选「首页显示」即自动呈现</span>
              <button class="btn btn-sm" @click="router.push({ name: 'cameras' })">去配置</button>
            </div>
            <button class="embed-expand" title="打开视频监控" @click="goVideo(visibleVideo)">打开全屏页 ↗</button>
          </div>
        </ScadaPanel>

        <ScadaPanel title="热红外视频" tone="gold" class="grow" body-class="no-pad">
          <div class="embed">
            <iframe v-if="thermalStream" :src="thermalStream" title="热红外" allow="autoplay; fullscreen" />
            <div v-else class="embed-empty">
              <b>视频通道未接入</b>
              <span>热像仪接上后，勾选「首页显示」即自动呈现</span>
            </div>
            <button class="embed-expand" title="打开视频监控" :disabled="!thermalVideo"
                    @click="goVideo(thermalVideo)">打开全屏页 ↗</button>
          </div>
        </ScadaPanel>

        <ScadaPanel title="实时控制" class="h-ctrl">
          <div class="ctrl-tabs">
            <button :class="{ on: controlTab === 'ptz' }" @click="controlTab = 'ptz'">云台控制</button>
            <button :class="{ on: controlTab === 'chassis' }" @click="controlTab = 'chassis'">车体控制</button>
          </div>
          <div class="ctrl-body">
            <div class="stick" title="点击查看为什么不能操作" @click="tryControl"><span class="knob" /></div>
            <div class="ctrl-meta">
              <div v-if="canStand" class="pose-actions">
                <button class="btn" :disabled="busyMotion" @click="doMotion('stand')">起立</button>
                <button class="btn" :disabled="busyMotion" @click="doMotion('lie')">趴下</button>
              </div>
              <p v-else class="dim small">这台设备不支持起立/趴下</p>
              <div><span>电压</span><b>{{ num(galileo.power, 1) }} V</b></div>
              <div><span>速度</span><b>{{ num(galileo.currentSpeedX) }} m/s</b></div>
              <div><span>角速度</span><b>{{ num(galileo.currentSpeedTheta, 3) }} rad/s</b></div>
              <p class="dim">写操作未开放（需真机联调 + 现场授权签字）</p>
            </div>
          </div>
        </ScadaPanel>
      </aside>

      <main class="col center">
        <ScadaPanel
          title="实时地图"
          :right="`${points.length} 个点位 · ${mapMeta?.resolution?.toFixed(3) ?? '—'} m/px`"
          class="grow map-panel"
        >
          <div class="map-frame">
            <MapCanvas
              :map-meta="mapMeta" :image-url="imageUrl" :points="points"
              :pose="pose" :stale="robot.stale || !robot.online" :trail="trail"
            />
            <span class="scan" />
            <span class="radar" />
          </div>
          <p v-if="mapError" class="red small">{{ mapError }}</p>
        </ScadaPanel>

        <section class="rt">
          <header class="rt-head"><span>实时消息</span></header>
          <div class="rt-body">
            <div class="rt-left">
              <div class="rt-tabs">
                <button :class="{ on: msgTab === 'patrol' }" @click="msgTab = 'patrol'; loadFeed()">
                  巡检消息<i v-if="unread.patrol" class="dot-new" />
                </button>
                <button :class="{ on: msgTab === 'alarm' }" @click="msgTab = 'alarm'; loadFeed()">
                  告警消息<i v-if="unread.alarm" class="dot-new" />
                </button>
                <button :class="{ on: msgTab === 'control' }" @click="msgTab = 'control'; loadFeed()">
                  控制消息<i v-if="unread.control" class="dot-new" />
                </button>
              </div>
              <div class="rt-scroll">
                <table class="rt-tbl">
                  <thead><tr><th>时间</th><th>{{ tabTitle }}</th><th>状态</th></tr></thead>
                  <tbody>
                    <tr v-for="a in msgRows" :key="a.id" class="clickable-row"
                        :title="`${a.ts} 打开详情：${a.link}`" @click="openMsg(a)">
                      <td class="c-time">{{ a.ts.slice(11, 19) || a.ts }}</td>
                      <td class="c-text">
                        <i class="bar" :class="a.level" />
                        <span class="ellipsis">{{ a.text }}</span>
                      </td>
                      <td class="c-badge">
                        <em class="pill" :class="a.level === 'critical' ? 'bad' : a.level === 'warn' ? 'warn' : 'ok'">
                          {{ a.badge }}
                        </em>
                      </td>
                    </tr>
                    <tr v-if="!msgRows.length"><td colspan="3" class="dim">暂无消息</td></tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div class="rt-sep" />

            <aside class="rt-right">
              <div class="rt-tag">今日任务状态</div>
              <div class="rt-line"><span>任务名称</span><b>{{ currentRun?.name || '—' }}</b></div>
              <div class="rt-line"><span>任务状态</span><b>{{ runStatusText }}</b></div>
              <div class="rt-line"><span>当前任务预估剩余时间</span><b>{{ runEta }}</b></div>

              <div class="rt-groups">
                <div class="rt-grow">
                  <b class="gl">巡检任务</b>
                  <span class="gv"><i class="r">{{ runStats.total }}</i><em>总数</em></span>
                  <span class="gv"><i class="w">{{ runStats.planned }}</i><em>待执行</em></span>
                  <span class="gv"><i class="g">{{ runStats.done }}</i><em>已完成</em></span>
                </div>
                <div class="rt-grow">
                  <b class="gl">执行结果</b>
                  <span class="gv"><i class="r">{{ runStats.cancelled }}</i><em>终止</em></span>
                  <span class="gv"><i class="w">{{ runStats.failed }}</i><em>异常</em></span>
                  <span class="gv"><i class="g">{{ runStats.done }}</i><em>正常</em></span>
                </div>
                <div class="rt-grow">
                  <b class="gl">告警</b>
                  <span class="gv"><i class="r">{{ alarmUnacked }}</i><em>未确认</em></span>
                  <span class="gv"><i class="w">{{ alarmCritical }}</i><em>严重</em></span>
                  <span class="gv"><i class="g">{{ alarmAcked }}</i><em>已确认</em></span>
                </div>
              </div>
            </aside>
          </div>
        </section>
      </main>

      <aside class="col right">
        <ScadaPanel title="告警统计" tone="gold" class="h-donut stack-panel" :right="`近7日 ${trendTotal} 条`">
          <div class="donut-row" title="点击查看未确认告警" @click="goAlarms('unacked')">
            <svg viewBox="0 0 100 100" class="donut">
              <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,.14)" stroke-width="13" />
              <circle cx="50" cy="50" r="42" fill="none" stroke="#38e07b" stroke-width="13"
                      :stroke-dasharray="`${donut.green} ${RING_C}`" transform="rotate(-90 50 50)" />
              <circle cx="50" cy="50" r="42" fill="none" stroke="#ffcf3f" stroke-width="13"
                      :stroke-dasharray="`${donut.red} ${RING_C}`" :stroke-dashoffset="-donut.green"
                      transform="rotate(-90 50 50)" />
            </svg>
            <div class="donut-center"><b><AnimatedNumber :value="donut.total" /></b><em>告警总数</em></div>
            <ul class="legend">
              <li><i class="dot gold" />未确认 <b>{{ donut.unacked }}</b></li>
              <li><i class="dot green" />已确认 <b>{{ donut.acked }}</b></li>
            </ul>
          </div>

          <div class="trend-wrap">
            <div class="trend">
              <div v-for="d in trend" :key="d.date" class="trend-col" :title="`${d.date}：严重 ${d.critical} / 注意 ${d.warn}`">
                <div class="bar-stack">
                  <span class="b-crit" :style="{ height: barH(d.critical) + '%' }" />
                  <span class="b-warn" :style="{ height: barH(d.warn) + '%' }" />
                </div>
                <span class="trend-x">{{ d.date.slice(8) }}</span>
              </div>
              <p v-if="!trendTotal" class="dim small">近 7 天没有告警</p>
            </div>
          </div>
        </ScadaPanel>

        <ScadaPanel title="环境数据" tone="cyan" class="grow" :right="envCount ? `${envCount} 项` : '未接入'">
          <div class="env-grid">
            <div v-for="e in envCells" :key="e.label" class="env-cell">
              <span class="env-label">{{ e.label }}</span>
              <span class="env-value" v-if="e.value !== null">
                {{ e.value }}<small>{{ e.unit }}</small>
              </span>
              <span class="env-value empty" v-else>--<small>{{ e.unit }}</small></span>
            </div>
          </div>
          <p v-if="envCount" class="dim small">
            本机 {{ envCount }} 个传感器；未标定阈值的只记录不告警
          </p>
          <p v-else class="dim small">这台设备没有登记传感器</p>
        </ScadaPanel>

        <ScadaPanel title="巡检点位" class="h-points" :right="`${points.length} 点`">
          <ul class="points">
            <li
              v-for="(p, i) in points" :key="i"
              class="clickable-row" :title="`在地图上看点位：${p.name || '点位 ' + String(i + 1).padStart(2, '0')}`"
              @click="goPoint(p)"
            >
              <span class="idx">{{ String(i + 1).padStart(2, '0') }}</span>
              <span class="name">{{ p.name || `点位 ${String(i + 1).padStart(2, '0')}` }}</span>
              <span class="coord">{{ p.x.toFixed(1) }}, {{ p.y.toFixed(1) }}</span>
              <i class="dot green" />
            </li>
            <li v-if="!points.length" class="dim">地图未加载</li>
          </ul>
        </ScadaPanel>
      </aside>
    </div>

    <footer class="footbar">
      <span><i class="dot" :class="robot.online ? 'green' : 'red'" />链路 {{ robot.online ? '正常' : '中断' }}</span>
      <span>数据更新于 {{ robot.snapshot ? new Date(Date.now() - robot.snapshot.age_s * 1000).toLocaleTimeString('zh-CN') : '—' }}（{{ updated }}）</span>
      <span>固件 {{ version }} · 导航源 {{ slam }} · 急停 {{ estop ? '已按下' : '未按下' }}</span>
      <span class="spacer" />
      <span>WebSocket 推送未接入（轮询 1s）</span>
      <span>v0.1.0</span>
    </footer>

    <!-- 锁屏：Teleport 到 body 并压在所有浮层之上，锁住后连菜单都点不到 -->
    <Teleport to="body">
    <div v-if="locked" class="lock-mask">
      <div class="lock-box">
        <div class="lock-icon">🔒</div>
        <h3>屏幕已锁定</h3>
        <p class="dim">输入当前账号密码解锁</p>
        <input
          class="lock-input" type="password" v-model="lockPwd"
          placeholder="密码" @keyup.enter="unlock" autofocus
        />
        <p v-if="lockError" class="red small">{{ lockError }}</p>
        <div class="lock-actions">
          <button class="btn btn-sm" @click="logout">退出登录</button>
          <button class="btn btn-sm primary" :disabled="lockBusy" @click="unlock">解锁</button>
        </div>
        <p class="dim small" style="margin-top:10px">锁定期间无法操作大屏；忘记密码请让管理员在「用户管理」里重置</p>
      </div>
    </div>
    </Teleport>
  </div>
</template>

<style scoped>

.board {
  position: fixed; inset: 0; z-index: 40;
  display: grid;
  grid-template-rows: 54px 40px minmax(0, 1fr) 26px;   /* header/subbar/body/foot 四行 */
  overflow: hidden;   /* 整页固定，滚动只发生在面板内部 */
  color: #dff0ff;
  font-size: 13px;
  background:
    radial-gradient(1100px 520px at 18% -6%, rgba(46, 176, 255, 0.45), transparent 62%),
    radial-gradient(900px 480px at 88% 4%, rgba(0, 226, 255, 0.22), transparent 60%),
    linear-gradient(160deg, #0b6fc4 0%, #005da4 45%, #004274 100%);
}
.board::before {
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background-image:
    repeating-linear-gradient(135deg, rgba(120, 220, 255, 0.05) 0 2px, transparent 2px 90px),
    linear-gradient(rgba(120, 200, 255, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(120, 200, 255, 0.05) 1px, transparent 1px);
  background-size: auto, 58px 58px, 58px 58px;
  mask-image: radial-gradient(circle at 50% 30%, #000 40%, transparent 92%);
}

/* 顶栏 */
.hdr {
  position: relative;
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 12px;
  padding: 0 14px;
  background: linear-gradient(180deg, #0a7ad0, #005da4);
  border-bottom: 1px solid rgba(111, 227, 255, 0.5);
  box-shadow: 0 2px 12px rgba(0, 40, 110, 0.5);
}
.hdr-center { display: flex; align-items: center; gap: 14px; justify-self: center; }
.logo { display: flex; align-items: center; gap: 9px; min-width: 0; }
.brand {
  font-size: 18px; font-weight: 800; letter-spacing: 0.14em;
  background-image: linear-gradient(
    100deg,
    #cfefff 0%, #ffffff 38%, #ffffff 46%, #7fe3ff 50%, #ffffff 54%, #ffffff 62%, #cfefff 100%
  );
  background-size: 300% 100%;
  background-position: 100% 0;
  -webkit-background-clip: text; background-clip: text; color: transparent;
  filter: drop-shadow(0 0 8px rgba(90, 200, 255, 0.45));
  white-space: nowrap;
  animation: brand-shine 6s ease-in-out infinite;
}
@keyframes brand-shine {
  0%, 55% { background-position: 100% 0; }
  100% { background-position: 0% 0; }
}
/* 透明底直接放蓝底上：靠外发光把轮廓托出来 */
.logo-badge {
  display: flex; align-items: center; justify-content: center;
  height: 30px;
}
.logo-img {
  height: 28px; width: auto; max-width: 140px;
  object-fit: contain; display: block;
  /* 亮度保持原样，只拉对比度：边缘更实，蓝底上更容易看出形状 */
  filter: contrast(1.8) saturate(1.1)
          drop-shadow(0 0 5px rgba(190, 240, 255, 0.5));
}
.mark {
  width: 30px; height: 30px; display: grid; place-items: center;
  color: #eaf7ff; font-size: 17px;
  background: linear-gradient(180deg, #2fa9ff, #005da4);
  border: 1px solid rgba(160, 230, 255, 0.8);
  box-shadow: 0 0 12px rgba(80, 200, 255, 0.7);
}
.logo-text { line-height: 1.15; }
.logo-text b { display: block; font-size: 15px; color: #fff; letter-spacing: 0.08em; }
.logo-text i { font-style: normal; font-size: 9.5px; color: #9fd2ff; letter-spacing: 0.18em; }

.tabs { display: flex; gap: 6px; }
.tab {
  position: relative; padding: 6px 20px;
  color: #cfe8ff; font-size: 14px;
  background: linear-gradient(180deg, rgba(20, 130, 220, 0.6), rgba(0, 70, 140, 0.7));
  border: 1px solid rgba(111, 227, 255, 0.45);
  clip-path: polygon(10px 0, 100% 0, calc(100% - 10px) 100%, 0 100%);
  transition: all 0.15s;
}
.tab:hover { color: #fff; border-color: #6fe3ff; }
.tab.active {
  color: #082f66; font-weight: 700;
  background: linear-gradient(180deg, #b9ecff, #4fc3ff);
  box-shadow: 0 0 14px rgba(120, 220, 255, 0.8);
}

.hdr-right { display: flex; align-items: center; gap: 10px; justify-self: end; }

/* 中间大标题（参考图那种带翼的标题组件） */
.board-title {
  display: flex; align-items: center; gap: 14px;
  pointer-events: none;
}
.board-title h1 {
  margin: 0;
  font-size: 26px; font-weight: 800; letter-spacing: 0.22em;
  background: linear-gradient(180deg, #ffffff 35%, #9fe4ff 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
  text-shadow: 0 0 22px rgba(80, 200, 255, 0.5);
  white-space: nowrap;
}
.wing {
  width: 78px; height: 22px; position: relative; opacity: 0.9;
}
.wing::before {
  content: ""; position: absolute; top: 50%; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(160, 235, 255, 0.9));
}
.wing::after {
  content: ""; position: absolute; top: 50%; width: 7px; height: 7px;
  margin-top: -3.5px; background: #9fefff; transform: rotate(45deg);
  box-shadow: 0 0 10px rgba(120, 230, 255, 0.9);
}
.wing.l::after { right: -2px; }
.wing.r::after { left: -2px; }
.wing.l::before { background: linear-gradient(90deg, transparent, rgba(160, 235, 255, 0.9)); }
.wing.r::before { background: linear-gradient(90deg, rgba(160, 235, 255, 0.9), transparent); }
.icon-btn {
  display: inline-flex; align-items: center; gap: 6px;
  color: #cfe8ff; font-size: 12px; padding: 4px 10px;
  border: 1px solid rgba(111, 227, 255, 0.4);
}
.bell { width: 10px; height: 10px; border-radius: 50%; background: #ffcf3f; box-shadow: 0 0 8px rgba(255, 207, 63, 0.9); }
.user { display: flex; align-items: center; gap: 7px; font-size: 13px; }
.avatar {
  width: 24px; height: 24px; border-radius: 50%;
  display: grid; place-items: center;
  background: linear-gradient(180deg, #7fd8ff, #2b9bff);
  color: #062f66; font-weight: 700; font-size: 12px;
}
.logout {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(160, 220, 255, 0.5);
  color: #eaf7ff; font-size: 12px; padding: 4px 10px; cursor: pointer;
}
.logout:hover { background: rgba(255, 255, 255, 0.2); }

/* 状态带 */
.subbar {
  display: grid;
  grid-template-columns: 1fr auto 1fr;   /* 时钟固定在正中间，和标题对齐 */
  align-items: center; gap: 14px;
  padding: 0 16px;
  background: linear-gradient(180deg, rgba(0, 74, 132, 0.94), rgba(0, 58, 110, 0.94));
  border-bottom: 1px solid rgba(64, 176, 255, 0.35);
  font-size: 12px;
  position: relative; z-index: 35;   /* 让场站/设备下拉能盖在主体之上 */
}
.sb-left { display: flex; align-items: center; gap: 12px; justify-self: start; min-width: 0; }
.sb-right { display: flex; align-items: center; gap: 14px; justify-self: end; }
.tool-icons { display: flex; gap: 6px; }
.ti {
  position: relative;
  width: 26px; height: 22px;
  display: inline-flex; align-items: center; justify-content: center;
  padding: 0; line-height: 1;
  background: rgba(0, 90, 170, 0.6);
  border: 1px solid rgba(111, 227, 255, 0.35);
  color: #dff0ff; cursor: pointer;
  transition: all 0.15s;
}
.ti svg {
  width: 13px; height: 13px; display: block;
  fill: none; stroke: currentColor; stroke-width: 1.4;
  stroke-linecap: round; stroke-linejoin: round;
}
.ti:hover { color: #fff; }
.ti:hover { border-color: #7fe9ff; box-shadow: 0 0 8px rgba(80, 200, 255, 0.5); }
.ti-badge {
  position: absolute; top: -6px; right: -6px;
  min-width: 14px; height: 14px; line-height: 14px;
  padding: 0 3px; border-radius: 7px;
  background: #ff5a5a; color: #fff; font-size: 9.5px; font-style: normal;
}

.lock-mask {
  position: fixed; inset: 0; z-index: 2147483100;
  display: grid; place-items: center;
  background: rgba(2, 12, 28, 0.72);
  backdrop-filter: blur(6px);
}
.lock-box {
  width: 320px; padding: 22px 22px 18px;
  text-align: center;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
  box-shadow: 0 0 40px rgba(0, 60, 140, 0.8);
}
.lock-icon { font-size: 26px; margin-bottom: 6px; }
.lock-box h3 { margin: 0 0 4px; font-size: 15px; color: #fff; }
.lock-box p { margin: 0 0 10px; font-size: 12px; }
.lock-input {
  width: 100%; padding: 8px 10px; margin-bottom: 8px;
  background: rgba(0, 45, 90, 0.7); color: #eaf7ff;
  border: 1px solid rgba(111, 227, 255, 0.45); outline: none;
}
.lock-input:focus { border-color: #7fe9ff; box-shadow: 0 0 10px rgba(80, 200, 255, 0.45); }
.lock-actions { display: flex; justify-content: center; gap: 8px; margin-top: 4px; }
.field { display: flex; align-items: center; gap: 6px; }
.field label { color: #8fc4f0; }
.select {
  padding: 3px 10px; color: #eaf7ff;
  background: rgba(0, 110, 200, 0.75);
  border: 1px solid rgba(111, 227, 255, 0.45);
}
.sep { width: 1px; height: 16px; background: rgba(120, 200, 255, 0.3); }
.clock { display: flex; flex-direction: column; line-height: 1.15; text-align: center; min-width: 120px; }
.clock b { font-size: 15px; color: #fff; font-variant-numeric: tabular-nums; }
.clock i { font-style: normal; font-size: 10px; color: #9fd2ff; }
.stat { display: flex; align-items: center; gap: 5px; white-space: nowrap; }
.stat label { color: #8fc4f0; }
.stat b { font-weight: 600; }
.battery {
  width: 44px; height: 8px; margin-left: 2px;
  border: 1px solid rgba(160, 220, 255, 0.6);
  display: inline-block; position: relative;
}
.battery i { position: absolute; left: 0; top: 0; bottom: 0; background: linear-gradient(90deg, #7dff9a, #22e06b); }

/* 主体 */
.body {
  position: relative;
  display: grid;
  /* 中栏比原来窄 8%，让左侧视频/控制更大一些 */
  grid-template-columns: clamp(330px, 24.4vw, 440px) minmax(0, 0.92fr) clamp(320px, 24vw, 430px);
  grid-template-rows: minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  min-height: 0;
}
.body { min-height: 0; }
.col { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
.grow { flex: 1; min-height: 0; }
.left .panel.grow { flex: 1 1 0; }   /* 可见光/热红外等高 */
.col.center { display: grid; grid-template-rows: minmax(0, 1fr) auto; }
.h-ctrl { height: 172px; flex: none; }
.h-donut { height: 208px; flex: none; }
.h-points { height: 176px; flex: none; }
.h-msg { height: 244px; flex: none; }
.h-msg :deep(.panel-body) { padding: 0; }
.msg-split { display: grid; grid-template-columns: 5.8fr 4.2fr; height: 100%; min-height: 0; }
.msg-main { min-width: 0; overflow: auto; }
.msg-side {
  padding: 4px 10px 8px; border-left: 1px solid rgba(111, 227, 255, .22);
  display: flex; flex-direction: column; gap: 1px; font-size: 11px; overflow: hidden;
}
.ms-head { color: #8ef0ff; font-weight: 600; letter-spacing: 1px; }
.ms-row { display: flex; justify-content: space-between; gap: 6px; align-items: baseline; font-size: 11px; line-height: 1.35; }
.ms-row b { max-width: 62%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: right; }
.ms-row span { color: #bfe6ff; }
.ms-row b { color: #f2fbff; font-weight: 600; }
.ms-counts { display: grid; grid-template-columns: repeat(5, 1fr); gap: 3px; margin-top: 2px; }
.ms-counts div { text-align: center; background: rgba(0, 90, 160, .35); border-radius: 3px; padding: 2px 0; }
.ms-counts b { display: block; font-size: 14px; color: #f2fbff; line-height: 1.15; }
.ms-counts span { font-size: 9.5px; color: #9fd2ff; line-height: 1.1; display: block; }

.no-pad { padding: 6px !important; }
.clickable { height: 100%; cursor: pointer; }

/* 控制面板 */
.ctrl-tabs { display: flex; gap: 6px; margin-bottom: 8px; }
.ctrl-tabs button {
  flex: 1; padding: 4px 0; font-size: 12px; cursor: default;
  color: #9fd2ff; background: rgba(0, 90, 170, 0.55);
  border: 1px solid rgba(111, 227, 255, 0.35);
}
.ctrl-tabs button.on {
  color: #062f66; font-weight: 700;
  background: linear-gradient(180deg, #b9ecff, #4fc3ff);
}
.ctrl-body { display: flex; gap: 12px; align-items: center; }
.stick {
  width: 84px; height: 84px; flex: none; border-radius: 50%;
  border: 1px solid rgba(111, 227, 255, 0.45);
  background: radial-gradient(circle, rgba(20, 110, 200, 0.55), rgba(0, 40, 90, 0.7));
  display: grid; place-items: center; position: relative;
}
.stick::before, .stick::after {
  content: ""; position: absolute; background: rgba(111, 227, 255, 0.25);
}
.stick::before { left: 50%; top: 10%; bottom: 10%; width: 1px; }
.stick::after { top: 50%; left: 10%; right: 10%; height: 1px; }
.knob {
  width: 28px; height: 28px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #b9ecff, #2b9bff);
  box-shadow: 0 0 14px rgba(80, 200, 255, 0.8);
}
.ctrl-meta { display: flex; flex-direction: column; gap: 3px; font-size: 12px; }
.ctrl-meta div { display: flex; justify-content: space-between; gap: 12px; }
.ctrl-meta span { color: #9fd2ff; }
.ctrl-meta b { color: #eaf7ff; font-weight: 600; }
.ctrl-meta p {
  margin: 4px 0 0; font-size: 10.5px;
  color: #8fc4f0;
  max-width: 190px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 地图扫码 */
.map-frame { position: relative; flex: 1 1 auto; min-height: 0; }
.map-frame :deep(.map-wrap) { position: absolute; inset: 0; height: auto; min-height: 0; }
.scan {
  position: absolute; left: 0; right: 0; height: 34%;
  background: linear-gradient(180deg, transparent, rgba(120, 230, 255, 0.16), transparent);
  animation: sweep 5s linear infinite; pointer-events: none;
}
@keyframes sweep { 0% { top: -35%; } 100% { top: 100%; } }
/* 雷达扫描扇面 */
.radar {
  position: absolute; inset: 0; pointer-events: none;
  background: conic-gradient(from 0deg at 50% 50%, rgba(120, 255, 220, 0.22), transparent 22%, transparent 100%);
  animation: radar 6s linear infinite;
  mix-blend-mode: screen;
  opacity: 0.45;
}
@keyframes radar { to { transform: rotate(360deg); } }

/* 环形图 */
.donut-row { display: flex; align-items: center; gap: 12px; position: relative; flex: none; }
.donut { width: 88px; height: 88px; flex: none; }
.donut-center {
  position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  width: 88px; text-align: center; pointer-events: none;
}
.donut-center b { display: block; font-size: 18px; line-height: 1.1; color: #ffd54a; font-weight: 800; }
.donut-center em { font-style: normal; font-size: 10px; color: #9fd2ff; }
.legend { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; font-size: 12px; }
.legend li { display: flex; align-items: center; gap: 6px; color: #cfe8ff; }
.legend b { margin-left: auto; color: #fff; font-size: 14px; }

/* 告警趋势（空坐标系，不画假曲线） */
.trend-wrap { margin-top: 4px; flex: none; }
.trend { position: relative; height: 46px; display: flex; align-items: stretch; gap: 4px; }
.t-head { display: flex; justify-content: space-between; font-size: 10.5px; color: #9fd2ff; margin-bottom: 2px; }
.t-head em { font-style: normal; color: #ffe08a; }
.t-plot {
  position: relative; flex: 1; min-height: 54px;
  display: grid; place-items: center;
  border: 1px solid rgba(111, 227, 255, 0.18);
  background:
    repeating-linear-gradient(0deg, rgba(111, 227, 255, 0.12) 0 1px, transparent 1px 20px),
    linear-gradient(180deg, rgba(0, 90, 170, 0.25), rgba(0, 50, 100, 0.25));
}
.t-plot span { font-size: 11px; color: #6f9ec9; }

/* 环境 */
.env-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 10px; align-content: center; flex: 1; }
.env-cell {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 8px;
  background: linear-gradient(180deg, rgba(0, 110, 190, 0.45), rgba(0, 70, 140, 0.55));
  border: 1px solid rgba(111, 227, 255, 0.22);
}
.env-label { font-size: 11px; color: #cfeaff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.env-value { font-size: 15px; color: #f2fbff; font-weight: 600; text-shadow: 0 0 8px rgba(120, 225, 255, 0.45); font-variant-numeric: tabular-nums; }
.env-value small { font-size: 10px; margin-left: 2px; color: #9fe0ff; font-weight: 400; text-shadow: none; }
.env-value.empty { color: #7fb6dd; font-weight: 400; text-shadow: none; }

/* 点位 */
.points { list-style: none; margin: 0; padding: 0; }
.t-panel:has(.points) :deep(.t-body) { overflow-y: auto; }
.clickable-row { cursor: pointer; }
.points li {
  display: flex; align-items: center; gap: 9px;
  padding: 5px 6px; font-size: 12.5px;
  border-bottom: 1px dashed rgba(140, 210, 255, 0.18);
}
/* 点位多时在面板内滚动，不把页面顶长 */
.t-panel:has(.points) :deep(.t-body) { max-height: 100%; }
.points .idx {
  width: 22px; height: 18px; display: grid; place-items: center;
  font-size: 10.5px; color: #062f66; font-weight: 700;
  background: linear-gradient(180deg, #9fe4ff, #48b6ff);
}
.points .name { color: #eaf7ff; }
.points .coord { margin-left: auto; color: #9fd2ff; font-size: 11px; }

/* ---------- 响应式：窄屏/矮屏都不挤爆 ---------- */
@media (max-width: 1560px) {
  .brand { font-size: 16px; letter-spacing: 0.08em; }
  .hdr-center { gap: 10px; }
  .board-title h1 { font-size: 15px; letter-spacing: 0.04em; }
  .wing { width: 14px; }
}
@media (max-width: 1780px) {
  .board-title h1 { font-size: clamp(15px, 1.25vw, 20px); letter-spacing: 0.08em; }
  .wing { width: 22px; }
  .tab { padding: 5px 12px; font-size: 13px; }
  .logo-text i { display: none; }
}

@media (max-width: 1600px) {
  .tab { padding: 4px 10px; font-size: 12.5px; }
  .board-title { gap: 10px; }
  .wing { width: 16px; }
  .stat { gap: 4px; font-size: 11.5px; }
  .subbar { gap: 10px; }
}

@media (max-width: 1440px) {
  .hdr { gap: 8px; }
  .board-title h1 { font-size: clamp(13px, 1.15vw, 16px); letter-spacing: 0.06em; }
  .user { display: none; }
  .h-ctrl { height: 182px; }
  .h-donut { height: 196px; }
  .h-points { height: 168px; }
  .h-msg { height: 216px; }
}

/* 窄屏：仍保持固定三列，靠压缩列宽 + 面板内滚，不整页滚 */
@media (max-width: 1240px) {
  /* 列宽用 minmax(0,…)：宁可压缩内容，也不撑破整页 */
  .body { grid-template-columns: minmax(0, 280px) minmax(0, 1fr) minmax(0, 250px); gap: 8px; padding: 8px; }
  .col, .t-panel { min-width: 0; }
  .logo-text { display: none; }
  .hdr { grid-template-columns: auto auto minmax(0, 1fr) auto; }
  .subbar { gap: 8px; overflow: hidden; }
  .sb-left { min-width: 0; }
  .sb-right { gap: 8px; }
  .stat label { display: none; }        /* 状态带只留值，省宽度 */
  .clock i { display: none; }
  .tabs .tab:nth-child(n + 4) { display: none; }
  .h-ctrl { height: 168px; }
  .h-donut { height: 190px; }
  .h-points { height: 160px; }
  .h-msg { height: 200px; }
}

@media (max-width: 1240px) {
  /* 窄列里别让文字折行，宁可变小 */
  .legend li, .env-label, .ctrl-meta div, .points .name { white-space: nowrap; }
  .legend { font-size: 11px; gap: 5px; }
  .legend b { font-size: 12px; }
  .env-label { font-size: 10.5px; }
  .env-value { font-size: 13px; }
  .env-cell { padding: 5px 6px; }
  .ctrl-meta { font-size: 11px; }
  .ctrl-meta p { display: none; }
  .stick { width: 64px; height: 64px; }
  .donut { width: 92px; height: 92px; }
  .donut-center { width: 92px; }
  .donut-center b { font-size: 20px; }
}

@media (max-width: 1100px) {
  .body { grid-template-columns: minmax(0, 230px) minmax(0, 1fr) minmax(0, 210px); }
  .board-title h1 { font-size: 12px; letter-spacing: 0; }
  .sb-right .stat:nth-child(n + 4) { display: none; }
}

@media (max-width: 860px) {
  .hdr { grid-template-columns: auto auto 1fr; }
  .board-title h1 { font-size: 12px; letter-spacing: 0; }
  .wing { display: none; }
  .col.left, .col.right { grid-template-columns: minmax(0, 1fr); }
  .icon-btn, .logout { display: none; }
}

/* 面板内容底部渐隐：暗示还能往下滚 */
.t-panel :deep(.t-body) {
  scrollbar-width: thin;
  background-image: linear-gradient(180deg, transparent calc(100% - 18px), rgba(0, 30, 70, 0.55));
  background-attachment: local;
}

/* 表格 */
.tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.tbl th {
  text-align: left; padding: 5px 8px; font-weight: 600; color: #cfe8ff;
  background: linear-gradient(180deg, rgba(32, 140, 230, 0.85), rgba(0, 92, 170, 0.85));
  border: 1px solid rgba(111, 227, 255, 0.25);
}
.tbl td { padding: 5px 8px; color: #dff0ff; border: 1px solid rgba(111, 227, 255, 0.14); }
.tbl tbody tr:nth-child(even) td { background: rgba(0, 80, 150, 0.35); }
.tbl .strong { color: #fff; }

.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; margin-right: 4px; background: #9fd2ff; }
.dot.green { background: #38e07b; box-shadow: 0 0 7px rgba(56, 224, 123, 0.9); }
.dot.red { background: #ff5a5a; box-shadow: 0 0 7px rgba(255, 90, 90, 0.9); }
.dot.gold { background: #ffcf3f; box-shadow: 0 0 7px rgba(255, 207, 63, 0.9); }

.footbar {
  display: flex; align-items: center; gap: 20px;
  padding: 0 14px; font-size: 11px; color: #9fd2ff;
  background: rgba(0, 58, 110, 0.92);
  border-top: 1px solid rgba(64, 176, 255, 0.35);
}
.spacer { flex: 1; }
.small { font-size: 12px; }
.dim { color: #9fd2ff; }
.gold { color: #ffd54a; }
.green { color: #7dff9a; }
.red { color: #ff8a8a; }

/* 首页内嵌视频 */
.embed { position: relative; width: 100%; height: 100%; background: #04101f; }
.embed iframe { width: 100%; height: 100%; border: 0; display: block; }
.embed-empty {
  height: 100%; display: flex; flex-direction: column; gap: 8px;
  align-items: center; justify-content: center; text-align: center; padding: 12px;
}
.embed-empty b { color: #cfe9ff; font-size: 13px; }
.embed-empty span { color: #7fa8cc; font-size: 11.5px; }
.embed-expand {
  position: absolute; right: 8px; bottom: 8px;
  background: rgba(0, 40, 80, 0.78); color: #cfe9ff;
  border: 1px solid rgba(111, 227, 255, 0.4); border-radius: 4px;
  padding: 3px 8px; font-size: 11px; cursor: pointer;
}
.embed-expand:hover { border-color: #7fe9ff; color: #fff; }

/* 近 7 日告警趋势柱 */
.trend { position: relative; height: 46px; display: flex; align-items: stretch; gap: 4px; }
.trend-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: 2px; min-height: 0; }
.trend-col .bar-stack {
  flex: 1 1 auto; width: 72%; min-height: 0;
  display: flex; flex-direction: column; justify-content: flex-end; gap: 1px;
}
.trend-col .bar-stack span { display: block; width: 100%; border-radius: 1px 1px 0 0; }
.trend-col .b-crit { background: linear-gradient(180deg, #ff8a8a, #d9342b); }
.trend-col .b-warn { background: linear-gradient(180deg, #ffe066, #d9a300); }
.trend-x { font-size: 9px; color: #6f9dc4; line-height: 1; }
.trend p { position: absolute; inset: 0; display: grid; place-items: center; margin: 0; }

/* 实时消息表格：级别/状态不换行，内容列吃剩余宽度 */
.msg-main .tbl th:nth-child(1), .msg-main .tbl td:nth-child(1) { width: 72px; }
.msg-main .tbl th:nth-child(2), .msg-main .tbl td:nth-child(2) { width: 70px; white-space: nowrap; }
.msg-main .tbl th:nth-child(4), .msg-main .tbl td:nth-child(4) { width: 74px; white-space: nowrap; }
.msg-main .tbl td:nth-child(3) { white-space: normal; }

/* ===== 实时消息：按参考图（工业蓝+青+橙）重做 ===== */
.h-msg :deep(.panel-body) { padding: 0; }
.h-msg .tbl th {
  background: linear-gradient(180deg, #0d2a52, #0a244b);
  color: #eaf3ff; font-size: 12.5px; font-weight: 700; letter-spacing: .5px;
  border: 1px solid rgba(37, 116, 187, .75);
}
.h-msg .tbl td {
  font-size: 12.5px; color: #eaf3ff;
  border: 1px solid rgba(37, 116, 187, .55);
  padding: 7px 8px;
}
.h-msg .tbl tbody tr:nth-child(even) td { background: transparent; }
.h-msg .tbl tbody tr:hover td { background: rgba(47, 224, 240, .12); }
.msg-side {
  background: linear-gradient(180deg, rgba(8, 32, 64, .55), rgba(6, 24, 48, .35));
  border-left: 2px solid rgba(37, 116, 187, .8);
}
.ms-head {
  color: #ffc23c; font-weight: 700; letter-spacing: 1.5px; font-size: 12px;
  padding-bottom: 2px; border-bottom: 1px solid rgba(37, 116, 187, .5);
}
.ms-row span { color: #7fd8ff; font-size: 11.5px; }
.ms-row b { color: #ffb62e; font-weight: 700; font-size: 12px; }
.ms-counts { gap: 4px; }
.ms-counts div {
  background: rgba(6, 26, 54, .55);
  border: 1px solid rgba(37, 116, 187, .45);
  border-radius: 2px; padding: 3px 0 2px;
}
.ms-counts b { font-size: 15px; font-weight: 700; }
.ms-counts b.c-total { color: #ff6a6e; }
.ms-counts b.c-plan { color: #ff6a6e; }
.ms-counts b.c-cancel { color: #9fb8d0; }
.ms-counts b.c-done { color: #4dff46; }
.ms-counts b.c-fail { color: #ff4b45; }
.ms-counts span { color: #8fb7d8; font-size: 9.5px; }

/* ===== 实时消息：按参考图重做（豆包视觉说明） ===== */
.h-msg { position: relative; }
.h-msg :deep(.panel-body) { padding: 0; overflow: hidden; }
.h-msg :deep(.panel-title) {
  background: linear-gradient(180deg, #1e6fae 0%, #0b2b55 100%);
  box-shadow: inset 0 1px 0 rgba(160, 240, 255, .55);
}
.msg-split { display: grid; grid-template-columns: 6fr 4fr; height: 100%; min-height: 0; }
.msg-main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }

/* 三个 tab：选中亮青底深字，未选深蓝底浅字 */
.msg-tabs { display: flex; gap: 3px; padding: 5px 6px 3px; flex: none; }
.msg-tabs button {
  flex: 1; padding: 4px 6px; font-size: 11.5px; font-weight: 600; cursor: pointer;
  color: #bfd9ef; background: #0a2247; border: 1px solid rgba(37, 116, 187, .7);
  border-radius: 2px; letter-spacing: .5px;
}
.msg-tabs button.on { background: #2fe0f0; color: #06253f; border-color: #7ff0ff; }

.h-msg .tbl { table-layout: fixed; width: 100%; }
.h-msg .tbl th {
  background: #0a244b; color: #eaf3ff; font-size: 12px; font-weight: 700;
  border: 1px solid rgba(37, 116, 187, .75); padding: 5px 8px;
}
.h-msg .tbl th:nth-child(1) { width: 108px; }
.h-msg .tbl td {
  border: 1px solid rgba(37, 116, 187, .55); padding: 6px 8px;
  color: #eaf3ff; font-size: 12px; white-space: normal; line-height: 1.45;
}
.h-msg .tbl tbody tr:nth-child(even) td { background: transparent; }
.h-msg .tbl tbody tr:hover td { background: rgba(47, 224, 240, .12); }
.h-msg .tbl .t-time { color: #cfe6ff; font-variant-numeric: tabular-nums; white-space: nowrap; }
.h-msg .tbl .t-state { font-style: normal; font-size: 10.5px; margin-left: 6px; padding: 0 4px; border-radius: 2px; }
.h-msg .tbl .t-state.ok { color: #4dff46; border: 1px solid rgba(77, 255, 70, .5); }
.h-msg .tbl .t-state.bad { color: #ff6a6e; border: 1px solid rgba(255, 106, 110, .5); }

/* 右侧任务区：浅青标签 + 橙黄数值 + 三组红/绿计数 */
.msg-side {
  padding: 6px 10px 8px; border-left: 2px solid rgba(37, 116, 187, .85);
  background: linear-gradient(180deg, rgba(10, 36, 75, .75), rgba(7, 25, 50, .55));
  display: flex; flex-direction: column; gap: 4px; min-height: 0; overflow: hidden;
}
.ms-tag {
  align-self: flex-end; background: #36cbe6; color: #06264a; font-weight: 700;
  font-size: 11.5px; padding: 3px 9px; border-radius: 2px;
  box-shadow: 0 0 10px rgba(54, 203, 230, .55); letter-spacing: 1px;
}
.ms-line { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; font-size: 11.5px; }
.ms-line span { color: #7fd8ff; }
.ms-line b {
  color: #ffb62e; font-weight: 700; max-width: 58%; text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ms-groups { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: auto; }
.ms-group { border: 1px solid rgba(37, 116, 187, .55); border-radius: 2px; padding: 3px 4px; }
.ms-group .nums { text-align: center; font-size: 15px; font-weight: 700; letter-spacing: 1px; color: #8fb7d8; }
.ms-group .nums i { font-style: normal; text-shadow: 0 0 8px currentColor; }
.ms-group .nums .r { color: #ff6a6e; }
.ms-group .nums .g { color: #4dff46; }
.ms-group .caps { display: flex; justify-content: space-around; font-size: 9px; color: #8fb7d8; }

/* ===== 实时消息：1:1 复刻参考（配色用豆包给出的精确值） ===== */
.rt {
  height: auto; flex: none;   /* 高度由内容决定，不留底部空白，地图吃剩余空间 */ display: flex; flex-direction: column;
  background: #0f2b52; border: 1px solid #3098e8; border-radius: 3px;
  box-shadow: 0 0 0 1px rgba(48, 152, 232, .25), 0 0 12px rgba(48, 152, 232, .18);
  overflow: hidden;
}
.rt-head {
  height: 26px; flex: none; display: grid; place-items: center;
  background: linear-gradient(180deg, #1760a8, #0d335f);
  border-bottom: 1px solid #3098e8;
}
.rt-head span {
  color: #ffd040; font-weight: 700; font-size: 14px; letter-spacing: 3px;
  text-shadow: 0 0 8px rgba(255, 208, 64, .35);
}
/* 左栏比原来窄约 12%（70%→62%），右栏随之左移变宽 */
.rt-body { flex: 1; min-height: 0; display: grid; align-items: stretch; grid-template-columns: 6.2fr 1px 3.8fr; }
.rt-left { min-width: 0; display: flex; flex-direction: column; }
.rt-tabs { display: flex; gap: 0; padding: 6px 8px 5px; flex: none; }
.rt-tabs button {
  padding: 4px 14px; font-size: 12px; font-weight: 600; cursor: pointer;
  color: #ffffff; background: #0b2344; border: 1px solid #3098e8; border-radius: 3px;
  margin-right: 4px;
}
.rt-tabs button.on { background: #54b8f5; color: #ffffff; border-color: #7fd0ff; }
.rt-scroll { min-height: 0; max-height: 138px; overflow-y: auto; overflow-x: hidden; scrollbar-width: thin; }
.rt-scroll::-webkit-scrollbar { width: 6px; }
.rt-scroll::-webkit-scrollbar-thumb { background: #2f7fc4; border-radius: 3px; }
.rt-tbl { width: 100%; border-collapse: collapse; table-layout: fixed; }
.rt-tbl th {
  color: #ffffff; font-size: 12px; font-weight: 700; text-align: left;
  background: #0b2344; border: 1px solid #3098e8; padding: 5px 8px;
}
.rt-tbl th:first-child { width: 132px; }
.rt-tbl td {
  color: #ffffff; font-size: 11.5px; line-height: 1.45; padding: 5px 8px;
  border: 1px solid rgba(48, 152, 232, .6); word-break: break-all;
}
.rt-tbl .c-time { color: #ffffff; font-variant-numeric: tabular-nums; white-space: nowrap; }
.rt-tbl .st { font-style: normal; margin-left: 6px; font-size: 11px; }
.rt-tbl .st.g { color: #30d040; }
.rt-tbl .st.r { color: #ff3333; }
.rt-tbl tbody tr:hover td { background: rgba(84, 184, 245, .14); }

.rt-sep { background: #3098e8; }
.rt-right { padding: 5px 8px 6px; display: flex; flex-direction: column; gap: 4px; min-height: 0; overflow: hidden; }
.rt-tag {
  align-self: flex-end; background: #54b8f5; color: #ffffff; font-weight: 700;
  font-size: 11.5px; padding: 2px 10px; border-radius: 3px; letter-spacing: 1px;
}
.rt-line {
  display: flex; justify-content: space-between; gap: 10px; align-items: baseline;
  font-size: 11.5px; line-height: 1.4;
  padding: 5px 0;                      /* 行间留白 */
  border-bottom: 1px dashed rgba(48, 152, 232, .45);   /* 行分隔线 */
}
.rt-line:last-of-type { border-bottom: 0; }
.rt-line span { color: #71f9ff; white-space: nowrap; font-weight: 700; }
.rt-line b {
  color: #f7c355; font-weight: 800; letter-spacing: .3px; text-align: right; max-width: 62%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rt-groups {
  display: flex; flex-direction: column; gap: 2px; margin-top: 4px; flex: none;
  border-top: 1px solid #3098e8; padding-top: 5px;
}
.rt-grow { display: grid; grid-template-columns: 60px repeat(3, 1fr); align-items: baseline; white-space: nowrap; }
.rt-grow .gl { color: #71f9ff; font-size: 11px; font-weight: 700; }
.rt-grow .gv { display: inline-flex; align-items: baseline; gap: 3px; justify-content: flex-start; }
.rt-grow .gv i { font-style: normal; font-size: 16px; font-weight: 800; font-variant-numeric: tabular-nums; }
.rt-grow .gv em { font-style: normal; color: #9fc4e8; font-size: 8.5px; }
.rt-grow .gv i.r { color: #ff3333; text-shadow: 0 0 8px rgba(255, 51, 51, .4); }
.rt-grow .gv i.w { color: #ffffff; }
.rt-grow .gv i.g { color: #30d040; text-shadow: 0 0 8px rgba(48, 208, 64, .4); }


/* 三列消息表：色条 + 省略 + 状态 pill */
.rt-tbl th:nth-child(1) { width: 74px; }
.rt-tbl th:nth-child(3) { width: 66px; }
.rt-tbl .c-time { color: #cfe6ff; white-space: nowrap; }
.rt-tbl .c-text { display: flex; align-items: center; gap: 6px; }
.rt-tbl .c-text .bar { flex: none; width: 3px; height: 13px; border-radius: 1px; background: #3a6f9e; }
.rt-tbl .c-text .bar.critical { background: #ff3333; box-shadow: 0 0 6px rgba(255,51,51,.6); }
.rt-tbl .c-text .bar.warn { background: #ffa82e; }
.rt-tbl .c-text .ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rt-tbl .c-badge { text-align: center; }
.rt-tbl .pill { font-style: normal; font-size: 10.5px; padding: 1px 6px; border-radius: 2px; }
.rt-tbl .pill.bad { color: #fff; background: #d33; }
.rt-tbl .pill.warn { color: #06253f; background: #ffa82e; }
.rt-tbl .pill.ok { color: #4dff46; border: 1px solid rgba(77,255,70,.55); }
.rt-tabs .dot-new {
  display: inline-block; width: 6px; height: 6px; margin-left: 4px; border-radius: 50%;
  background: #ff3b3b; box-shadow: 0 0 6px #ff3b3b; vertical-align: middle;
}
</style>
