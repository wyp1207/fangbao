<script setup lang="ts">
const rules = [
  { metric: 'lel（可燃气体）', threshold: '未标定', note: '需要现场安全员给定 ppm 阈值' },
  { metric: 'smoke（烟雾）', threshold: '未标定', note: '现场标定' },
  { metric: 'temperature（温度）', threshold: '未标定', note: '现场标定' },
  { metric: 'battery（电量）', threshold: '20% 提醒 / 10% 严重', note: '平台建议值' },
  { metric: '离线', threshold: '10s', note: '轮询 + WS 心跳' },
  { metric: '急停（driver_port）', threshold: '立即', note: '硬件按钮，只读' },
  { metric: '任务错误（state=ERROR）', threshold: '立即', note: '对账发现' },
  { metric: '自检失败', threshold: '任一 false', note: '/system/self_test' },
]
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">当前告警</div>
      <p class="muted small">
        暂无告警。阈值未标定的指标不参与求值，也不会产生告警——这是刻意的，不拿占位值冒充现场标准。
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
            <td>
              <span class="tag" :class="r.threshold === '未标定' ? 'warn' : ''">{{ r.threshold }}</span>
            </td>
            <td class="muted">{{ r.note }}</td>
          </tr>
        </tbody>
      </table>
      <p class="muted small">
        阈值由前端修改 → 落 alarm_rule 表 → 告警引擎引用，改完即时生效（W5 实现）。
      </p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.small { font-size: 12px; line-height: 1.6; }
</style>
