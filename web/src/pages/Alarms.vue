<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRobotStore } from '@/stores/robot'
import { useAuthStore } from '@/stores/auth'

const robot = useRobotStore()
const auth = useAuthStore()
const message = ref('')

const rules = [
  { metric: 'lel（可燃气体）', threshold: '未标定', note: '需要现场安全员给定 ppm 阈值' },
  { metric: 'smoke（烟雾）', threshold: '未标定', note: '现场标定' },
  { metric: 'temperature（温度）', threshold: '未标定', note: '现场标定' },
  { metric: 'battery（电量）', threshold: '20% 提醒 / 10% 严重', note: '平台建议值，可改' },
  { metric: 'offline（通信中断）', threshold: '10s', note: '轮询连续失败' },
  { metric: 'estop（driver_port）', threshold: '立即', note: '硬件按钮，只读' },
]

async function ack(id: number) {
  message.value = ''
  try {
    await robot.ackAlarm(id)
  } catch (e) {
    message.value = e instanceof Error ? e.message : '确认失败'
  }
}

onMounted(() => {
  void robot.refreshAlarms()
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>告警（{{ robot.alarms.length }}）</span>
        <button class="btn" @click="robot.refreshAlarms()">刷新</button>
      </div>

      <table class="grid">
        <thead>
          <tr><th>时间</th><th>级别</th><th>告警</th><th>状态</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="a in robot.alarms" :key="a.id">
            <td class="mono muted">{{ a.started_at.slice(11, 19) }}</td>
            <td>
              <span class="tag" :class="a.level === 'critical' ? 'danger' : 'warn'">
                {{ a.level === 'critical' ? '严重' : '提醒' }}
              </span>
            </td>
            <td>{{ a.message }}</td>
            <td>
              <span v-if="a.acked_at" class="muted">
                已确认 · {{ a.acked_by }} · {{ a.acked_at.slice(11, 19) }}
              </span>
              <span v-else class="danger">未确认</span>
            </td>
            <td>
              <button
                class="btn"
                :disabled="!!a.acked_at || !auth.canWrite"
                @click="ack(a.id)"
              >确认</button>
            </td>
          </tr>
          <tr v-if="!robot.alarms.length">
            <td colspan="5" class="muted">暂无告警</td>
          </tr>
        </tbody>
      </table>
      <p v-if="message" class="danger small">{{ message }}</p>
      <p class="muted small">
        告警确认不等于恢复：这里记的是“人看到了”，恢复由数据自己判断。
        告警目前存内存，重启即清空——W5 落库后才做历史检索。
      </p>
    </section>

    <section class="panel">
      <div class="panel-title">规则与阈值</div>
      <table class="grid">
        <thead>
          <tr><th>指标</th><th>阈值</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in rules" :key="r.metric">
            <td>{{ r.metric }}</td>
            <td><span class="tag" :class="r.threshold === '未标定' ? 'warn' : ''">{{ r.threshold }}</span></td>
            <td class="muted">{{ r.note }}</td>
          </tr>
        </tbody>
      </table>
      <p class="muted small">
        未标定的指标一律不求值，也不显示 0 或“正常”来冒充——这是有意的。
      </p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel:first-of-type { flex: 1; min-height: 0; overflow: auto; }
.small { font-size: 12px; line-height: 1.6; }
.mono { font-variant-numeric: tabular-nums; }
</style>
