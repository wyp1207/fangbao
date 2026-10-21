<script setup lang="ts">
import { computed } from 'vue'
import { useRobotStore } from '@/stores/robot'

const robot = useRobotStore()

/** 只画“现在能看到的一条曲线”，历史接口在 W5 接。
 *  没有真数据就画空，不造假。 */
const samples = computed(() => {
  const snap = robot.snapshot
  if (!snap) return []
  const v = snap.galileo
  return [
    { label: '电压', value: v.power, unit: 'V' },
    { label: '电量', value: snap.info.battery, unit: '%' },
    { label: '前进速度', value: v.currentSpeedX, unit: 'm/s' },
    { label: '角速度', value: v.currentSpeedTheta, unit: 'rad/s' },
    { label: '目标距离', value: v.targetDistance, unit: 'm' },
  ]
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>实时读数</span>
        <span class="muted small">历史曲线与 CSV 导出在 W5 接</span>
      </div>
      <div class="cards">
        <div v-for="s in samples" :key="s.label" class="card">
          <div class="muted small">{{ s.label }}</div>
          <div class="kpi">
            {{ typeof s.value === 'number' ? s.value.toFixed(2) : '—' }}
            <span class="unit muted">{{ s.unit }}</span>
          </div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title">历史与导出</div>
      <p class="muted small">
        状态采样表（1s 原始 7 天 / 1 分钟聚合 180 天，按天分区）与环境采样表在 W5 建。
        导出按钮在数据链路打通前保持禁用，避免导出空文件被当成“功能已交付”。
      </p>
      <div class="actions">
        <button class="btn" disabled>导出任务 CSV</button>
        <button class="btn" disabled>导出告警 CSV</button>
        <button class="btn" disabled>导出审计日志</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel:first-of-type { flex: 1; min-height: 0; overflow: auto; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.card { background: var(--bg-2); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
.unit { font-size: 12px; margin-left: 4px; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.small { font-size: 12px; line-height: 1.6; }
</style>
