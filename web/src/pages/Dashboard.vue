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
  { name: 'dashboard', label: '驾驶舱' },
  { name: 'map', label: '地图与点位' },
  { name: 'tasks', label: '任务与巡航' },
  { name: 'alarms', label: '告警中心' },
  { name: 'history', label: '数据查询' },
  { name: 'settings', label: '系统设置' },
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
    date: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} 周${'日一二三四五六'[d.getDay()]}`,
  }
})

const updatedAt = computed(() => (robot.snapshot ? robot.snapshot.age_s.toFixed(1) + 's 前' : '—'))
const mode = computed(() => robot.snapshot?.status?.status ?? 'UNKNOWN')
const battery = computed(() => robot.snapshot?.info?.battery ?? null)
const estop = computed(() => robot.snapshot?.info?.driver_port ?? null)
const charging = computed(() => robot.snapshot?.info?.charge ?? null)
const version = computed(() => robot.snapshot?.info?.info?.version ?? '待确认')
const slam = computed(() => robot.snapshot?.info?.slam_type ?? '待确认')

/** 告警环形：用 SVG 画两段弧，避免为两个数值引 ECharts */
const donut = computed(() => {
  const total = robot.alarms.length
  if (!total) return { unacked: 0, acked: 0, total: 0, dashRed: 0, dashGreen: 0 }
  const C = 2 * Math.PI * 42
  return {
    unacked: unacked.value.length,
    acked: acked.value.length,
    total,
    dashRed: (unacked.value.length / total) * C,
    dashGreen: (acked.value.length / total) * C,
  }
})
const RING_C = 2 * Math.PI * 42

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

function fit() {
  // 布局改成自适应撑满，不再做整体缩放；这里的函数仅为兼容调用点
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

function leave() {
  robot.stop()
  router.push({ name: 'alarms' })
}

async function logout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="scada">
    <div class="screen">
      <!-- 顶栏 -->
      <header class="hdr">
        <div class="brand">
          <div class="logo">◈</div>
          <div>
            <h1>防爆机器人巡检平台</h1>
            <p>JCROB · 单机 · 二维作业管控</p>
          </div>
        </div>

        <nav class="nav">
          <router-link
            v-for="item in nav"
            :key="item.name"
            :to="{ name: item.name }"
            class="nav-item"
            :class="{ active: item.name === 'dashboard' }"
          >{{ item.label }}</router-link>
        </nav>

        <div class="meta">
          <span class="state" :class="robot.online ? 'ok' : 'danger'">
            <i class="pulse" />{{ robot.online ? '链路正常' : '通信中断' }}
          </span>
          <div class="clock">
            <b>{{ clock.time }}</b>
            <em>{{ clock.date }}</em>
          </div>
          <button class="btn-quiet" @click="logout">退出</button>
        </div>
      </header>

      <!-- 主体 -->
      <div class="body">
        <aside class="col left">
          <ScadaPanel title="机器人状态" class="h-kpi">
            <div class="kpi-grid">
              <div class="kpi-cell">
                <div class="kpi-label">在线状态</div>
                <div class="kpi" :class="robot.online ? 'ok' : 'danger'">
                  {{ robot.online ? '在线' : '中断' }}
                </div>
                <span class="chip" :class="robot.stale ? 'warn' : 'ok'">{{ updatedAt }}</span>
              </div>
              <div class="kpi-cell">
                <div class="kpi-label">电池电量</div>
                <div class="kpi">{{ battery ?? '—' }}<small>%</small></div>
                <div class="bar"><i :style="{ width: (battery ?? 0) + '%' }" /></div>
              </div>
              <div class="kpi-cell">
                <div class="kpi-label">当前任务</div>
                <div class="kpi">{{ mode }}</div>
                <span class="chip">进度未标定</span>
              </div>
              <div class="kpi-cell">
                <div class="kpi-label">未确认告警</div>
                <div class="kpi" :class="unacked.length ? 'danger alert' : ''">{{ unacked.length }}</div>
                <span class="chip">共 {{ robot.alarms.length }} 条</span>
              </div>
            </div>
          </ScadaPanel>

          <ScadaPanel title="链路与硬件" class="h-hw">
            <ul class="rows">
              <li><span>链路延迟</span><b class="num">{{ updatedAt }}</b></li>
              <li><span>运行模式</span><b>{{ mode }}</b></li>
              <li><span>硬件急停</span><b :class="estop ? 'danger' : 'ok'">{{ estop ? '已按下' : '未按下' }}</b></li>
              <li><span>充电状态</span><b>{{ charging ? '充电中' : '未充电' }}</b></li>
              <li><span>固件版本</span><b class="num">{{ version }}</b></li>
              <li><span>导航源</span><b>{{ slam }}</b></li>
            </ul>
          </ScadaPanel>

          <ScadaPanel title="实时消息" class="grow" right="查看全部 →">
            <table class="tbl">
              <thead><tr><th>时间</th><th>级别</th><th>内容</th><th>状态</th></tr></thead>
              <tbody>
                <tr v-for="a in robot.alarms.slice(0, 7)" :key="a.id">
                  <td class="num dim">{{ a.started_at.slice(11, 19) }}</td>
                  <td><i class="dot" :class="a.level === 'critical' ? 'danger' : 'warn'" />{{ a.level === 'critical' ? '严重' : '提醒' }}</td>
                  <td class="msg">{{ a.message }}</td>
                  <td :class="a.acked_at ? 'ok' : 'danger'">{{ a.acked_at ? '已确认' : '未确认' }}</td>
                </tr>
                <tr v-if="!robot.alarms.length">
                  <td colspan="4" class="dim">暂无消息 · 环境类阈值未标定，不会产生环境告警</td>
                </tr>
              </tbody>
            </table>
          </ScadaPanel>
        </aside>

        <main class="col center">
          <ScadaPanel
            title="实时地图"
            :right="`${points.length} 个点位 · ${mapMeta?.resolution?.toFixed(3) ?? '—'} m/px`"
            class="grow"
            body-class="map-body"
          >
            <MapCanvas
              dark
              :map-meta="mapMeta"
              :image-url="imageUrl"
              :points="points"
              :pose="pose"
              :stale="robot.stale || !robot.online"
              :trail="trail"
            />
            <p v-if="mapError" class="err">{{ mapError }}</p>
          </ScadaPanel>
        </main>

        <aside class="col right">
          <ScadaPanel title="告警统计" class="h-donut">
            <div class="donut-row">
              <svg viewBox="0 0 100 100" class="donut">
                <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="12" />
                <circle
                  cx="50" cy="50" r="42" fill="none" stroke="#22E5A6" stroke-width="12"
                  :stroke-dasharray="`${donut.dashGreen} ${RING_C}`"
                  transform="rotate(-90 50 50)"
                />
                <circle
                  cx="50" cy="50" r="42" fill="none" stroke="#FF4D5E" stroke-width="12"
                  :stroke-dasharray="`${donut.dashRed} ${RING_C}`"
                  :stroke-dashoffset="-donut.dashGreen"
                  transform="rotate(-90 50 50)"
                />
              </svg>
              <div class="donut-center">
                <b class="num">{{ donut.total }}</b>
                <em>告警总数</em>
              </div>
              <ul class="legend">
                <li><i class="sw red" />未确认 <b class="num">{{ donut.unacked }}</b></li>
                <li><i class="sw green" />已确认 <b class="num">{{ donut.acked }}</b></li>
                <li class="hint">确认不等于恢复，恢复由数据判断</li>
              </ul>
            </div>
          </ScadaPanel>

          <ScadaPanel title="环境数据" class="h-env" right="未接入">
            <div class="env-grid">
              <div v-for="e in envCells" :key="e.label" class="env-cell">
                <div class="env-label">{{ e.label }}</div>
                <div class="env-value">--<small>{{ e.unit }}</small></div>
              </div>
            </div>
            <p class="hint">环境传感 WebSocket 未接入，真机联调后自动呈现</p>
          </ScadaPanel>

          <ScadaPanel title="巡检点位" class="grow" :right="`${points.length} 点`">
            <ul class="points">
              <li v-for="(p, i) in points" :key="i">
                <span class="idx num">{{ String(i + 1).padStart(2, '0') }}</span>
                <span class="name">{{ p.name || `点位 ${String(i + 1).padStart(2, '0')}` }}</span>
                <span class="coord num">{{ p.x.toFixed(1) }}, {{ p.y.toFixed(1) }}</span>
                <i class="dot ok" />
              </li>
              <li v-if="!points.length" class="dim">地图未加载</li>
            </ul>
          </ScadaPanel>
        </aside>
      </div>

      <!-- 底部状态条 -->
      <footer class="statusbar">
        <span class="sb-item"><i class="pulse" :class="robot.online ? 'ok' : 'danger'" />链路 {{ robot.online ? '正常' : '中断' }}</span>
        <span class="sb-item">数据更新于 {{ robot.snapshot ? new Date(Date.now() - robot.snapshot.age_s * 1000).toLocaleTimeString('zh-CN') : '—' }}</span>
        <span class="sb-item">电压 {{ num(galileo.power, 1) }} V · 速度 {{ num(galileo.currentSpeedX) }} m/s</span>
        <span class="sb-spacer" />
        <span class="sb-item">WebSocket 推送未接入（轮询 1s）</span>
        <span class="sb-item">v0.1.0</span>
      </footer>
    </div>

    <button class="leave" @click="leave">进入后台</button>
  </div>
</template>

<style scoped>
.scada {
  position: fixed; inset: 0; z-index: 40;
  background:
    radial-gradient(1200px 700px at 18% 0%, rgba(24, 144, 255, 0.18), transparent 42%),
    radial-gradient(900px 600px at 88% 8%, rgba(19, 194, 194, 0.12), transparent 40%),
    linear-gradient(180deg, #07111f 0%, #0a1730 48%, #08101f 100%);
  overflow: hidden;
}
.scada::before {
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(64, 158, 255, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(64, 158, 255, 0.05) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(circle at 50% 40%, #000 30%, transparent 85%);
}

.screen {
  position: absolute; inset: 0;
  padding: 12px 16px 10px;
  display: grid;
  grid-template-rows: 60px minmax(0, 1fr) 28px;
  gap: 10px;
  color: #a9bbd6;
  font-size: 13px;
}

/* 顶栏 */
.hdr { display: flex; align-items: center; gap: 30px; position: relative; }
.hdr::after {
  content: ""; position: absolute; left: 0; right: 0; bottom: -5px; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(41, 212, 255, 0.5), transparent);
}
.brand { display: flex; align-items: center; gap: 11px; width: 420px; }
.logo {
  width: 34px; height: 34px; display: grid; place-items: center;
  color: #29d4ff; font-size: 19px;
  border: 1px solid rgba(41, 212, 255, 0.45);
  border-radius: 2px;
  background: rgba(41, 212, 255, 0.07);
  box-shadow: 0 0 14px rgba(41, 212, 255, 0.3);
}
h1 { font-size: 21px; margin: 0; color: #eaf4ff; letter-spacing: 0.08em; font-weight: 700; }
.brand p { margin: 3px 0 0; font-size: 11px; color: #6b7c99; letter-spacing: 0.16em; }

.nav { flex: 1; display: flex; justify-content: center; gap: 26px; }
.nav-item {
  position: relative; padding: 18px 0 8px;
  color: #a9bbd6; font-size: 14px;
}
.nav-item:hover { color: #eaf4ff; }
.nav-item.active { color: #29d4ff; font-weight: 500; }
.nav-item.active::after {
  content: ""; position: absolute; left: 50%; bottom: 0; width: 24px; height: 3px;
  transform: translateX(-50%);
  background: #29d4ff; border-radius: 2px;
  box-shadow: 0 0 10px rgba(41, 212, 255, 0.8);
}

.meta { display: flex; align-items: center; gap: 18px; width: 420px; justify-content: flex-end; }
.state {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 13px; padding: 4px 11px; border-radius: 2px;
  border: 1px solid currentColor; background: rgba(34, 229, 166, 0.08);
}
.state.ok { color: #22e5a6; }
.state.danger { color: #ff4d5e; background: rgba(255, 77, 94, 0.1); }
.clock { text-align: right; line-height: 1.2; }
.clock b { display: block; font-size: 20px; color: #eaf4ff; font-variant-numeric: tabular-nums; letter-spacing: 0.04em; }
.clock em { font-style: normal; font-size: 11px; color: #6b7c99; }
.btn-quiet {
  background: transparent; color: #a9bbd6; font-size: 12px;
  border: 1px solid rgba(64, 158, 255, 0.35); border-radius: 2px;
  padding: 5px 12px; cursor: pointer;
}
.btn-quiet:hover { color: #29d4ff; border-color: #29d4ff; }

/* 主体三列 */
.body {
  display: grid;
  grid-template-columns: clamp(300px, 21vw, 380px) minmax(0, 1fr) clamp(320px, 23vw, 420px);
  gap: 12px;
  min-height: 0;
}
.col { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.grow { flex: 1; min-height: 0; }
.h-kpi { height: 232px; flex: none; }
.h-hw { height: 224px; flex: none; }
.h-donut { height: 232px; flex: none; }
.h-env { height: 256px; flex: none; }

/* KPI 2×2 */
.kpi-grid { display: grid; grid-template-columns: 1fr 1fr; height: 100%; }
.kpi-cell {
  position: relative;
  padding: 6px 12px 8px;
  display: flex; flex-direction: column; gap: 5px; justify-content: center;
  border-right: 1px solid rgba(64, 128, 200, 0.14);
  border-bottom: 1px solid rgba(64, 128, 200, 0.14);
}
.kpi-cell:nth-child(2n) { border-right: none; }
.kpi-cell:nth-child(n + 3) { border-bottom: none; }
.kpi-label { font-size: 12px; color: #6b7c99; }
.kpi {
  font-size: 28px; font-weight: 700; line-height: 1.1; color: #eaf4ff;
  font-variant-numeric: tabular-nums;
}
.kpi small { font-size: 13px; color: #6b7c99; margin-left: 2px; font-weight: 400; }
.kpi.ok { color: #22e5a6; text-shadow: 0 0 14px rgba(34, 229, 166, 0.45); }
.kpi.danger { color: #ff4d5e; }
.kpi.alert { animation: alertPulse 1.2s ease-out infinite; }
@keyframes alertPulse {
  0% { box-shadow: 0 0 0 0 rgba(255, 77, 94, 0.55); }
  100% { box-shadow: 0 0 0 12px rgba(255, 77, 94, 0); }
}
.chip {
  align-self: flex-start;
  font-size: 11px; padding: 1px 7px; border-radius: 2px;
  border: 1px solid rgba(169, 187, 214, 0.5); color: #a9bbd6;
}
.chip.ok { color: #22e5a6; border-color: rgba(34, 229, 166, 0.5); }
.chip.warn { color: #ffb02e; border-color: rgba(255, 176, 46, 0.5); }
.bar { height: 5px; background: rgba(255, 255, 255, 0.08); border-radius: 1px; overflow: hidden; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, #22e5a6, #29d4ff); box-shadow: 0 0 8px rgba(41, 212, 255, 0.5); }

/* 链路与硬件 */
.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.rows li { display: flex; justify-content: space-between; font-size: 13px; }
.rows span { color: #6b7c99; }
.rows b { font-weight: 500; color: #eaf4ff; }
.rows b.ok { color: #22e5a6; }
.rows b.danger { color: #ff4d5e; }

/* 表格 */
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.tbl th {
  text-align: left; font-size: 11.5px; font-weight: 500; color: #8fa3c4;
  background: rgba(17, 38, 74, 0.8); padding: 6px 8px; height: 30px;
}
.tbl td { padding: 7px 8px; border-bottom: 1px solid rgba(64, 128, 200, 0.12); color: #a9bbd6; }
.tbl tbody tr:hover td { background: rgba(41, 212, 255, 0.06); }
.tbl .msg { color: #eaf4ff; }
.tbl .dim { color: #6b7c99; }
.dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; margin-right: 5px; }
.dot.ok { background: #22e5a6; }
.dot.warn { background: #ffb02e; }
.dot.danger { background: #ff4d5e; box-shadow: 0 0 8px rgba(255, 77, 94, 0.8); }

/* 地图 */
.map-body { padding: 8px; display: flex; flex-direction: column; }
.err { color: #ff4d5e; font-size: 12px; margin: 6px 0 0; }

/* 告警环形 */
.donut-row { display: flex; align-items: center; gap: 18px; height: 100%; position: relative; }
.donut { width: 140px; height: 140px; flex: none; }
.donut-center {
  position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  width: 140px; text-align: center; pointer-events: none;
}
.donut-center b { display: block; font-size: 30px; color: #eaf4ff; font-weight: 700; }
.donut-center em { font-style: normal; font-size: 11px; color: #6b7c99; }
.legend { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 9px; font-size: 13px; }
.legend li { display: flex; align-items: center; gap: 7px; color: #a9bbd6; }
.legend b { margin-left: auto; color: #eaf4ff; font-size: 15px; }
.sw { width: 8px; height: 8px; border-radius: 1px; display: inline-block; }
.sw.red { background: #ff4d5e; box-shadow: 0 0 8px rgba(255, 77, 94, 0.6); }
.sw.green { background: #22e5a6; box-shadow: 0 0 8px rgba(34, 229, 166, 0.5); }
.hint { font-size: 11px; color: #6b7c99; line-height: 1.6; margin: 8px 0 0; }

/* 环境六格 */
.env-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px 12px; }
.env-cell {
  border: 1px dashed rgba(64, 128, 200, 0.25);
  border-radius: 2px; padding: 5px 9px;
}
.env-label { font-size: 11.5px; color: #6b7c99; }
.env-value { font-size: 19px; color: #44536b; font-variant-numeric: tabular-nums; line-height: 1.3; }
.env-value small { font-size: 10.5px; margin-left: 3px; }

/* 点位列表 */
.points { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.points li {
  display: flex; align-items: center; gap: 10px;
  padding: 7px 6px; font-size: 13px;
  border-bottom: 1px solid rgba(64, 128, 200, 0.1);
}
.points .idx {
  width: 22px; height: 20px; display: grid; place-items: center;
  font-size: 11px; color: #29d4ff;
  border: 1px solid rgba(41, 212, 255, 0.35); border-radius: 2px;
}
.points .name { color: #eaf4ff; }
.points .coord { margin-left: auto; color: #6b7c99; font-size: 11.5px; }
.points .dim { color: #6b7c99; justify-content: center; }

/* 底部状态条 */
.statusbar {
  display: flex; align-items: center; gap: 22px;
  padding: 0 12px;
  font-size: 11.5px; color: #6b7c99;
  border-top: 1px solid rgba(64, 128, 200, 0.18);
}
.sb-spacer { flex: 1; }
.sb-item { display: inline-flex; align-items: center; gap: 6px; }
.pulse { width: 6px; height: 6px; border-radius: 50%; background: #22e5a6; animation: breathe 2s ease-in-out infinite; }
.pulse.danger { background: #ff4d5e; }
@keyframes breathe { 50% { opacity: 0.45; transform: scale(1.25); } }

.leave {
  position: fixed; right: 12px; bottom: 10px; z-index: 41;
  background: rgba(8, 16, 31, 0.8); color: #a9bbd6;
  border: 1px solid rgba(64, 158, 255, 0.35); border-radius: 2px;
  font-size: 11px; padding: 4px 10px; cursor: pointer;
}
.leave:hover { color: #29d4ff; border-color: #29d4ff; }
</style>
