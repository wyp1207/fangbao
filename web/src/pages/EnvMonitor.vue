<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, type SensorItem } from '@/api'
import { useRobotStore } from '@/stores/robot'

const robot = useRobotStore()
const rows = ref<SensorItem[]>([])
const histories = ref<Record<number, { ts: string; value: number }[]>>({})
const tick = ref(Date.now())

const cards = computed(() =>
  rows.value.filter((s) => s.enabled).map((s) => {
    const hist = histories.value[s.id] ?? []
    return { s, hist, spark: sparkline(hist), level: levelOf(s) }
  }),
)

function levelOf(s: SensorItem): 'ok' | 'warn' | 'critical' | 'uncalibrated' {
  if (!s.calibrated) return 'uncalibrated'
  const v = s.latest?.value
  if (v === undefined || v === null) return 'ok'
  if ((s.crit_high !== null && v >= s.crit_high) || (s.crit_low !== null && v <= s.crit_low)) return 'critical'
  if ((s.warn_high !== null && v >= s.warn_high) || (s.warn_low !== null && v <= s.warn_low)) return 'warn'
  return 'ok'
}

const LEVEL_TEXT: Record<string, string> = {
  ok: '正常', warn: '注意', critical: '超限', uncalibrated: '未标定',
}

/** 迷你折线：把点映射到 100x28 的 svg 上 */
function sparkline(points: { value: number }[]): string {
  if (points.length < 2) return ''
  const vals = points.map((p) => p.value)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const span = max - min || 1
  return points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * 100
      const y = 26 - ((p.value - min) / span) * 24
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function ago(ts: string | null): string {
  if (!ts) return '—'
  const s = Math.max(0, (tick.value - Date.parse(ts)) / 1000)
  if (s < 60) return `${Math.round(s)} 秒前`
  if (s < 3600) return `${Math.round(s / 60)} 分钟前`
  return `${Math.round(s / 3600)} 小时前`
}

async function load() {
  rows.value = await api.sensors()
  for (const s of rows.value.filter((x) => x.enabled)) {
    try {
      const h = await api.sensorHistory(s.id, 24, 60)
      histories.value[s.id] = h.points
    } catch { /* 单条失败不影响别的 */ }
  }
}

let timer = 0
let clock = 0
onMounted(async () => {
  robot.start()
  await load()
  timer = window.setInterval(load, 15000)
  clock = window.setInterval(() => { tick.value = Date.now() }, 1000)
})
onBeforeUnmount(() => { window.clearInterval(timer); window.clearInterval(clock) })
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>环境监测</span>
        <span class="muted small">近 24 小时趋势；超限阈值来自「设备管理 → 环境传感器」的标定值</span>
        <span class="grow" />
        <router-link class="btn btn-sm" :to="{ name: 'env-device' }">去标定传感器</router-link>
      </div>

      <div v-if="!cards.length" class="empty">
        <b>还没有环境传感器</b>
        <span>到「设备管理 → 环境传感器」登记一台，填了阈值才会告警</span>
        <router-link class="btn btn-sm primary" :to="{ name: 'env-device' }">去登记</router-link>
      </div>

      <div v-else class="cards">
        <div v-for="c in cards" :key="c.s.id" class="card" :class="c.level">
          <div class="head">
            <span class="name">{{ c.s.name }}</span>
            <span class="tag" :class="c.level === 'critical' ? 'danger' : c.level === 'warn' ? 'warn' : c.level === 'ok' ? 'ok' : ''">
              {{ LEVEL_TEXT[c.level] }}
            </span>
          </div>
          <div class="value">
            <b>{{ c.s.latest ? c.s.latest.value : '—' }}</b>
            <span>{{ c.s.unit }}</span>
          </div>
          <svg class="spark" viewBox="0 0 100 28" preserveAspectRatio="none">
            <path :d="c.spark" fill="none" stroke="currentColor" stroke-width="1.4" />
          </svg>
          <div class="foot">
            <span>{{ c.s.kind_label }} · {{ c.s.location || '未填位置' }}</span>
            <span class="dim">{{ ago(c.s.latest?.ts ?? null) }}</span>
          </div>
          <div v-if="!c.s.calibrated" class="uncal">未标定阈值，不参与告警</div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.small { font-size: 12px; }
.empty {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 10px; color: #9fd2ff;
}
.empty b { font-size: 15px; color: #dceeff; }
.empty span { font-size: 12.5px; color: #7fa8cc; }
.cards {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px; padding: 4px; overflow: auto;
}
.card {
  position: relative; padding: 10px 12px 8px;
  background: linear-gradient(180deg, rgba(0, 96, 170, 0.5), rgba(0, 50, 100, 0.6));
  border: 1px solid rgba(111, 227, 255, 0.28);
  border-left: 3px solid rgba(111, 227, 255, 0.7);
  border-radius: 4px;
  color: #7fe3ff;
}
.card.ok { border-left-color: #35d67a; color: #6ff0a5; }
.card.warn { border-left-color: #ffcf3f; color: #ffe08a; }
.card.critical {
  border-left-color: #ff5a5a; color: #ff9a9a;
  box-shadow: 0 0 16px rgba(255, 70, 70, 0.25) inset;
}
.card.uncalibrated { border-left-color: #6f8aa8; color: #8fb6d6; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.name { font-size: 13px; font-weight: 600; color: #eaf7ff; }
.value { display: flex; align-items: baseline; gap: 6px; margin: 8px 0 2px; }
.value b { font-size: 26px; font-weight: 800; color: #fff; font-variant-numeric: tabular-nums; }
.value span { font-size: 12px; color: #9fd2ff; }
.spark { width: 100%; height: 34px; display: block; opacity: 0.85; }
.foot {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 11.5px; color: #9fd2ff; margin-top: 4px;
}
.uncal { margin-top: 6px; font-size: 11px; color: #ffcf3f; }
</style>
