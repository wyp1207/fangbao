<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRobotStore } from '@/stores/robot'
import { api } from '@/api'
import AnimatedNumber from '@/components/AnimatedNumber.vue'

const robot = useRobotStore()
const health = ref<Awaited<ReturnType<typeof api.deepHealth>> | null>(null)

const snap = computed(() => robot.snapshot)
const g = computed(() => snap.value?.galileo ?? {})
const pose = computed(() => robot.pose)

function fmt(v: unknown, digits = 2): string {
  return typeof v === 'number' ? v.toFixed(digits) : '—'
}

const fields = computed(() => [
  { label: '位姿 X', value: fmt(pose.value?.x, 3), unit: 'm' },
  { label: '位姿 Y', value: fmt(pose.value?.y, 3), unit: 'm' },
  { label: '朝向 angle', value: fmt(pose.value?.angle_deg, 1), unit: '°' },
  { label: '导航状态', value: snap.value?.status?.status ?? '—', unit: '' },
  { label: '速度', value: fmt(g.value.currentSpeedX), unit: 'm/s' },
  { label: '角速度', value: fmt(g.value.currentSpeedTheta, 3), unit: 'rad/s' },
  { label: '电压', value: fmt(g.value.power, 1), unit: 'V' },
  { label: '目标距离', value: fmt(g.value.targetDistance), unit: 'm' },
])

const healthRows = computed(() => {
  const h = health.value as Record<string, any> | null
  if (!h) return []
  const cache = h.cache ?? {}
  const rows: { k: string; v: string }[] = [
    { k: '链路在线', v: cache.online ? '是' : '否' },
    { k: '数据年龄', v: cache.age_s != null ? `${Number(cache.age_s).toFixed(1)} s` : '—' },
    { k: '连续失败', v: String(cache.consecutive_failures ?? '—') },
    { k: '累计轮询', v: String(cache.poll_count ?? '—') },
    { k: '事件循环延迟', v: h.loop_lag_ms != null ? `${h.loop_lag_ms} ms` : '—' },
  ]
  for (const svc of h.services ?? []) {
    rows.push({
      k: `后台循环 · ${svc.name}`,
      v: `${svc.running ? '运行中' : '已停止'} · 运行 ${Number(svc.uptime_s ?? 0).toFixed(0)}s · 重启 ${svc.restarts ?? 0} 次`,
    })
  }
  return rows
})

async function loadHealth() {
  try {
    health.value = await api.deepHealth()
  } catch {
    health.value = null
  }
}

let timer = 0
onMounted(() => {
  void robot.loadMaps()
  void loadHealth()
  timer = window.setInterval(loadHealth, 5000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>机器人状态</span>
        <span class="tag" :class="robot.online ? 'ok' : 'danger'">{{ robot.online ? '在线' : '离线' }}</span>
        <span class="muted small" v-if="snap">数据年龄 {{ snap.age_s.toFixed(1) }}s</span>
      </div>

      <div class="grid4">
        <div v-for="f in fields" :key="f.label" class="cell">
          <span class="k">{{ f.label }}</span>
          <b class="v">{{ f.value }}<small v-if="f.unit">{{ f.unit }}</small></b>
        </div>
      </div>

      <div class="row">
        <div class="chip">
          <span>电量</span>
          <b class="gold"><AnimatedNumber :value="snap?.info?.battery ?? null" suffix="%" /></b>
        </div>
        <div class="chip">
          <span>硬件急停</span>
          <b :class="snap?.info?.driver_port ? 'red' : 'green'">{{ snap?.info?.driver_port ? '已按下' : '未按下' }}</b>
        </div>
        <div class="chip">
          <span>固件</span><b>{{ snap?.info?.info?.version ?? '—' }}</b>
        </div>
        <div class="chip">
          <span>导航源</span><b>{{ snap?.info?.slam_type ?? '—' }}</b>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title"><span>接口健康</span></div>
      <table class="grid" v-if="healthRows.length">
        <thead><tr><th>项目</th><th>值</th></tr></thead>
        <tbody>
          <tr v-for="r in healthRows" :key="r.k">
            <td>{{ r.k }}</td>
            <td class="num">{{ r.v }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted small">健康检查读取失败（后端不可达）</p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.grid4 { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin-bottom: 12px; }
.cell {
  padding: 10px 12px;
  background: linear-gradient(180deg, rgba(0, 110, 190, 0.45), rgba(0, 70, 140, 0.55));
  border: 1px solid rgba(111, 227, 255, 0.22);
}
.k { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 4px; }
.v { font-size: 20px; color: #fff; font-variant-numeric: tabular-nums; }
.v small { font-size: 11px; color: #9fd2ff; margin-left: 3px; }
.row { display: flex; gap: 10px; flex-wrap: wrap; }
.chip {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 12px;
  background: rgba(0, 70, 140, 0.5);
  border: 1px solid rgba(111, 227, 255, 0.25);
  font-size: 12px; color: #9fd2ff;
}
.chip b { color: #eaf7ff; font-size: 14px; }
.gold { color: #ffd54a; }
.green { color: #7dff9a; }
.red { color: #ff8a8a; }
.small { font-size: 12px; }
</style>
