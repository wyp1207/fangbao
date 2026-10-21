<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import StatusBar from '@/components/StatusBar.vue'
import MapCanvas from '@/components/MapCanvas.vue'
import { useRobotStore } from '@/stores/robot'
import { api, type MapMeta, type NavPoint } from '@/api'

const robot = useRobotStore()
const mapMeta = ref<MapMeta | null>(null)
const points = ref<NavPoint[]>([])
const mapError = ref('')
const trail = ref<{ x: number; y: number }[]>([])

const imageUrl = computed(() => (robot.currentMap ? api.mapPng(1, robot.currentMap) : ''))
const pose = computed(() => robot.pose)
const galileo = computed(() => robot.snapshot?.galileo ?? {})

function num(value: unknown, digits = 2): string {
  return typeof value === 'number' ? value.toFixed(digits) : '—'
}

const unacked = computed(() => robot.alarms.filter((a) => !a.acked_at))
const acked = computed(() => robot.alarms.filter((a) => a.acked_at))

const donutStyle = computed(() => {
  const total = robot.alarms.length
  if (!total) return { background: 'var(--bg-3)' }
  const pct = (unacked.value.length / total) * 100
  return { background: `conic-gradient(var(--danger) 0 ${pct}%, var(--ok-soft) ${pct}% 100%)` }
})

const envItems = [
  { label: '温度', unit: '℃' },
  { label: '湿度', unit: '%RH' },
  { label: '可燃气体', unit: 'ppm' },
  { label: '烟雾', unit: 'ppm' },
  { label: 'PM2.5', unit: 'μg/m³' },
  { label: '噪声', unit: 'dB' },
]

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

let trailTimer = 0

onMounted(async () => {
  robot.start()
  await loadMap()
  trailTimer = window.setInterval(() => {
    const p = robot.pose
    if (!p || typeof p.x !== 'number' || typeof p.y !== 'number') return
    trail.value.push({ x: p.x, y: p.y })
    if (trail.value.length > 200) trail.value.shift()
  }, 1000)
})

onBeforeUnmount(() => {
  robot.stop()
  if (trailTimer) window.clearInterval(trailTimer)
})
</script>

<template>
  <div class="dash">
    <StatusBar :snapshot="robot.snapshot" :online="robot.online" :stale="robot.stale" />

    <div class="kpis">
      <div class="panel kpi-card">
        <div class="kpi-label">在线状态</div>
        <div class="kpi-row">
          <span class="kpi" :class="robot.online ? 'ok' : 'danger'">{{ robot.online ? '在线' : '中断' }}</span>
          <span class="tag" :class="robot.stale ? 'warn' : 'ok'">
            {{ robot.snapshot ? robot.snapshot.age_s.toFixed(1) + 's 前' : '无数据' }}
          </span>
        </div>
      </div>

      <div class="panel kpi-card">
        <div class="kpi-label">电池电量</div>
        <div class="kpi-row">
          <span class="kpi">{{ robot.battery ?? '—' }}<small>%</small></span>
          <span class="tag" :class="robot.estop ? 'danger' : 'ok'">
            {{ robot.estop ? '急停按下' : '急停未按下' }}
          </span>
        </div>
      </div>

      <div class="panel kpi-card">
        <div class="kpi-label">当前任务</div>
        <div class="kpi-row">
          <span class="kpi">{{ robot.robotState }}</span>
          <span class="tag">进度未标定</span>
        </div>
      </div>

      <div class="panel kpi-card">
        <div class="kpi-label">未确认告警</div>
        <div class="kpi-row">
          <span class="kpi" :class="unacked.length ? 'danger' : ''">{{ unacked.length }}</span>
          <span class="tag" :class="unacked.length ? 'danger' : ''">共 {{ robot.alarms.length }} 条</span>
        </div>
      </div>
    </div>

    <div class="main">
      <section class="panel map-card">
        <div class="panel-title">
          <span>实时地图 · {{ robot.currentMap || '未连接' }}</span>
          <span class="muted small">{{ points.length }} 个点位</span>
        </div>
        <div class="map-box">
          <MapCanvas
            :map-meta="mapMeta"
            :image-url="imageUrl"
            :points="points"
            :pose="pose"
            :stale="robot.stale || !robot.online"
            :trail="trail"
          />
        </div>
        <p v-if="mapError" class="danger small">{{ mapError }}</p>
      </section>

      <div class="side">
        <section class="panel">
          <div class="panel-title"><span>告警统计</span></div>
          <div class="donut-row">
            <div class="donut" :style="donutStyle"><span>{{ robot.alarms.length }}</span></div>
            <ul class="legend">
              <li><i class="sw danger" />未确认 <b>{{ unacked.length }}</b></li>
              <li><i class="sw ok" />已确认 <b>{{ acked.length }}</b></li>
              <li class="muted small">确认不等于恢复，恢复由数据判断</li>
            </ul>
          </div>
        </section>

        <section class="panel env-card">
          <div class="panel-title">
            <span>环境数据</span>
            <span class="tag warn">未接入</span>
          </div>
          <ul class="env">
            <li v-for="e in envItems" :key="e.label">
              <span>{{ e.label }}</span>
              <b class="num">—</b>
              <em>{{ e.unit }}</em>
            </li>
          </ul>
          <p class="muted small">
            走机器人 WebSocket；PDF 只给了字段，没给推送频率与 ping 语义，真机联调后再接。
          </p>
        </section>
      </div>
    </div>

    <div class="bottom">
      <section class="panel">
        <div class="panel-title">
          <span>实时消息</span>
          <router-link class="link" :to="{ name: 'alarms' }">查看全部</router-link>
        </div>
        <table class="grid">
          <thead>
            <tr><th style="width: 92px">时间</th><th style="width: 84px">级别</th><th>内容</th><th style="width: 92px">状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="a in robot.alarms.slice(0, 6)" :key="a.id">
              <td class="num">{{ a.started_at.slice(11, 19) }}</td>
              <td>
                <span class="tag" :class="a.level === 'critical' ? 'danger' : 'warn'">
                  {{ a.level === 'critical' ? '严重' : '提醒' }}
                </span>
              </td>
              <td>{{ a.message }}</td>
              <td>
                <span v-if="a.acked_at" class="ok">已确认</span>
                <span v-else class="danger">未确认</span>
              </td>
            </tr>
            <tr v-if="!robot.alarms.length">
              <td colspan="4" class="muted small">暂无消息。环境类阈值未标定，不会产生环境告警。</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="panel">
        <div class="panel-title"><span>地图与点位</span></div>
        <ul class="stat">
          <li><span>地图</span><b class="num">{{ robot.maps.length }}</b></li>
          <li><span>巡检点</span><b class="num">{{ points.length }}</b></li>
          <li><span>分辨率</span><b class="num">{{ mapMeta?.resolution?.toFixed(3) ?? '—' }}<small>m/px</small></b></li>
          <li><span>底图尺寸</span><b class="num">{{ mapMeta ? `${mapMeta.width}×${mapMeta.height}` : '—' }}</b></li>
        </ul>
        <router-link class="btn link-btn" :to="{ name: 'map' }">进入地图管理</router-link>
      </section>
    </div>
  </div>
</template>

<style scoped>
.dash { display: flex; flex-direction: column; gap: var(--gap); }

.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--gap); }
.kpi-card { padding: 16px 18px; }
.kpi-label { font-size: 13px; color: var(--text-2); margin-bottom: 10px; }
.kpi-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }

.main { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: var(--gap); }
.side { display: flex; flex-direction: column; gap: var(--gap); }

.map-card { display: flex; flex-direction: column; }
.map-box { flex: 1; min-height: 390px; }

.donut-row { display: flex; align-items: center; gap: 22px; }
.donut {
  width: 108px; height: 108px; border-radius: 50%;
  display: grid; place-items: center;
  position: relative;
}
.donut::after {
  content: ""; position: absolute; inset: 14px; border-radius: 50%; background: #fff;
}
.donut span { position: relative; z-index: 1; font-size: 22px; font-weight: 600; font-family: var(--font-num); }
.legend { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: var(--text-1); }
.legend li { display: flex; align-items: center; gap: 7px; }
.legend b { margin-left: auto; color: var(--text-0); font-family: var(--font-num); }
.sw { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.sw.danger { background: var(--danger); }
.sw.ok { background: var(--ok); }

.env { list-style: none; margin: 0 0 12px; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 10px 18px; }
.env li { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-1); }
.env b { margin-left: auto; color: var(--text-2); font-size: 14px; }
.env em { font-style: normal; font-size: 11px; color: var(--text-2); width: 34px; text-align: right; }

.bottom { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: var(--gap); }
.stat { list-style: none; margin: 0 0 14px; padding: 0; display: flex; flex-direction: column; gap: 11px; }
.stat li { display: flex; justify-content: space-between; align-items: baseline; font-size: 13px; color: var(--text-1); }
.stat b { color: var(--text-0); font-size: 15px; font-weight: 500; }
.stat b small { font-size: 11px; color: var(--text-2); margin-left: 3px; }

.link { font-size: 13px; color: var(--accent); font-weight: 400; }
.link-btn { display: block; text-align: center; }
</style>
