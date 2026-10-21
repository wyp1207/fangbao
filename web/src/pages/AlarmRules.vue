<script setup lang="ts">
import { useRobotStore } from '@/stores/robot'
import { toast } from '@/composables/useToast'

const robot = useRobotStore()

const rules = [
  { metric: 'battery', label: '电量', warn: '20%', critical: '10%', note: '平台建议值，可在后端配置改', frozen: false },
  { metric: 'offline', label: '通信中断', warn: '10s', critical: '30s', note: '轮询连续失败计时', frozen: false },
  { metric: 'estop', label: '硬件急停 driver_port', warn: '—', critical: '立即', note: '硬件按钮，只读，不可下发', frozen: true },
  { metric: 'lel', label: '可燃气体', warn: '未标定', critical: '未标定', note: '等现场安全员给阈值', frozen: true },
  { metric: 'smoke', label: '烟雾', warn: '未标定', critical: '未标定', note: '等现场标定', frozen: true },
  { metric: 'temperature', label: '温度', warn: '未标定', critical: '未标定', note: '等现场标定', frozen: true },
]
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>告警规则</span>
        <span class="muted">本期只读；改阈值要后端配置 + 重启，暂不放开页面编辑</span>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">序号</th>
            <th style="width: 220px">指标</th>
            <th style="width: 140px">提醒阈值</th>
            <th style="width: 140px">严重阈值</th>
            <th>说明</th>
            <th style="width: 120px">状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rules" :key="r.metric">
            <td>{{ i + 1 }}</td>
            <td>{{ r.label }}</td>
            <td class="num" :class="r.warn === '未标定' ? 'warn' : ''">{{ r.warn }}</td>
            <td class="num" :class="r.critical === '未标定' ? 'warn' : ''">{{ r.critical }}</td>
            <td class="dim">{{ r.note }}</td>
            <td>
              <span class="tag" :class="r.frozen ? 'warn' : 'ok'">{{ r.frozen ? '只读' : '生效中' }}</span>
            </td>
          </tr>
        </tbody>
      </table>

      <p class="muted small">
        未标定的指标一律不求值，也不会显示 0 或「正常」——这是有意的，避免把没测的东西说成安全。
      </p>

      <div class="actions">
        <button class="btn btn-sm" @click="robot.refreshAlarms()">刷新告警状态</button>
        <button class="btn btn-sm" disabled title="阈值编辑需要后端配置，暂不开放">编辑阈值</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.small { font-size: 12px; line-height: 1.8; }
.actions { display: flex; gap: 8px; margin-top: 14px; }
.num { font-variant-numeric: tabular-nums; }
.warn { color: #ffe08a; }
</style>
