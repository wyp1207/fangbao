<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type TaskItem } from '@/api'
import { useRobotStore } from '@/stores/robot'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'

const robot = useRobotStore()

type Tab = 'tasks' | 'alarms'
const tab = ref<Tab>('tasks')

const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const keyword = ref('')
const from = ref('')
const to = ref('')

const stateText: Record<string, string> = {
  WAITTING: '等待执行', WORKING: '执行中', PAUSED: '已暂停',
  CANCELLED: '已取消', ERROR: '错误', COMPLETE: '已完成',
}
const stateTone: Record<string, string> = {
  COMPLETE: 'ok', WORKING: 'ok', ERROR: 'danger', CANCELLED: 'danger', PAUSED: 'warn',
}

const tabs = [
  { key: 'tasks' as Tab, label: '任务记录' },
  { key: 'alarms' as Tab, label: '告警记录' },
]

const taskRows = computed(() =>
  tasks.value.filter((t) => {
    if (keyword.value && !t.name.includes(keyword.value)) return false
    return true
  }),
)

const alarmRows = computed(() =>
  robot.alarms.filter((a) => {
    if (keyword.value && !a.message.includes(keyword.value)) return false
    if (from.value && a.started_at.slice(0, 10) < from.value) return false
    if (to.value && a.started_at.slice(0, 10) > to.value) return false
    return true
  }),
)

async function loadTasks() {
  loading.value = true
  try {
    tasks.value = await api.tasks()
  } catch {
    toast('任务读取失败', 'danger')
  } finally {
    loading.value = false
  }
}

function csvEscape(v: unknown): string {
  const s = v === null || v === undefined ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function download(name: string, header: string[], rows: (string | number | null)[][]) {
  if (!rows.length) {
    toast('当前列表为空，不导出空文件', 'warn')
    return
  }
  const body = [header, ...rows].map((r) => r.map(csvEscape).join(',')).join('\r\n')
  // BOM：Excel 打开中文不乱码
  const blob = new Blob(['\ufeff' + body], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
  toast(`已导出 ${rows.length} 条到 ${name}`, 'ok')
}

function exportCurrent() {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')
  if (tab.value === 'tasks') {
    download(`tasks-${stamp}.csv`,
      ['任务名', '状态', '动作数', '进度原值', '循环', '任务ID'],
      taskRows.value.map((t) => [
        t.name, stateText[t.state] ?? t.state,
        Array.isArray(t.sub_tasks) ? t.sub_tasks.length : 0,
        t.progress, t.loop_flag ? '是' : '否', t.id,
      ]))
  } else {
    download(`alarms-${stamp}.csv`,
      ['时间', '级别', '内容', '确认状态', '确认人', '确认时间'],
      alarmRows.value.map((a) => [
        a.started_at.replace('T', ' ').slice(0, 19),
        a.level === 'critical' ? '严重' : '提醒',
        a.message, a.acked_at ? '已确认' : '未确认',
        a.acked_by ?? '', a.acked_at ?? '',
      ]))
  }
}

function reset() {
  keyword.value = ''
  from.value = ''
  to.value = ''
}

onMounted(async () => {
  await loadTasks()
  void robot.refreshAlarms()
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>数据查询</span>
        <span class="muted">导出的就是当前列表里的数据，不做“看起来有数据”的假导出</span>
      </div>

      <div class="tabs-row">
        <button
          v-for="t in tabs" :key="t.key"
          class="tab-btn" :class="{ on: tab === t.key }"
          @click="tab = t.key"
        >{{ t.label }}（{{ t.key === 'tasks' ? taskRows.length : alarmRows.length }}）</button>
      </div>

      <div class="toolbar">
        <label>关键词</label>
        <input class="input" v-model="keyword" :placeholder="tab === 'tasks' ? '任务名称' : '告警内容'" />
        <template v-if="tab === 'alarms'">
          <label>起</label>
          <input class="input date" type="date" v-model="from" />
          <label>止</label>
          <input class="input date" type="date" v-model="to" />
        </template>
        <button class="btn btn-sm warn" @click="reset">重置</button>
        <span class="grow" />
        <button class="btn btn-sm" :disabled="loading" @click="loadTasks">刷新</button>
        <button class="btn btn-sm primary" @click="exportCurrent">导出 CSV</button>
      </div>

      <table v-if="tab === 'tasks'" class="grid">
        <thead>
          <tr><th style="width: 60px">序号</th><th>任务名称</th><th style="width: 110px">状态</th><th style="width: 90px">动作数</th><th style="width: 150px">进度</th><th style="width: 80px">循环</th><th style="width: 160px">任务 ID</th></tr>
        </thead>
        <tbody>
          <tr v-for="(t, i) in taskRows" :key="t.id">
            <td>{{ i + 1 }}</td>
            <td>{{ t.name }}</td>
            <td><span class="tag" :class="stateTone[t.state] ?? ''">{{ stateText[t.state] ?? t.state }}</span></td>
            <td class="num">{{ Array.isArray(t.sub_tasks) ? t.sub_tasks.length : 0 }}</td>
            <td class="dim">未标定（原值 {{ t.progress }}）</td>
            <td>{{ t.loop_flag ? '是' : '否' }}</td>
            <td class="num dim">{{ t.id.slice(0, 8) }}…</td>
          </tr>
          <tr v-if="!taskRows.length"><td colspan="7" class="dim">没有匹配的任务</td></tr>
        </tbody>
      </table>

      <table v-else class="grid">
        <thead>
          <tr><th style="width: 60px">序号</th><th style="width: 170px">时间</th><th style="width: 90px">级别</th><th>内容</th><th style="width: 120px">状态</th><th style="width: 140px">确认人</th></tr>
        </thead>
        <tbody>
          <tr v-for="(a, i) in alarmRows" :key="a.id">
            <td>{{ i + 1 }}</td>
            <td class="num dim">{{ a.started_at.replace('T', ' ').slice(0, 19) }}</td>
            <td><span class="tag" :class="a.level === 'critical' ? 'danger' : 'warn'">{{ a.level === 'critical' ? '严重' : '提醒' }}</span></td>
            <td>{{ a.message }}</td>
            <td :class="a.acked_at ? 'dim' : 'danger'">{{ a.acked_at ? '已确认' : '未确认' }}</td>
            <td class="dim">{{ a.acked_by ?? '—' }}</td>
          </tr>
          <tr v-if="!alarmRows.length"><td colspan="6" class="dim">没有匹配的告警</td></tr>
        </tbody>
      </table>

      <p class="muted small">
        告警目前是服务端内存里的环形缓冲（重启即清空）；状态/环境历史采样表与 7 天/180 天保留策略在 W5 落库，
        那之后这里的“按时间范围查询”才是真正查库。
      </p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.tabs-row { display: flex; gap: 6px; margin-bottom: 10px; }
.tab-btn {
  padding: 5px 16px; font-size: 13px; cursor: pointer;
  color: #cfe8ff;
  background: linear-gradient(180deg, rgba(20, 130, 220, 0.45), rgba(0, 70, 140, 0.6));
  border: 1px solid rgba(111, 227, 255, 0.35);
}
.tab-btn.on {
  color: #062f66; font-weight: 700;
  background: linear-gradient(180deg, #b9ecff, #4fc3ff);
  box-shadow: 0 0 12px rgba(120, 220, 255, 0.7);
}
.date { min-width: 130px; }
.small { font-size: 12px; line-height: 1.7; }
.num { font-variant-numeric: tabular-nums; }
</style>
