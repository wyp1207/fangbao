<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import MapCanvas from '@/components/MapCanvas.vue'
import ScadaPanel from '@/components/ScadaPanel.vue'
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

const nav = [
  { name: 'dashboard', label: '首页' },
  { name: 'map', label: '巡检管理' },
  { name: 'tasks', label: '任务与巡航' },
  { name: 'alarms', label: '监控中心' },
  { name: 'history', label: '数据查询' },
  { name: 'settings', label: '系统管理' },
]

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
    <!-- 顶栏 -->
    <header class="hdr">
      <div class="logo">
        <span class="mark">◈</span>
        <div class="logo-text">
          <b>防爆巡检</b>
          <i>JCROB PLATFORM</i>
        </div>
      </div>

      <nav class="tabs">
        <router-link
          v-for="item in nav" :key="item.name"
          :to="{ name: item.name }"
          class="tab" :class="{ active: item.name === 'dashboard' }"
        >{{ item.label }}</router-link>
      </nav>

      <div class="hdr-right">
        <router-link class="icon-btn" :to="{ name: 'alarms' }" title="告警">
          <span class="bell" />{{ unacked.length }}
        </router-link>
        <div class="user">
          <span class="avatar">{{ (auth.user?.username ?? 'A').slice(0, 1).toUpperCase() }}</span>
          <span>{{ auth.user?.username }}</span>
        </div>
        <button class="logout" @click="logout">退出</button>
      </div>
    </header>

    <!-- 状态带 -->
    <div class="subbar">
      <div class="field">
        <label>当前场站</label>
        <span class="select">泰安 · 泉州石化-04</span>
      </div>
      <div class="field">
        <label>当前设备</label>
        <span class="select">JCROB-01（{{ mode }}）</span>
      </div>
      <span class="sep" />
      <div class="clock">
        <b>{{ clock.time }}</b>
        <i>{{ clock.date }}</i>
      </div>
      <span class="sep" />
      <div class="stat"><label>电量</label><b class="gold">{{ battery ?? '—' }}%</b><span class="battery"><i :style="{ width: (battery ?? 0) + '%' }" /></span></div>
      <div class="stat"><label>在线状态</label><b :class="robot.online ? 'green' : 'red'">{{ robot.online ? '在线' : '离线' }}</b></div>
      <div class="stat"><label>重定位状态</label><b class="green">{{ robot.online ? '定位成功' : '未知' }}</b></div>
      <div class="stat"><label>机器人状态</label><b class="gold">{{ mode }}</b></div>
      <div class="stat"><label>服务器状态</label><b class="green">已连接</b></div>
    </div>

    <!-- 主体 -->
    <div class="body">
      <aside class="col left">
        <ScadaPanel title="机器人状态" :right="updated" class="h-kpi">
          <div class="kpi-grid">
            <div class="kpi-cell">
              <div class="kpi-label">在线状态</div>
              <div class="kpi" :class="robot.online ? 'green' : 'red'">{{ robot.online ? '在线' : '中断' }}</div>
            </div>
            <div class="kpi-cell">
              <div class="kpi-label">电池电量</div>
              <div class="kpi gold">{{ battery ?? '—' }}<small>%</small></div>
            </div>
            <div class="kpi-cell">
              <div class="kpi-label">当前任务</div>
              <div class="kpi">{{ mode }}</div>
            </div>
            <div class="kpi-cell">
              <div class="kpi-label">未确认告警</div>
              <div class="kpi" :class="unacked.length ? 'red pulse' : ''">{{ unacked.length }}</div>
            </div>
          </div>
        </ScadaPanel>

        <ScadaPanel title="链路与硬件" class="h-hw">
          <ul class="rows">
            <li><span>链路延迟</span><b>{{ updated }}</b></li>
            <li><span>硬件急停</span><b :class="estop ? 'red' : 'green'">{{ estop ? '已按下' : '未按下' }}</b></li>
            <li><span>固件版本</span><b>{{ version }}</b></li>
            <li><span>导航源</span><b>{{ slam }}</b></li>
            <li><span>电压 / 速度</span><b>{{ num(galileo.power, 1) }}V / {{ num(galileo.currentSpeedX) }}m/s</b></li>
          </ul>
        </ScadaPanel>

        <ScadaPanel title="环境数据" class="h-env" right="未接入">
          <div class="env-grid">
            <div v-for="e in envCells" :key="e.label" class="env-cell">
              <span class="env-label">{{ e.label }}</span>
              <span class="env-value">--<small>{{ e.unit }}</small></span>
            </div>
          </div>
          <p class="dim small">环境传感 WebSocket 未接入，真机联调后自动呈现</p>
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
          </div>
          <p v-if="mapError" class="red small">{{ mapError }}</p>
        </ScadaPanel>

        <ScadaPanel title="实时消息" class="h-msg" right="查看全部 →">
          <table class="tbl">
            <thead><tr><th>时间</th><th>级别</th><th>内容</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="a in robot.alarms.slice(0, 8)" :key="a.id">
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
        <ScadaPanel title="告警统计" class="h-donut">
          <div class="donut-row">
            <svg viewBox="0 0 100 100" class="donut">
              <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,.14)" stroke-width="13" />
              <circle cx="50" cy="50" r="42" fill="none" stroke="#38e07b" stroke-width="13"
                      :stroke-dasharray="`${donut.green} ${RING_C}`" transform="rotate(-90 50 50)" />
              <circle cx="50" cy="50" r="42" fill="none" stroke="#ffcf3f" stroke-width="13"
                      :stroke-dasharray="`${donut.red} ${RING_C}`" :stroke-dashoffset="-donut.green"
                      transform="rotate(-90 50 50)" />
            </svg>
            <div class="donut-center"><b>{{ donut.total }}</b><em>告警总数</em></div>
            <ul class="legend">
              <li><i class="dot gold" />未确认 <b>{{ donut.unacked }}</b></li>
              <li><i class="dot green" />已确认 <b>{{ donut.acked }}</b></li>
            </ul>
          </div>
        </ScadaPanel>

        <ScadaPanel title="巡检点位" class="grow" :right="`${points.length} 点`">
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
      <span>数据更新于 {{ robot.snapshot ? new Date(Date.now() - robot.snapshot.age_s * 1000).toLocaleTimeString('zh-CN') : '—' }}</span>
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
  color: #dff0ff;
  font-size: 13px;
  background:
    radial-gradient(1100px 520px at 18% -6%, rgba(46, 176, 255, 0.42), transparent 62%),
    radial-gradient(900px 480px at 88% 4%, rgba(0, 226, 255, 0.2), transparent 60%),
    linear-gradient(160deg, #0b6fc4 0%, #005da4 45%, #004274 100%);
}
/* 斜向光带 + 网格，参考图那种“科技蓝”底纹 */
.board::before {
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background-image:
    repeating-linear-gradient(135deg, rgba(120, 220, 255, 0.05) 0 2px, transparent 2px 90px),
    linear-gradient(rgba(120, 200, 255, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(120, 200, 255, 0.045) 1px, transparent 1px);
  background-size: auto, 58px 58px, 58px 58px;
  mask-image: radial-gradient(circle at 50% 30%, #000 40%, transparent 92%);
}

/* 顶栏 */
.hdr {
  position: relative;
  display: flex; align-items: center; gap: 18px;
  padding: 0 16px;
  background: linear-gradient(180deg, #0a7ad0, #005da4);
  border-bottom: 1px solid rgba(111, 227, 255, 0.5);
  box-shadow: 0 2px 12px rgba(0, 40, 110, 0.5);
}
.logo { display: flex; align-items: center; gap: 9px; min-width: 190px; }
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

.tabs { display: flex; gap: 6px; flex: 1; justify-content: center; }
.tab {
  position: relative;
  padding: 6px 20px;
  color: #cfe8ff; font-size: 14px;
  background: linear-gradient(180deg, rgba(20, 130, 220, 0.6), rgba(0, 70, 140, 0.7));
  border: 1px solid rgba(111, 227, 255, 0.45);
  clip-path: polygon(10px 0, 100% 0, calc(100% - 10px) 100%, 0 100%);
  transition: all 0.15s;
}
.tab:hover { color: #fff; border-color: #6fe3ff; }
.tab.active {
  color: #082f66;
  font-weight: 700;
  background: linear-gradient(180deg, #b9ecff, #4fc3ff);
  box-shadow: 0 0 14px rgba(120, 220, 255, 0.8);
}

.hdr-right { display: flex; align-items: center; gap: 14px; min-width: 190px; justify-content: flex-end; }
.icon-btn {
  display: inline-flex; align-items: center; gap: 6px;
  color: #cfe8ff; font-size: 12px;
  padding: 4px 10px;
  border: 1px solid rgba(111, 227, 255, 0.4);
}
.bell {
  width: 10px; height: 10px; border-radius: 50%;
  background: #ffcf3f; box-shadow: 0 0 8px rgba(255, 207, 63, 0.9);
}
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
  display: flex; align-items: center; gap: 14px;
  padding: 0 16px;
  background: linear-gradient(180deg, rgba(0, 74, 132, 0.94), rgba(0, 58, 110, 0.94));
  border-bottom: 1px solid rgba(64, 176, 255, 0.35);
  font-size: 12px;
  overflow: hidden;
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
  grid-template-columns: clamp(300px, 21vw, 380px) minmax(0, 1fr) clamp(320px, 23vw, 420px);
  grid-template-rows: minmax(0, 1fr);   /* 必须有显式行轨道，否则列高度按内容算，画布会被压成 0 */
  gap: 10px;
  padding: 10px 12px;
  min-height: 0;
}
.col { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
/* 中列用 grid 单行 1fr，保证面板拿到确定高度（flex 链在深层嵌套里会塌成 0） */
.col.center { display: grid; grid-template-rows: minmax(0, 1fr) auto; }
.col.center > .t-panel { min-height: 0; }
.grow { flex: 1; min-height: 0; }
.h-kpi { height: 196px; flex: none; }
.h-hw { height: 196px; flex: none; }
.h-donut { height: 196px; flex: none; }
.h-env { flex: 1; min-height: 0; }
.h-msg { height: 208px; flex: none; }

.kpi-grid { display: grid; grid-template-columns: 1fr 1fr; height: 100%; }
.kpi-cell {
  padding: 2px 8px; display: flex; flex-direction: column; justify-content: center; gap: 4px;
  border-right: 1px dashed rgba(140, 210, 255, 0.22);
  border-bottom: 1px dashed rgba(140, 210, 255, 0.22);
}
.kpi-cell:nth-child(2n) { border-right: none; }
.kpi-cell:nth-child(n + 3) { border-bottom: none; }
.kpi-label { font-size: 12px; color: #9fd2ff; }
.kpi { font-size: 26px; font-weight: 800; color: #fff; text-shadow: 0 2px 6px rgba(0, 40, 90, 0.6); }
.kpi small { font-size: 12px; color: #9fd2ff; margin-left: 2px; }
.kpi.gold { color: #ffd54a; text-shadow: 0 0 14px rgba(255, 213, 74, 0.5); }
.kpi.green { color: #7dff9a; text-shadow: 0 0 14px rgba(125, 255, 154, 0.45); }
.kpi.red { color: #ff8a8a; }
.kpi.pulse { animation: p 1.1s ease-out infinite; }
@keyframes p { 0% { text-shadow: 0 0 0 rgba(255, 90, 90, 0.8); } 100% { text-shadow: 0 0 18px rgba(255, 90, 90, 0); } }

.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 7px; }
.rows li { display: flex; justify-content: space-between; font-size: 12.5px; }
.rows span { color: #9fd2ff; }
.rows b { color: #eaf7ff; font-weight: 600; }

.tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.tbl th {
  text-align: left; padding: 6px 8px; font-weight: 600; color: #cfe8ff;
  background: rgba(0, 110, 200, 0.8);
  border: 1px solid rgba(111, 227, 255, 0.25);
}
.tbl td { padding: 6px 8px; color: #dff0ff; border: 1px solid rgba(111, 227, 255, 0.14); }
.tbl tbody tr:nth-child(even) td { background: rgba(0, 80, 150, 0.35); }
.tbl .strong { color: #fff; }
.tbl .dim { color: #9fd2ff; }

.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; margin-right: 4px; background: #9fd2ff; }
.dot.green { background: #38e07b; box-shadow: 0 0 7px rgba(56, 224, 123, 0.9); }
.dot.red { background: #ff5a5a; box-shadow: 0 0 7px rgba(255, 90, 90, 0.9); }
.dot.gold { background: #ffcf3f; box-shadow: 0 0 7px rgba(255, 207, 63, 0.9); }

.map-frame { position: relative; flex: 1 1 auto; min-height: 0; }
/* 用绝对定位把画布钉在父容器上，避免 flex 高度算不出来 */
.map-frame :deep(.map-wrap) { position: absolute; inset: 0; height: auto; min-height: 0; }
/* 扫描线：参考图那种横着扫的光带 */
.scan {
  position: absolute; left: 0; right: 0; top: 0; height: 40%;
  background: linear-gradient(180deg, rgba(120, 230, 255, 0.16), transparent);
  animation: sweep 5s linear infinite;
  pointer-events: none;
}
@keyframes sweep { 0% { transform: translateY(-100%); } 100% { transform: translateY(260%); } }

.donut-row { display: flex; align-items: center; gap: 12px; height: 100%; position: relative; }
.donut { width: 118px; height: 118px; flex: none; }
.donut-center {
  position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  width: 118px; text-align: center; pointer-events: none;
}
.donut-center b { display: block; font-size: 24px; color: #ffd54a; font-weight: 800; }
.donut-center em { font-style: normal; font-size: 10px; color: #9fd2ff; }
.legend { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; font-size: 12px; }
.legend li { display: flex; align-items: center; gap: 6px; color: #cfe8ff; }
.legend b { margin-left: auto; color: #fff; font-size: 14px; }

.env-grid { display: grid; grid-template-columns: 1fr 1fr; grid-auto-rows: 56px; align-content: center; gap: 6px 10px; }
.env-cell {
  display: flex; align-items: center; justify-content: space-between;
  padding: 5px 8px;
  background: rgba(0, 78, 145, 0.55);
  border: 1px solid rgba(111, 227, 255, 0.22);
}
.env-label { font-size: 11.5px; color: #9fd2ff; }
.env-value { font-size: 16px; color: #5d8fc4; font-variant-numeric: tabular-nums; }
.env-value small { font-size: 10px; margin-left: 2px; }

.points { list-style: none; margin: 0; padding: 0; }
.points li {
  display: flex; align-items: center; gap: 9px;
  padding: 6px 6px; font-size: 12.5px;
  border-bottom: 1px dashed rgba(140, 210, 255, 0.18);
}
.points .idx {
  width: 22px; height: 18px; display: grid; place-items: center;
  font-size: 10.5px; color: #062f66; font-weight: 700;
  background: linear-gradient(180deg, #9fe4ff, #48b6ff);
}
.points .name { color: #eaf7ff; }
.points .coord { margin-left: auto; color: #9fd2ff; font-size: 11px; }
.points .dim { color: #9fd2ff; justify-content: center; }

.footbar {
  display: flex; align-items: center; gap: 20px;
  padding: 0 14px;
  font-size: 11px; color: #9fd2ff;
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
