<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import MapCanvas from '@/components/MapCanvas.vue'
import ScadaPanel from '@/components/ScadaPanel.vue'
import VideoBox from '@/components/VideoBox.vue'
import AnimatedNumber from '@/components/AnimatedNumber.vue'
import DarkSelect from '@/components/DarkSelect.vue'
import TopNav from '@/components/TopNav.vue'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { useRobotStore } from '@/stores/robot'
import { api, type MapMeta, type NavPoint } from '@/api'

const robot = useRobotStore()
const auth = useAuthStore()
const router = useRouter()

const mapMeta = ref<MapMeta | null>(null)
const points = ref<NavPoint[]>([])
const trail = ref<{ x: number; y: number }[]>([])
const mapError = ref('')
const now = ref(new Date())
const controlTab = ref<'ptz' | 'chassis'>('ptz')

const sites = [
  { value: 'qz-04', label: '泰安 · 泉州石化-04' },
  { value: 'dy-03', label: '东营 · 泉州石化-03' },
  { value: 'hb', label: '湖北荆州' },
]
const site = ref('qz-04')
const deviceId = ref('1')
const devices = ref([{ value: '1', label: 'JCROB-01' }])

function onSite(v: string) {
  site.value = v
  if (v !== 'qz-04') toast('该场站暂无机器人接入，仍显示当前设备', 'warn')
}
function onDevice(v: string) {
  deviceId.value = v
  toast('已切换到 ' + (devices.value.find((d) => d.value === v)?.label ?? v), 'ok')
}
function openVideo(which: string) {
  toast(`${which}通道未接入：真机联调后按 RTSP / WebRTC 接入`, 'warn', 3000)
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

const envCells = [
  { label: '温度', unit: '℃' },
  { label: '湿度', unit: '%RH' },
  { label: '可燃气体', unit: 'ppm' },
  { label: '烟雾', unit: 'ppm' },
  { label: 'PM2.5', unit: 'μg/m³' },
  { label: '噪声', unit: 'dB' },
]

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
  await loadMap()
  try {
    const list = await api.robots()
    if (list.length) devices.value = list.map((r) => ({ value: String(r.id), label: r.name }))
  } catch { /* 设备列表失败不影响大屏 */ }
  timers.push(window.setInterval(() => { now.value = new Date() }, 1000))
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
      <div class="hdr-left">
        <div class="logo">
          <span class="mark">◈</span>
          <div class="logo-text">
            <b>防爆巡检</b>
            <i>JCROB</i>
          </div>
        </div>
        <TopNav :start="0" :end="3" />
      </div>

      <div class="board-title">
        <span class="wing l" />
        <h1>智能巡检机器人管理平台</h1>
        <span class="wing r" />
      </div>

      <div class="hdr-right">
        <TopNav :start="3" />
        <router-link class="icon-btn" :to="{ name: 'alarms' }" title="告警">
          <span class="bell" />{{ unacked.length }}
        </router-link>
        <div class="user">
          <span class="avatar">{{ (auth.user?.username ?? 'A').slice(0, 1).toUpperCase() }}</span>
        </div>
        <button class="logout" @click="logout">退出</button>
      </div>
    </header>

    <!-- 状态带：左选择器 / 中时钟 / 右状态（参考图就是靠右） -->
    <div class="subbar">
      <div class="sb-left">
        <div class="field"><label>当前场站</label><DarkSelect :model-value="site" :options="sites" width="190px" @update:model-value="onSite" /></div>
        <div class="field"><label>当前设备</label><DarkSelect :model-value="deviceId" :options="devices" width="170px" @update:model-value="onDevice" /></div>
        <span class="tool-icons">
          <i class="ti">🔒</i><i class="ti">🔔</i><i class="ti">✉</i>
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
          <div class="clickable" @click="openVideo('可见光')">
            <VideoBox title="可见光" hint="海康可见光通道接入后播放" />
          </div>
        </ScadaPanel>

        <ScadaPanel title="热红外视频" tone="gold" class="grow" body-class="no-pad">
          <div class="clickable" @click="openVideo('热红外')">
            <VideoBox title="热红外" hint="热成像通道接入后播放" />
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

        <ScadaPanel title="实时消息" tone="violet" class="h-msg" right="查看全部 →">
          <table class="tbl">
            <thead><tr><th>时间</th><th>级别</th><th>内容</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="a in robot.alarms.slice(0, 6)" :key="a.id">
                <td>{{ a.started_at.slice(11, 19) }}</td>
                <td><i class="dot" :class="a.level === 'critical' ? 'red' : 'gold'" />{{ a.level === 'critical' ? '严重' : '提醒' }}</td>
                <td class="strong">{{ a.message }}</td>
                <td :class="a.acked_at ? 'green' : 'red'">{{ a.acked_at ? '已确认' : '未确认' }}</td>
              </tr>
              <tr v-if="!robot.alarms.length">
                <td colspan="4" class="dim">暂无消息 · 环境类阈值未标定，不会产生环境告警</td>
              </tr>
            </tbody>
          </table>
        </ScadaPanel>
      </main>

      <aside class="col right">
        <ScadaPanel title="告警统计" tone="gold" class="h-donut stack-panel">
          <div class="donut-row">
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

          <div class="trend">
            <div class="t-head"><span>近 7 日告警趋势</span><em>待接入</em></div>
            <div class="t-plot"><span>历史数据未接入，接入后自动绘制</span></div>
          </div>
        </ScadaPanel>

        <ScadaPanel title="环境数据" tone="cyan" class="grow" right="未接入">
          <div class="env-grid">
            <div v-for="e in envCells" :key="e.label" class="env-cell">
              <span class="env-label">{{ e.label }}</span>
              <span class="env-value">--<small>{{ e.unit }}</small></span>
            </div>
          </div>
          <p class="dim small">环境传感 WebSocket 未接入，真机联调后自动呈现</p>
        </ScadaPanel>

        <ScadaPanel title="巡检点位" class="h-points" :right="`${points.length} 点`">
          <ul class="points">
            <li v-for="(p, i) in points" :key="i">
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
  </div>
</template>

<style scoped>
.board {
  position: fixed; inset: 0; z-index: 40;
  display: grid;
  grid-template-rows: 54px 40px minmax(0, 1fr) 26px;
  overflow: auto;
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
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  background: linear-gradient(180deg, #0a7ad0, #005da4);
  border-bottom: 1px solid rgba(111, 227, 255, 0.5);
  box-shadow: 0 2px 12px rgba(0, 40, 110, 0.5);
}
.hdr-left { display: flex; align-items: center; gap: 14px; }
.logo { display: flex; align-items: center; gap: 9px; }
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

.hdr-right { display: flex; align-items: center; gap: 10px; justify-content: flex-end; }

/* 中间大标题（参考图那种带翼的标题组件） */
.board-title { position: relative; display: flex; align-items: center; gap: 16px; }
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
  display: flex; align-items: center; justify-content: space-between; gap: 14px;
  padding: 0 16px;
  background: linear-gradient(180deg, rgba(0, 74, 132, 0.94), rgba(0, 58, 110, 0.94));
  border-bottom: 1px solid rgba(64, 176, 255, 0.35);
  font-size: 12px; overflow: hidden;
}
.sb-left { display: flex; align-items: center; gap: 12px; }
.sb-right { display: flex; align-items: center; gap: 14px; }
.tool-icons { display: flex; gap: 6px; }
.ti {
  width: 22px; height: 20px; display: grid; place-items: center;
  font-size: 11px; font-style: normal;
  background: rgba(0, 90, 170, 0.6);
  border: 1px solid rgba(111, 227, 255, 0.35);
}
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
  grid-template-columns: clamp(300px, 22vw, 400px) minmax(0, 1fr) clamp(320px, 24vw, 430px);
  grid-template-rows: minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  min-height: 0;
}
.body { min-height: 0; }
.col { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
.grow { flex: 1; min-height: 0; }
.col.center { display: grid; grid-template-rows: minmax(0, 1fr) auto; }
.h-ctrl { height: 172px; flex: none; }
.h-donut { height: 262px; flex: none; }
.h-points { height: 232px; flex: none; }
.h-msg { height: 190px; flex: none; }

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
.ctrl-meta p { margin: 4px 0 0; font-size: 10.5px; }

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
.donut { width: 128px; height: 128px; flex: none; }
.donut-center {
  position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  width: 128px; text-align: center; pointer-events: none;
}
.donut-center b { display: block; font-size: 24px; color: #ffd54a; font-weight: 800; }
.donut-center em { font-style: normal; font-size: 10px; color: #9fd2ff; }
.legend { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; font-size: 12px; }
.legend li { display: flex; align-items: center; gap: 6px; color: #cfe8ff; }
.legend b { margin-left: auto; color: #fff; font-size: 14px; }

/* 告警趋势（空坐标系，不画假曲线） */
.trend { margin-top: 4px; flex: 1; min-height: 0; display: flex; flex-direction: column; }
.t-head { display: flex; justify-content: space-between; font-size: 11px; color: #9fd2ff; margin-bottom: 4px; }
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
.env-label { font-size: 11.5px; color: #9fd2ff; }
.env-value { font-size: 15px; color: #5d8fc4; font-variant-numeric: tabular-nums; }
.env-value small { font-size: 10px; margin-left: 2px; }

/* 点位 */
.points { list-style: none; margin: 0; padding: 0; }
.points li {
  display: flex; align-items: center; gap: 9px;
  padding: 5px 6px; font-size: 12.5px;
  border-bottom: 1px dashed rgba(140, 210, 255, 0.18);
}
.points .idx {
  width: 22px; height: 18px; display: grid; place-items: center;
  font-size: 10.5px; color: #062f66; font-weight: 700;
  background: linear-gradient(180deg, #9fe4ff, #48b6ff);
}
.points .name { color: #eaf7ff; }
.points .coord { margin-left: auto; color: #9fd2ff; font-size: 11px; }

/* ---------- 响应式：窄屏/矮屏都不挤爆 ---------- */
@media (max-height: 900px) {
  .board { grid-template-rows: 54px 40px minmax(620px, 1fr) 26px; }
}

@media (max-width: 1600px) {
  .board-title h1 { font-size: 21px; letter-spacing: 0.14em; }
  .wing { width: 46px; }
  .tab { padding: 5px 13px; font-size: 13px; }
  .logo-text i { display: none; }
  .stat { gap: 4px; font-size: 11.5px; }
  .subbar { gap: 10px; }
}

@media (max-width: 1440px) {
  .hdr { gap: 8px; }
  .board-title h1 { font-size: 18px; letter-spacing: 0.1em; }
  .wing { width: 28px; }
  .tab { padding: 4px 10px; font-size: 12.5px; }
  .user { display: none; }
  .h-ctrl { height: 182px; }
  .h-donut { height: 236px; }
  .h-points { height: 208px; }
  .h-msg { height: 168px; }
}

/* 窄屏：整块改成普通流式文档，面板从上到下排、整页滚动，绝不互相压 */
@media (max-width: 1240px) {
  .board { display: block; overflow: auto; }
  .hdr { position: sticky; top: 0; z-index: 6; }
  .subbar { flex-wrap: wrap; height: auto; padding: 6px 12px; gap: 8px; }
  .sb-right { flex-wrap: wrap; }
  .clock { min-width: auto; }

  .body {
    display: flex; flex-direction: column;
    gap: 10px; padding: 10px 12px;
    height: auto; min-height: 0;
  }
  /* 取消列容器本身，让面板直接排进 body */
  .col, .col.center { display: contents; grid-template-rows: none; }
  .t-panel {
    flex: none; height: auto; min-height: 0;
  }
  .t-panel :deep(.video-box) { height: 210px; }
  .t-panel :deep(.screen) { min-height: 150px; }
  .map-frame { height: 46vh; min-height: 300px; }
  .tabs .tab:nth-child(n + 3) { display: none; }
  .footbar { position: static; }
}

@media (max-width: 860px) {
  .hdr { grid-template-columns: auto 1fr; }
  .board-title { display: none; }
  .col.left, .col.right { grid-template-columns: minmax(0, 1fr); }
  .icon-btn, .logout { display: none; }
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
</style>
