<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import DarkSelect from '@/components/DarkSelect.vue'

interface Summary {
  range: { from: string; to: string }
  alarms: {
    total: number
    by_level: { key: string; label: string; count: number }[]
    by_metric: { key: string; count: number }[]
    acked: number
    handled: number
    closed: number
    ack_rate: number | null
    close_rate: number | null
    avg_ack_s: number | null
    avg_close_s: number | null
    by_resolution: { key: string; label: string; count: number }[]
  }
  environment: { name: string; kind: string; unit: string; count: number; min: number; max: number; over: number; over_rate: number }[]
  operations: {
    samples: number
    online_ratio: number | null
    distance_m: number
    battery_min: number | null
    battery_max: number | null
    battery_avg: number | null
  }
}

const preset = ref('7d')
const dateFrom = ref('')
const dateTo = ref('')
const data = ref<Summary | null>(null)
const loading = ref(false)
const exportUrl = computed(() => {
  const q: string[] = []
  if (dateFrom.value) q.push(`date_from=${dateFrom.value}`)
  if (dateTo.value) q.push(`date_to=${dateTo.value}`)
  return `/api/v1/reports/export.xlsx${q.length ? '?' + q.join('&') : ''}`
})

const presets = [
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: 'week', label: '本周' },
  { value: 'month', label: '本月' },
  { value: 'custom', label: '自定义' },
]

function iso(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function applyPreset(v: string) {
  preset.value = v
  const now = new Date()
  if (v === '7d') {
    dateFrom.value = iso(new Date(now.getTime() - 6 * 864e5))
    dateTo.value = iso(now)
  } else if (v === '30d') {
    dateFrom.value = iso(new Date(now.getTime() - 29 * 864e5))
    dateTo.value = iso(now)
  } else if (v === 'week') {
    const day = (now.getDay() + 6) % 7
    dateFrom.value = iso(new Date(now.getTime() - day * 864e5))
    dateTo.value = iso(now)
  } else if (v === 'month') {
    dateFrom.value = iso(new Date(now.getFullYear(), now.getMonth(), 1))
    dateTo.value = iso(now)
  }
  if (v !== 'custom') void load()
}

function duration(sec: number | null): string {
  if (sec === null || sec === undefined) return '—'
  if (sec < 60) return `${Math.round(sec)} 秒`
  if (sec < 3600) return `${Math.round(sec / 60)} 分钟`
  return `${(sec / 3600).toFixed(1)} 小时`
}

async function load() {
  loading.value = true
  try {
    data.value = await api.reportSummary(dateFrom.value || undefined, dateTo.value || undefined) as unknown as Summary
  } finally {
    loading.value = false
  }
}

onMounted(() => applyPreset('7d'))
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>巡检报表</span>
        <span class="muted small">告警闭环率、处置时长、环境超限、运行里程——汇报直接用</span>
        <span class="grow" />
        <a class="btn btn-sm primary" :href="exportUrl" target="_blank">导出 Excel</a>
      </div>

      <div class="toolbar">
        <label>区间</label>
        <DarkSelect :model-value="preset" :options="presets" width="130px" @update:model-value="applyPreset" />
        <input class="input date" type="date" v-model="dateFrom" :disabled="preset !== 'custom'" />
        <span class="dim">至</span>
        <input class="input date" type="date" v-model="dateTo" :disabled="preset !== 'custom'" />
        <button class="btn btn-sm ok" :disabled="loading" @click="load">统计</button>
        <span class="grow" />
        <span class="muted small" v-if="data">{{ data.range.from }} ~ {{ data.range.to }}</span>
      </div>

      <div v-if="!data" class="dim small">读取中…</div>

      <template v-else>
        <div class="kpis">
          <div class="kpi"><span>告警总数</span><b>{{ data.alarms.total }}</b></div>
          <div class="kpi danger"><span>严重</span><b>{{ data.alarms.by_level[0]?.count ?? 0 }}</b></div>
          <div class="kpi warn"><span>提醒</span><b>{{ data.alarms.by_level[1]?.count ?? 0 }}</b></div>
          <div class="kpi"><span>确认率</span><b>{{ data.alarms.ack_rate ?? '—' }}<small>%</small></b></div>
          <div class="kpi"><span>关闭率</span><b>{{ data.alarms.close_rate ?? '—' }}<small>%</small></b></div>
          <div class="kpi"><span>平均确认</span><b class="sm">{{ duration(data.alarms.avg_ack_s) }}</b></div>
          <div class="kpi"><span>平均关闭</span><b class="sm">{{ duration(data.alarms.avg_close_s) }}</b></div>
          <div class="kpi"><span>在线率</span><b>{{ data.operations.online_ratio ?? '—' }}<small>%</small></b></div>
          <div class="kpi"><span>行驶里程</span><b>{{ data.operations.distance_m }}<small>m</small></b></div>
          <div class="kpi"><span>电量区间</span><b class="sm">{{ data.operations.battery_min ?? '—' }} ~ {{ data.operations.battery_max ?? '—' }}<small>%</small></b></div>
        </div>

        <div class="cols">
          <div class="block">
            <div class="block-title">告警按指标 Top</div>
            <table class="grid">
              <thead><tr><th>指标</th><th style="width: 90px">条数</th></tr></thead>
              <tbody>
                <tr v-for="m in data.alarms.by_metric" :key="m.key">
                  <td>{{ m.key }}</td><td class="num">{{ m.count }}</td>
                </tr>
                <tr v-if="!data.alarms.by_metric.length"><td colspan="2" class="dim">区间内没有告警</td></tr>
              </tbody>
            </table>
          </div>

          <div class="block">
            <div class="block-title">关闭结论分布</div>
            <table class="grid">
              <thead><tr><th>结论</th><th style="width: 90px">条数</th></tr></thead>
              <tbody>
                <tr v-for="r in data.alarms.by_resolution" :key="r.key">
                  <td>{{ r.label }}</td><td class="num">{{ r.count }}</td>
                </tr>
                <tr v-if="!data.alarms.by_resolution.length"><td colspan="2" class="dim">还没有关闭的告警</td></tr>
              </tbody>
            </table>
          </div>

          <div class="block wide">
            <div class="block-title">环境传感器</div>
            <table class="grid">
              <thead>
                <tr><th>传感器</th><th style="width: 90px">条数</th><th style="width: 90px">最小</th>
                    <th style="width: 90px">最大</th><th style="width: 90px">超限</th><th style="width: 90px">占比</th></tr>
              </thead>
              <tbody>
                <tr v-for="e in data.environment" :key="e.name">
                  <td>{{ e.name }} <span class="dim">{{ e.unit }}</span></td>
                  <td class="num">{{ e.count }}</td>
                  <td class="num">{{ e.min }}</td>
                  <td class="num">{{ e.max }}</td>
                  <td class="num" :class="{ danger: e.over > 0 }">{{ e.over }}</td>
                  <td class="num">{{ e.over_rate }}%</td>
                </tr>
                <tr v-if="!data.environment.length"><td colspan="6" class="dim">区间内没有环境读数</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <p class="muted small">
          口径：告警按产生时间归入区间；平均确认 = 确认时间 − 产生时间；平均关闭 = 关闭时间 − 产生时间；
          在线率来自 10 秒遥测采样，没有采样时显示「—」而不是编一个数。
        </p>
      </template>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.small { font-size: 12px; }
.num { font-variant-numeric: tabular-nums; }
.input.date { width: 140px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin-bottom: 14px; }
.kpi {
  padding: 9px 11px; border-radius: 4px;
  background: linear-gradient(180deg, rgba(0, 96, 170, 0.42), rgba(0, 50, 100, 0.5));
  border-left: 2px solid rgba(111, 227, 255, 0.6);
}
.kpi span { display: block; font-size: 11.5px; color: #9fd2ff; margin-bottom: 3px; }
.kpi b { font-size: 20px; color: #fff; font-variant-numeric: tabular-nums; }
.kpi b.sm { font-size: 15px; }
.kpi small { font-size: 11px; color: #9fd2ff; margin-left: 2px; }
.kpi.danger { border-left-color: #ff5a5a; }
.kpi.warn { border-left-color: #ffcf3f; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.block.wide { grid-column: 1 / -1; }
.block-title { font-size: 12px; color: #ffe08a; margin-bottom: 6px; letter-spacing: 0.06em; }
.danger { color: #ff8a8a; }
</style>
