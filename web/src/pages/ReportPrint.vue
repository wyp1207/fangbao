<script setup lang="ts">
/**
 * 报表打印版（浏览器「打印 → 另存为 PDF」）。
 *
 * 为什么不做服务端 PDF：中文字体要额外打字体包，排版还得自己写；
 * 浏览器打印出来的 PDF 字体、分页、页眉都是现成的，客户签字盖章也够用。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api'

const route = useRoute()
const data = ref<Record<string, any> | null>(null)
const err = ref('')
const printed = ref(false)

const dateFrom = computed(() => (typeof route.query.date_from === 'string' ? route.query.date_from : ''))
const dateTo = computed(() => (typeof route.query.date_to === 'string' ? route.query.date_to : ''))

const now = new Date()
const stamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`

function dur(sec: number | null): string {
  if (sec === null || sec === undefined) return '—'
  if (sec < 60) return `${Math.round(sec)} 秒`
  if (sec < 3600) return `${Math.round(sec / 60)} 分钟`
  return `${(sec / 3600).toFixed(1)} 小时`
}

async function load() {
  try {
    data.value = (await api.reportSummary(
      dateFrom.value || undefined,
      dateTo.value || undefined,
    )) as unknown as Record<string, any>
  } catch (e) {
    err.value = e instanceof Error ? e.message : '读取失败'
  }
}

function close() {
  window.close()
}

function print() {
  printed.value = true
  window.print()
}

onMounted(async () => {
  await load()
  // 支持 ?auto=1 打开即弹打印框
  if (route.query.auto === '1' && data.value) setTimeout(print, 400)
})
</script>

<template>
  <div class="sheet">
    <div class="toolbar no-print">
      <button class="btn" @click="print">打印 / 另存为 PDF</button>
      <button class="btn" @click="close()">关闭</button>
      <span class="hint">在打印对话框里选「另存为 PDF」即可得到 PDF 文件</span>
    </div>

    <p v-if="err" class="err">{{ err }}</p>

    <template v-if="data">
      <header class="head">
        <h1>巡检报表</h1>
        <div class="meta">
          <span>统计区间：{{ data.range.from }} ~ {{ data.range.to }}</span>
          <span>生成时间：{{ stamp }}</span>
        </div>
      </header>

      <section>
        <h2>一、总览</h2>
        <table>
          <tbody>
            <tr><th>告警总数</th><td>{{ data.alarms.total }}</td><th>严重</th><td>{{ data.alarms.by_level[0]?.count ?? 0 }}</td><th>提醒</th><td>{{ data.alarms.by_level[1]?.count ?? 0 }}</td></tr>
            <tr><th>确认率</th><td>{{ data.alarms.ack_rate ?? '—' }}%</td><th>关闭率</th><td>{{ data.alarms.close_rate ?? '—' }}%</td><th>平均确认</th><td>{{ dur(data.alarms.avg_ack_s) }}</td></tr>
            <tr><th>在线率</th><td>{{ data.operations.online_ratio ?? '—' }}%</td><th>行驶里程</th><td>{{ data.operations.distance_m }} m</td><th>电量区间</th><td>{{ data.operations.battery_min ?? '—' }} ~ {{ data.operations.battery_max ?? '—' }}%</td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>二、告警分布</h2>
        <table>
          <thead><tr><th style="width: 50%">指标</th><th>条数</th></tr></thead>
          <tbody>
            <tr v-for="m in data.alarms.by_metric" :key="m.key"><td>{{ m.key }}</td><td>{{ m.count }}</td></tr>
            <tr v-if="!data.alarms.by_metric.length"><td colspan="2">区间内没有告警</td></tr>
          </tbody>
        </table>

        <table v-if="data.alarms.by_resolution?.length" class="gap">
          <thead><tr><th style="width: 50%">关闭结论</th><th>条数</th></tr></thead>
          <tbody>
            <tr v-for="r in data.alarms.by_resolution" :key="r.key"><td>{{ r.label }}</td><td>{{ r.count }}</td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>三、环境监测</h2>
        <table>
          <thead>
            <tr><th>传感器</th><th>条数</th><th>最小</th><th>最大</th><th>超限次数</th><th>超限占比</th></tr>
          </thead>
          <tbody>
            <tr v-for="e in data.environment" :key="e.name">
              <td>{{ e.name }}（{{ e.unit }}）</td><td>{{ e.count }}</td>
              <td>{{ e.min }}</td><td>{{ e.max }}</td><td>{{ e.over }}</td><td>{{ e.over_rate }}%</td>
            </tr>
            <tr v-if="!data.environment?.length"><td colspan="6">区间内没有环境读数（传感器未接入或未标定）</td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>四、巡检与点位</h2>
        <table>
          <tbody>
            <tr><th>点位总数</th><td>{{ data.points?.total ?? 0 }}</td><th>被模板覆盖</th><td>{{ data.points?.covered_by_templates ?? 0 }}</td><th>未覆盖</th><td>{{ data.points?.uncovered ?? 0 }}</td></tr>
            <tr><th>任务模板</th><td>{{ data.templates?.total ?? 0 }}</td><th>动作总数</th><td>{{ data.templates?.actions ?? 0 }}</td><th>涉及地图</th><td>{{ data.templates?.maps ?? 0 }}</td></tr>
          </tbody>
        </table>
        <table v-if="data.points?.by_group?.length" class="gap">
          <thead><tr><th>分组</th><th>点位数</th><th>涉及地图</th></tr></thead>
          <tbody>
            <tr v-for="g in data.points.by_group" :key="g.group"><td>{{ g.group }}</td><td>{{ g.points }}</td><td>{{ g.maps }}</td></tr>
          </tbody>
        </table>
      </section>

      <footer>
        <div class="sign">
          <span>巡检人：____________</span>
          <span>审核人：____________</span>
          <span>日期：____________</span>
        </div>
        <p class="note">
          说明：本报表数据来自平台记录。参数未标定的测点不计入告警统计（见「环境监测」表）。
        </p>
      </footer>
    </template>
  </div>
</template>

<style>
/* 打印版强制浅色：大屏配色打印出来全是黑的 */
.sheet {
  background: #fff; color: #111;
  max-width: 820px; margin: 0 auto; padding: 24px 12px 40px;
  font-size: 12.5px; line-height: 1.6;
}
.sheet .toolbar {
  display: flex; align-items: center; gap: 10px; margin-bottom: 16px;
}
.sheet .toolbar .btn {
  background: #f0f4f8; color: #123; border: 1px solid #9bb; padding: 6px 12px;
  border-radius: 4px; cursor: pointer;
}
.sheet .hint { color: #666; font-size: 12px; }
.sheet .head { border-bottom: 2px solid #123; padding-bottom: 8px; margin-bottom: 14px; }
.sheet h1 { font-size: 20px; margin: 0 0 6px; text-align: center; letter-spacing: 4px; }
.sheet .meta { display: flex; justify-content: space-between; font-size: 11.5px; color: #444; }
.sheet h2 { font-size: 13.5px; margin: 18px 0 6px; }
.sheet table { width: 100%; border-collapse: collapse; margin-bottom: 6px; }
.sheet table.gap { margin-top: 8px; }
.sheet th, .sheet td { border: 1px solid #888; padding: 4px 6px; text-align: left; }
.sheet thead th { background: #eef2f6; }
.sheet tbody th { background: #f7f9fb; font-weight: 600; width: 90px; }
.sheet .err { color: #b00; }
.sheet footer { margin-top: 24px; }
.sheet .sign { display: flex; gap: 28px; margin-bottom: 10px; }
.sheet .note { font-size: 11px; color: #555; border-top: 1px solid #ccc; padding-top: 6px; }

@page { size: A4; margin: 14mm 12mm; }
@media print {
  .no-print { display: none !important; }
  .sheet { max-width: none; padding: 0; font-size: 11.5px; }
  section { break-inside: avoid; }
  h2 { break-after: avoid; }
}
</style>
