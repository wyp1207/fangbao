<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRobotStore } from '@/stores/robot'
import { useAuthStore } from '@/stores/auth'
import DarkSelect from '@/components/DarkSelect.vue'

const robot = useRobotStore()
const auth = useAuthStore()
const message = ref('')

const keyword = ref('')
const levelFilter = ref('')
const ackFilter = ref('')

const levelText: Record<string, string> = { critical: '严重', warn: '提醒' }
const levelOptions = [
  { value: '', label: '全部' },
  { value: 'critical', label: '严重' },
  { value: 'warn', label: '提醒' },
]
const ackOptions = [
  { value: '', label: '全部' },
  { value: 'unacked', label: '未确认' },
  { value: 'acked', label: '已确认' },
]

const filtered = computed(() =>
  robot.alarms.filter((a) => {
    if (keyword.value && !a.message.includes(keyword.value)) return false
    if (levelFilter.value && a.level !== levelFilter.value) return false
    if (ackFilter.value === 'unacked' && a.acked_at) return false
    if (ackFilter.value === 'acked' && !a.acked_at) return false
    return true
  }),
)

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

function reset() {
  keyword.value = ''
  levelFilter.value = ''
  ackFilter.value = ''
}

onMounted(() => { void robot.refreshAlarms() })
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>告警列表</span>
        <span class="muted">确认不等于恢复，恢复由数据判断</span>
      </div>

      <div class="toolbar">
        <label>关键词</label>
        <input class="input" v-model="keyword" placeholder="输入告警内容搜索" />
        <label>级别</label>
        <DarkSelect v-model="levelFilter" :options="levelOptions" width="110px" />
        <label>状态</label>
        <DarkSelect v-model="ackFilter" :options="ackOptions" width="110px" />
        <button class="btn btn-sm" @click="robot.refreshAlarms()">查询</button>
        <button class="btn btn-sm" @click="reset">重置</button>
        <span class="grow" />
        <button class="btn btn-sm" @click="robot.refreshAlarms()">刷新</button>
        <button class="btn btn-sm" disabled>导出</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">序号</th>
            <th style="width: 150px">时间</th>
            <th style="width: 90px">级别</th>
            <th>告警内容</th>
            <th style="width: 160px">状态</th>
            <th style="width: 100px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(a, i) in filtered" :key="a.id">
            <td>{{ i + 1 }}</td>
            <td class="num dim">{{ a.started_at.replace('T', ' ').slice(0, 19) }}</td>
            <td>
              <span class="tag" :class="a.level === 'critical' ? 'danger' : 'warn'">{{ levelText[a.level] }}</span>
            </td>
            <td>{{ a.message }}</td>
            <td>
              <span v-if="a.acked_at" class="dim">已确认 · {{ a.acked_by }} · {{ a.acked_at.slice(11, 19) }}</span>
              <span v-else class="danger">未确认</span>
            </td>
            <td>
              <button class="link-btn" :disabled="!!a.acked_at || !auth.canWrite" @click="ack(a.id)">确认</button>
            </td>
          </tr>
          <tr v-if="!filtered.length">
            <td colspan="6" class="dim">暂无告警 · 环境类阈值未标定，不会产生环境告警</td>
          </tr>
        </tbody>
      </table>

      <div class="pager">
        <span>共 {{ filtered.length }} 条</span>
        <span class="spacer" />
        <button class="on">1</button>
        <button disabled>下一页</button>
      </div>

      <p v-if="message" class="danger small">{{ message }}</p>
    </section>

    <section class="panel">
      <div class="panel-title"><span>规则与阈值</span></div>
      <table class="grid">
        <thead><tr><th>指标</th><th style="width: 220px">阈值</th><th>说明</th></tr></thead>
        <tbody>
          <tr v-for="r in rules" :key="r.metric">
            <td>{{ r.metric }}</td>
            <td><span class="tag" :class="r.threshold === '未标定' ? 'warn' : ''">{{ r.threshold }}</span></td>
            <td class="dim">{{ r.note }}</td>
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
.num { font-variant-numeric: tabular-nums; }
</style>
