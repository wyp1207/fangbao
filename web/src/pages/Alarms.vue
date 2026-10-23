<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type AlarmItem } from '@/api'
import { useRobotStore } from '@/stores/robot'
import { useAuthStore } from '@/stores/auth'
import DarkSelect from '@/components/DarkSelect.vue'
import { ApiError } from '@/api/client'
import { toast } from '@/composables/useToast'

const robot = useRobotStore()
const route = useRoute()
const router = useRouter()

/** 从首页/铃铛跳过来时带筛选：?status=unacked&level=critical&q=xx */
function applyQuery() {
  const { status, level, q } = route.query
  const st = typeof status === 'string' ? status : ''
  if (st === 'unacked') ackFilter.value = 'new'
  else if (['new', 'acked', 'handled', 'closed'].includes(st)) ackFilter.value = st
  if (level === 'critical' || level === 'warn') levelFilter.value = String(level)
  if (typeof q === 'string' && q) keyword.value = q
}
const auth = useAuthStore()
const message = ref('')

const keyword = ref('')
const levelFilter = ref('')
const ackFilter = ref('')
const page = ref(1)
const focusRow = ref<number | null>(null)
const pageSize = 10

function fmtVal(v: unknown): string {
  if (typeof v !== 'number') return ''
  const a = Math.abs(v)
  if (a >= 100) return v.toFixed(1)
  if (a >= 10) return v.toFixed(1)
  return v.toFixed(2)
}

const levelText: Record<string, string> = { critical: '严重', warn: '提醒' }
const levelOptions = [
  { value: '', label: '全部' },
  { value: 'critical', label: '严重' },
  { value: 'warn', label: '提醒' },
]
const ackOptions = [
  { value: '', label: '全部' },
  { value: 'new', label: '待确认' },
  { value: 'acked', label: '已确认' },
  { value: 'handled', label: '已处置' },
  { value: 'closed', label: '已关闭' },
]
const STATUS_TEXT: Record<string, string> = {
  new: '待确认', acked: '已确认', handled: '已处置', closed: '已关闭',
}
const STATUS_TONE: Record<string, string> = {
  new: 'danger', acked: 'warn', handled: '', closed: 'ok',
}

const rows = ref<AlarmItem[]>([])
const total = ref(0)

const filtered = computed(() => rows.value)   // 服务端已过滤，这里只给模板用

async function reload() {
  const res = await api.alarmQuery({
    status: ackFilter.value,
    level: levelFilter.value,
    q: keyword.value,
    limit: pageSize,
    offset: (page.value - 1) * pageSize,
  })
  rows.value = res.items
  total.value = res.total
}

// 服务端已按 limit/offset 分页，这里不能再切一次（否则第 2 页起永远是空的）
const paged = computed(() => filtered.value)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function goto(p: number) {
  page.value = Math.min(Math.max(1, p), pageCount.value)
  await reload()
}

const cfg = ref<Record<string, unknown>>({})

const rules = computed(() => [
  { metric: 'lel（可燃气体）', threshold: '见传感器标定', note: '在「环境传感器」里填阈值，留空不报' },
  { metric: 'smoke（烟雾）', threshold: '见传感器标定', note: '在「环境传感器」里填阈值' },
  { metric: 'temperature（温度）', threshold: '见传感器标定', note: '在「环境传感器」里填阈值' },
  {
    metric: 'battery（电量）',
    threshold: `${cfg.value['alarm.battery_warn'] ?? 20}% 提醒 / ${cfg.value['alarm.battery_critical'] ?? 10}% 严重`,
    note: '可在「系统设置 → 告警」里改，立即生效',
  },
  {
    metric: 'offline（通信中断）',
    threshold: `${cfg.value['alarm.offline_after_s'] ?? 10}s`,
    note: '超过这个时间没收到数据就报',
  },
  {
    metric: 'sustain（持续确认）',
    threshold: cfg.value['alarm.sustain_s'] ? `${cfg.value['alarm.sustain_s']}s` : '不启用',
    note: '条件持续够久才报，防抖',
  },
  { metric: 'estop（driver_port）', threshold: '立即', note: '硬件按钮，只读' },
])

async function ack(id: number) {
  message.value = ''
  try {
    await robot.ackAlarm(id)
    toast('告警已确认（恢复仍由数据判断）', 'ok')
    await reload()
  } catch (e) {
    message.value = e instanceof Error ? e.message : '确认失败'
  }
}

// ---- 看录像 ----
function goPlayback(a: AlarmItem) {
  const when = (a.started_at ?? '').replace('T', ' ')
  void router.push({
    name: 'record-playback',
    query: {
      video: String(a.camera_id ?? ''),
      date: when.slice(0, 10),
      t: when.slice(11, 19),
    },
  })
}

// ---- 转工单 ----
async function asWorkOrder(a: AlarmItem) {
  try {
    const o = await api.createWorkOrder({
      title: a.message || `${a.metric} 告警`,
      source: 'alarm',
      source_id: a.id,
      level: a.level,
      due_hours: a.level === 'critical' ? 4 : 24,
      description: `告警 #${a.id} · ${a.metric} · ${(a.started_at ?? '').replace('T', ' ')}`,
    })
    toast(`已生成工单 ${o.code ?? ''}，去「工单」页派单`, 'ok', 4000)
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '转工单失败', 'danger')
  }
}

// ---- 处置 / 关闭 ----
const acting = ref<AlarmItem | null>(null)
const actMode = ref<'handle' | 'close'>('handle')
const actNote = ref('')
const actResolution = ref('handled')
const resolutionOptions = [
  { value: 'handled', label: '已处理（恢复/人工解决）' },
  { value: 'defect', label: '设备缺陷（需维修）' },
  { value: 'misreport', label: '误报' },
  { value: 'ignored', label: '忽略（不处理）' },
]

function openAct(a: AlarmItem, mode: 'handle' | 'close') {
  acting.value = a
  actMode.value = mode
  actNote.value = ''
  actResolution.value = 'handled'
}

async function submitAct() {
  if (!acting.value) return
  if (!actNote.value.trim()) return
  try {
    if (actMode.value === 'handle') {
      await api.handleAlarm(acting.value.id, actNote.value.trim())
      toast('已处置并记录', 'ok')
    } else {
      await api.closeAlarm(acting.value.id, actResolution.value, actNote.value.trim())
      toast('已关闭', 'ok')
    }
    acting.value = null
    await reload()
  } catch (e) {
    toast(e instanceof Error ? e.message : '操作失败', 'danger')
  }
}

function reset() {
  keyword.value = ''
  levelFilter.value = ''
  ackFilter.value = ''
  page.value = 1
}

function exportCsv() {
  const head = ['时间', '指标', '级别', '状态', '内容', '确认人', '延时(s)']
  const data = rows.value.map((a) => [
    (a.started_at ?? '').replace('T', ' ').slice(0, 19),
    a.metric, a.level === 'critical' ? '严重' : '提醒',
    a.status === 'new' ? '未确认' : a.status === 'acked' ? '已确认' : a.status === 'handled' ? '已处置' : '已关闭',
    (a.message ?? '').replace(/[\r\n,]/g, ' '),
    a.acked_by ?? '',
    a.acked_at ? Math.round((Date.parse(a.acked_at) - Date.parse(a.started_at)) / 1000) : '',
  ])
  const csv = [head, ...data]
    .map((r) => r.map((c: unknown) => `"${String(c ?? '').replace(/"/g, '""')}"`).join(','))
    .join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `告警_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
  toast(`已导出 ${data.length} 条`, 'ok')
}

onMounted(async () => {
  const f = Number(route.query.focus ?? 0)
  if (f) {
    focusRow.value = f
    await nextTick()
    const el = document.querySelector(`tr[data-alarm-id="${f}"]`)
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    window.setTimeout(() => { focusRow.value = null }, 2400)
  }
  applyQuery()
  await reload()
  void robot.refreshAlarms()
  try { cfg.value = (await api.settings()).values } catch { /* 设置读不到就显示默认 */ }
})
watch(() => route.fullPath, async () => { if (route.name === 'alarms') { applyQuery(); page.value = 1; await reload() } })
watch([levelFilter, ackFilter], async () => { page.value = 1; await reload() })
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
        <button class="btn btn-sm ok" @click="page = 1; reload()">查询</button>
        <button class="btn btn-sm warn" @click="reset">重置</button>
        <span class="grow" />
        <button class="btn btn-sm" @click="robot.refreshAlarms()">刷新</button>
        <button class="btn btn-sm" @click="exportCsv">导出 CSV</button>
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
          <tr v-for="(a, i) in paged" :key="a.id">
            <td>{{ (page - 1) * pageSize + i + 1 }}</td>
            <td class="num dim">{{ a.started_at.replace('T', ' ').slice(0, 19) }}</td>
            <td>
              <span class="tag p-badge">{{ a.priority ?? '—' }}</span>
              <span class="tag" :class="a.level === 'critical' ? 'danger' : 'warn'">{{ levelText[a.level] }}</span>
            </td>
            <td>{{ a.message }}</td>
            <td>
              <span class="tag" :class="STATUS_TONE[a.status ?? 'new']">{{ STATUS_TEXT[a.status ?? 'new'] }}</span>
              <div class="dim small" v-if="a.handled_at">{{ a.handled_by }} · {{ a.handle_note }}</div>
              <div class="dim small" v-if="a.closed_at">{{ a.closed_by }} · {{ a.resolution }}</div>
            </td>
            <td>
              <div class="row-actions">
                <button class="act" title="确认告警" :disabled="!!a.acked_at || !auth.canWrite" @click="ack(a.id)">✓</button>
                <button class="act" title="处置（写清做了什么）" :disabled="!auth.canWrite || !!a.closed_at" @click="openAct(a, 'handle')">✎</button>
                <button v-if="a.camera_id" class="act" title="看当时的录像"
                        @click="goPlayback(a)">▶</button>
                <button v-if="!a.work_order_id" class="act" title="转工单（派单闭环）"
                        :disabled="!auth.canWrite || !!a.closed_at" @click="asWorkOrder(a)">→</button>
                <button v-else class="act ok" :title="`已生成工单 #${a.work_order_id}，点击查看`"
                        @click="router.push({ name: 'work-orders', query: { focus: a.work_order_id } })">
                  工单{{ a.work_order_id }}
                </button>
                <button class="act danger" title="关闭（给结论）" :disabled="!auth.canWrite || !!a.closed_at" @click="openAct(a, 'close')">⏹</button>
                <button class="act" title="回看这个时刻的录像" @click="router.push({ name: 'record-playback', query: { date: a.started_at.slice(0, 10), t: a.started_at.slice(11, 19) } })">⟲</button>
              </div>
            </td>
          </tr>
          <tr v-if="!filtered.length">
            <td colspan="6" class="dim">暂无告警 · 环境类阈值未标定，不会产生环境告警</td>
          </tr>
        </tbody>
      </table>

      <div class="pager">
        <span>共 {{ total }} 条 · 第 {{ page }}/{{ pageCount }} 页</span>
        <span class="spacer" />
        <button :disabled="page <= 1" @click="goto(page - 1)">上一页</button>
        <button
          v-for="n in Math.min(pageCount, 7)" :key="n"
          :class="{ on: n === page }" @click="goto(n)"
        >{{ n }}</button>
        <button :disabled="page >= pageCount" @click="goto(page + 1)">下一页</button>
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

    <!-- 处置 / 关闭 -->
    <div v-if="acting" class="modal-mask" @click.self="acting = null">
      <div class="modal">
        <div class="panel-title">
          <span>{{ actMode === 'handle' ? '处置告警' : '关闭告警' }}</span>
        </div>
        <p class="dim small" style="margin: 0 0 10px">{{ acting.message }}</p>

        <label v-if="actMode === 'close'" class="fld">
          <span>结论</span>
          <DarkSelect v-model="actResolution" :options="resolutionOptions" width="100%" />
        </label>
        <label class="fld">
          <span>{{ actMode === 'handle' ? '处置说明（必填）' : '备注' }}</span>
          <textarea class="input area" v-model="actNote" rows="3"
                    :placeholder="actMode === 'handle' ? '例：已通知班组现场确认，充电后电量回到 45%' : '例：已恢复，无需处理'" />
        </label>

        <div class="modal-actions">
          <button class="btn" @click="acting = null">取消</button>
          <button class="btn primary" :disabled="!actNote.trim()" @click="submitAct">
            {{ actMode === 'handle' ? '提交处置' : '确认关闭' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-mask { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 14, 30, 0.66); }
.modal {
  width: 480px; padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
}
.fld { display: block; margin-bottom: 11px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; }
.input.area { resize: vertical; font-family: inherit; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
.small { font-size: 11.5px; }

.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel:first-of-type { flex: 1; min-height: 0; overflow: auto; }
.small { font-size: 12px; line-height: 1.6; }
.num { font-variant-numeric: tabular-nums; }

tr.flash td { background: rgba(255, 176, 46, .28) !important; box-shadow: inset 0 0 0 1px rgba(255,176,46,.7); }

.p-badge { background: rgba(255, 168, 46, .18); color: #ffc355; margin-right: 4px; }
</style>
