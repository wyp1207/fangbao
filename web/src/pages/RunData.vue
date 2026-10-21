<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import DarkSelect from '@/components/DarkSelect.vue'

interface Point {
  ts: string
  battery: number | null
  speed: number | null
  voltage: number | null
  online: boolean
}
interface Stats {
  battery_min: number | null
  battery_max: number | null
  battery_avg: number | null
  speed_max: number | null
  distance_m: number
  offline_ratio: number
  from: string
  to: string
}

const hours = ref('24')
const rangeOptions = [
  { value: '6', label: '近 6 小时' },
  { value: '24', label: '近 24 小时' },
  { value: '72', label: '近 3 天' },
  { value: '168', label: '近 7 天' },
]

const series = ref<Point[]>([])
const stats = ref<Stats | null>(null)
const count = ref(0)
const loading = ref(false)
const error = ref('')

const W = 1000
const H = 180

function path(key: 'battery' | 'speed'): string {
  const pts = series.value.filter((p) => p[key] !== null)
  if (pts.length < 2) return ''
  const vals = pts.map((p) => p[key] as number)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const flat = max - min < 1e-6           // 数值恒定：画在中线，别贴着坐标轴
  const span = max - min || 1
  return pts
    .map((p, i) => {
      const x = (i / (pts.length - 1)) * W
      const y = flat ? H / 2 : H - 12 - ((p[key] as number) - min) / span * (H - 24)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

const batteryRange = computed(() =>
  stats.value ? `${stats.value.battery_min ?? '—'} ~ ${stats.value.battery_max ?? '—'} %` : '—',
)
const lastPoint = computed(() => series.value[series.value.length - 1] ?? null)
const recent = computed(() => [...series.value].slice(-12).reverse())

function isFlat(key: 'battery' | 'speed'): boolean {
  const vals = series.value.map((p) => p[key]).filter((v): v is number => v !== null)
  if (vals.length < 2) return false
  return Math.max(...vals) - Math.min(...vals) < 1e-6
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.telemetry(Number(hours.value), 240)
    series.value = res.series as Point[]
    stats.value = res.stats as Stats | null
    count.value = res.count
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>运行数据</span>
        <span class="muted small">每 10 秒采一次，保留 7 天；数据来自机器人真实上报</span>
      </div>

      <div class="toolbar">
        <label>范围</label>
        <DarkSelect v-model="hours" :options="rangeOptions" width="140px" @update:model-value="load" />
        <button class="btn btn-sm ok" :disabled="loading" @click="load">刷新</button>
        <span class="grow" />
        <span class="muted small">共 {{ count }} 个采样点</span>
      </div>

      <p v-if="error" class="danger small">{{ error }}</p>

      <div v-if="!count" class="empty">
        <b>这段时间还没有采样</b>
        <span>服务刚启动时会先在后台采 10 秒一个点，等一会儿再刷新</span>
      </div>

      <template v-else>
        <div class="stat-row">
          <div class="stat">
            <span>电量区间</span><b>{{ batteryRange }}</b>
          </div>
          <div class="stat">
            <span>电量均值</span><b>{{ stats?.battery_avg ?? '—' }} %</b>
          </div>
          <div class="stat">
            <span>速度峰值</span><b>{{ stats?.speed_max ?? '—' }} m/s</b>
          </div>
          <div class="stat">
            <span>行驶里程</span><b>{{ stats?.distance_m ?? 0 }} m</b>
          </div>
          <div class="stat">
            <span>离线占比</span><b>{{ stats?.offline_ratio ?? 0 }} %</b>
          </div>
          <div class="stat">
            <span>最后采样</span><b class="dim">{{ lastPoint?.ts?.slice(11, 19) ?? '—' }}</b>
          </div>
        </div>

        <div class="chart">
          <div class="chart-head">
            <span>电量（%）</span>
            <em v-if="isFlat('battery')" class="flat">这段时间电量没有变化（{{ series[series.length - 1]?.battery }}%）</em>
            <em v-else>{{ series[0]?.ts?.slice(5, 16) }} → {{ series[series.length - 1]?.ts?.slice(5, 16) }}</em>
          </div>
          <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" class="svg">
            <path d="M0,168 L1000,168" class="axis" />
            <path :d="path('battery')" class="line battery" />
          </svg>
        </div>

        <div class="chart">
          <div class="chart-head">
            <span>速度（m/s）</span>
            <em v-if="isFlat('speed')" class="flat">这段时间速度恒定（{{ series[series.length - 1]?.speed }} m/s）</em>
          </div>
          <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" class="svg">
            <path d="M0,168 L1000,168" class="axis" />
            <path :d="path('speed')" class="line speed" />
          </svg>
        </div>
      </template>

      <div v-if="count" class="recent">
        <div class="chart-head"><span>最近采样</span><em>每 10 秒一条</em></div>
        <table class="grid">
          <thead>
            <tr><th style="width:160px">时间</th><th>电量</th><th>电压</th><th>速度</th><th>在线</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in recent" :key="p.ts">
              <td class="num dim">{{ p.ts.replace('T', ' ') }}</td>
              <td class="num">{{ p.battery ?? '—' }} %</td>
              <td class="num">{{ p.voltage ?? '—' }} V</td>
              <td class="num">{{ p.speed ?? '—' }} m/s</td>
              <td><span class="tag" :class="p.online ? 'ok' : 'danger'">{{ p.online ? '在线' : '离线' }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.small { font-size: 12px; }
.empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: #9fd2ff; }
.empty b { font-size: 15px; color: #dceeff; }
.empty span { font-size: 12.5px; color: #7fa8cc; }
.stat-row {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px; margin-bottom: 12px;
}
.stat {
  padding: 8px 10px; border-radius: 4px;
  background: linear-gradient(180deg, rgba(0, 96, 170, 0.42), rgba(0, 50, 100, 0.5));
  border-left: 2px solid rgba(111, 227, 255, 0.6);
}
.stat span { display: block; font-size: 11.5px; color: #9fd2ff; margin-bottom: 4px; }
.stat b { font-size: 17px; color: #fff; font-variant-numeric: tabular-nums; }
.chart { margin-bottom: 14px; }
.chart-head { display: flex; justify-content: space-between; font-size: 12px; color: #9fd2ff; margin-bottom: 4px; }
.chart-head em { font-style: normal; color: #6f9dc4; font-size: 11px; }
.chart-head em.flat { color: #ffe08a; }
.svg { width: 100%; height: 150px; display: block; }
.axis { stroke: rgba(111, 227, 255, 0.2); stroke-width: 1; fill: none; }
.line { fill: none; stroke-width: 1.8; vector-effect: non-scaling-stroke; }
.line.battery { stroke: #35d67a; }
.line.speed { stroke: #7fe3ff; }
.recent { margin-top: 6px; }
</style>
