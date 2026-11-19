<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type AlarmItem, type AiResultItem } from '@/api'
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
  // 整页 AI 告警的缩略图：reload 后只打一次批量接口
  void loadAiThumbs()
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

// ---- AI 告警：批量缩略图 + 证据面板 ----
// 每行 AI 告警都要一张 60×44 缩略图。逐行调单条接口会把首屏打成 N 个请求，
// 所以 reload 后统一打一次 /ai/results/by-alarms，点开面板直接用批量结果里的
// 完整数据（图 + 框 + 元数据），只有缓存里没有时才回退单条接口。
const aiCache = ref<Record<number, AiResultItem>>({})

function isAiAlarm(a: AlarmItem): boolean {
  return (a.metric ?? '').startsWith('ai_')
}

async function loadAiThumbs() {
  const ids = rows.value.filter(isAiAlarm).map((a) => a.id)
  if (!ids.length) {
    aiCache.value = {}
    return
  }
  try {
    const res = await api.aiResultsByAlarms(ids)
    const map: Record<number, AiResultItem> = {}
    for (const [k, v] of Object.entries(res.items)) map[Number(k)] = v
    aiCache.value = map
  } catch {
    // 缩略图拿不到不能挡住告警列表本身，缺图的行走「图」字回退
    aiCache.value = {}
  }
}

function aiThumb(a: AlarmItem): string {
  return aiCache.value[a.id]?.image || ''
}

// ---- 证据面板（大图 + 检测框 + 元数据）----
const evidence = ref<AlarmItem | null>(null)
const evidenceShot = ref<AiResultItem | null>(null)
const evidenceLoading = ref(false)
const evidenceError = ref('')
const shotW = ref(0)
const shotH = ref(0)

// 上一张/下一张只在当前页的 AI 告警之间切换，不跨页拉新数据
const aiRows = computed(() => paged.value.filter(isAiAlarm))
const evidenceIndex = computed(() => {
  if (!evidence.value) return -1
  const id = evidence.value.id
  return aiRows.value.findIndex((a) => a.id === id)
})
const canPrev = computed(() => evidenceIndex.value > 0)
const canNext = computed(() => evidenceIndex.value >= 0 && evidenceIndex.value < aiRows.value.length - 1)

const levelBoxColor: Record<string, string> = { critical: '#ff4d4f', warn: '#ffd23f' }
const boxColor = computed(() => levelBoxColor[evidence.value?.level ?? ''] ?? '#ffd23f')
const boxLabelTone = computed(() => (evidence.value?.level === 'critical' ? '#ffffff' : '#08243f'))

const metaCamera = computed(() => {
  const s = evidenceShot.value
  return s?.camera_name || (s?.external_camera_id != null ? `#${s.external_camera_id}` : '—')
})
const metaAlgorithm = computed(
  () => evidenceShot.value?.algorithm_name || evidenceShot.value?.algorithm || '—',
)
const metaConfidence = computed(() => `${Math.round((evidenceShot.value?.confidence ?? 0) * 100)}%`)
const metaTime = computed(() => {
  const raw = evidenceShot.value?.ts || evidence.value?.started_at || ''
  return raw.replace('T', ' ').slice(0, 19) || '—'
})
const metaLevel = computed(() => levelText[evidence.value?.level ?? ''] ?? evidence.value?.level ?? '—')
const metaBoxes = computed(() => evidenceShot.value?.boxes.length ?? 0)
const downloadName = computed(
  () => `ai_alarm_${evidence.value?.id ?? 0}_result_${evidenceShot.value?.id ?? 0}.jpg`,
)

async function openEvidence(a: AlarmItem) {
  evidence.value = a
  evidenceError.value = ''
  shotW.value = 0
  shotH.value = 0
  const cached = aiCache.value[a.id]
  if (cached) {
    evidenceShot.value = cached
    evidenceLoading.value = false
    return
  }
  evidenceShot.value = null
  evidenceLoading.value = true
  try {
    evidenceShot.value = await api.aiResultByAlarm(a.id)
  } catch (e) {
    evidenceError.value = e instanceof ApiError ? e.message : '没有关联的检测结果'
  } finally {
    evidenceLoading.value = false
  }
}

function closeEvidence() {
  evidence.value = null
  evidenceShot.value = null
  evidenceError.value = ''
}

function stepEvidence(delta: number) {
  const target = aiRows.value[evidenceIndex.value + delta]
  if (target) void openEvidence(target)
}

function onEvidenceKey(e: KeyboardEvent) {
  if (!evidence.value) return
  if (e.key === 'Escape') {
    e.preventDefault()
    closeEvidence()
  } else if (e.key === 'ArrowLeft') {
    stepEvidence(-1)
  } else if (e.key === 'ArrowRight') {
    stepEvidence(1)
  }
}

function boxStyle(b: Record<string, unknown>): Record<string, string> {
  const rect = (b.rect ?? {}) as Record<string, number>
  if (!shotW.value || !shotH.value) return { display: 'none' }
  const x = Number(rect.x ?? 0)
  const y = Number(rect.y ?? 0)
  const w = Number(rect.width ?? 0)
  const h = Number(rect.height ?? 0)
  return {
    left: `${(x / shotW.value) * 100}%`,
    top: `${(y / shotH.value) * 100}%`,
    width: `${(w / shotW.value) * 100}%`,
    height: `${(h / shotH.value) * 100}%`,
  }
}

// 框上标签按框自己的置信度（score）显示，不取整条结果的置信度
function boxLabel(b: Record<string, unknown>): string {
  const s = Number(b.score ?? 0)
  return Number.isFinite(s) ? `${Math.round(s * 100)}%` : ''
}

function onShotLoad(e: Event) {
  const el = e.target as HTMLImageElement
  shotW.value = el.naturalWidth
  shotH.value = el.naturalHeight
}

// ---- 搁置（检修/标定期间临时屏蔽）----
const shelveFor = ref<AlarmItem | null>(null)
const shelveMinutes = ref(30)
const shelveReason = ref('')

function openShelve(a: AlarmItem) {
  shelveFor.value = a
  shelveMinutes.value = 30
  shelveReason.value = ''
}

async function saveShelve() {
  const a = shelveFor.value
  if (!a) return
  if (!shelveReason.value.trim()) { toast('必须写搁置原因（审计要留痕）', 'warn'); return }
  try {
    await api.shelveAlarm(a.id, Number(shelveMinutes.value), shelveReason.value.trim())
    toast(`已搁置 ${shelveMinutes.value} 分钟`, 'ok')
    shelveFor.value = null
    await reload()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '搁置失败', 'danger')
  }
}

async function unshelve(a: AlarmItem) {
  try {
    await api.unshelveAlarm(a.id)
    toast('已解除搁置', 'ok')
    await reload()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '解除失败', 'danger')
  }
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

async function reset() {
  keyword.value = ''
  levelFilter.value = ''
  ackFilter.value = ''
  page.value = 1
  // 清完必须重查，否则筛选条件没了、列表还是旧的
  await reload()
  toast('已重置', 'ok', 2000)
}

// CSV 公式注入：以 = + - @ 开头的单元格在 Excel 里会被当公式执行
function csvCell(v: unknown): string {
  let text = String(v ?? '')
  if (/^[=+\-@\t\r]/.test(text)) text = "'" + text
  return `"${text.replace(/"/g, '""')}"`
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
    .map((r) => r.map(csvCell).join(','))
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
  window.addEventListener('keydown', onEvidenceKey)
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

onUnmounted(() => window.removeEventListener('keydown', onEvidenceKey))
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
        <button type="button" class="btn btn-sm ok" @click="page = 1; reload()">查询</button>
        <button type="button" class="btn btn-sm warn" @click="reset">重置</button>
        <span class="grow" />
        <button type="button" class="btn btn-sm" @click="robot.refreshAlarms()">刷新</button>
        <button type="button" class="btn btn-sm" @click="exportCsv">导出 CSV</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">序号</th>
            <th style="width: 150px">时间</th>
            <th style="width: 90px">级别</th>
            <th>告警内容</th>
            <th style="width: 160px">状态</th>
            <th style="width: 240px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(a, i) in paged" :key="a.id">
            <td>{{ (page - 1) * pageSize + i + 1 }}</td>
            <td class="num dim">{{ a.started_at.replace('T', ' ').slice(0, 19) }}</td>
            <td>
              <span v-if="a.shelved_until" class="tag shelved" title="搁置中，到期自动恢复">搁置</span>
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
                <button type="button" class="act" title="确认告警" :disabled="!!a.acked_at || !auth.canWrite" @click="ack(a.id)">✓</button>
                <button type="button" class="act" title="处置（写清做了什么）" :disabled="!auth.canWrite || !!a.closed_at" @click="openAct(a, 'handle')">✎</button>
                <button type="button" v-if="a.camera_id" class="act" title="看当时的录像"
                        @click="goPlayback(a)">▶</button>
                <button type="button" v-if="isAiAlarm(a) && aiThumb(a)" class="ai-thumb-btn"
                        title="查看 AI 告警证据" @click="openEvidence(a)">
                  <img class="ai-thumb" :src="aiThumb(a)" alt="AI 检测缩略图" />
                </button>
                <button type="button" v-else-if="isAiAlarm(a)" class="act" title="查看 AI 检测框图片"
                        @click="openEvidence(a)">图</button>
                <button type="button" v-if="!a.work_order_id" class="act" title="转工单（派单闭环）"
                        :disabled="!auth.canWrite || !!a.closed_at" @click="asWorkOrder(a)">→</button>
                <button type="button" v-else class="act ok" :title="`已生成工单 #${a.work_order_id}，点击查看`"
                        @click="router.push({ name: 'work-orders', query: { focus: a.work_order_id } })">
                  工单{{ a.work_order_id }}
                </button>
                <button type="button" v-if="!a.shelved_until" class="act" title="搁置（检修时临时别报）"
                        :disabled="!auth.canWrite || !!a.closed_at" @click="openShelve(a)">⏸</button>
                <button type="button" v-else class="act warn" :title="`已搁置到 ${a.shelved_until}`" @click="unshelve(a)">▶</button>
                <button type="button" class="act danger" title="关闭（给结论）" :disabled="!auth.canWrite || !!a.closed_at" @click="openAct(a, 'close')">⏹</button>
                <button type="button" class="act" title="回看这个时刻的录像" @click="router.push({ name: 'record-playback', query: { date: a.started_at.slice(0, 10), t: a.started_at.slice(11, 19) } })">⟲</button>
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
        <button type="button" :disabled="page <= 1" @click="goto(page - 1)">上一页</button>
        <button type="button"
          v-for="n in Math.min(pageCount, 7)" :key="n"
          :class="{ on: n === page }" @click="goto(n)"
        >{{ n }}</button>
        <button type="button" :disabled="page >= pageCount" @click="goto(page + 1)">下一页</button>
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
          <button type="button" class="btn" @click="acting = null">取消</button>
          <button type="button" class="btn primary" :disabled="!actNote.trim()" @click="submitAct">
            {{ actMode === 'handle' ? '提交处置' : '确认关闭' }}
          </button>
        </div>
      </div>
    </div>
  </div>

    <!-- AI 告警证据面板：左大图 + 框，右元数据，底部下载/切换/关闭 -->
    <div v-if="evidence" class="ev-mask" @click.self="closeEvidence">
      <div class="ev-dlg" role="dialog" aria-label="AI 告警证据">
        <div class="ev-head">
          <b>AI 告警证据</b>
          <span class="tag" :class="evidence.level === 'critical' ? 'danger' : 'warn'">{{ metaLevel }}</span>
          <span class="dim small">告警 #{{ evidence.id }}</span>
          <span class="grow" />
          <button type="button" class="act" title="关闭（ESC）" @click="closeEvidence">✕</button>
        </div>

        <div class="ev-body">
          <div class="ev-left">
            <p v-if="evidenceLoading" class="dim">读取检测结果…</p>
            <p v-else-if="evidenceError" class="danger small">{{ evidenceError }}</p>
            <div v-else-if="evidenceShot && evidenceShot.image" class="ev-frame">
              <img :key="evidenceShot.id" :src="evidenceShot.image" alt="AI 检测大图" @load="onShotLoad" />
              <span v-for="(b, i) in evidenceShot.boxes" :key="i" class="ev-box"
                    :style="{ ...boxStyle(b), borderColor: boxColor }">
                <em :style="{ background: boxColor, color: boxLabelTone }">{{ boxLabel(b) }}</em>
              </span>
            </div>
            <p v-else class="dim small">这条告警没有保存检测图。</p>
          </div>

          <aside class="ev-meta">
            <div class="ev-row"><span>相机</span><b>{{ metaCamera }}</b></div>
            <div class="ev-row"><span>算法</span><b>{{ metaAlgorithm }}</b></div>
            <div class="ev-row"><span>置信度</span><b>{{ metaConfidence }}</b></div>
            <div class="ev-row"><span>时间</span><b>{{ metaTime }}</b></div>
            <div class="ev-row"><span>告警级别</span><b>{{ metaLevel }}</b></div>
            <div class="ev-row"><span>告警 ID</span><b>{{ evidence.id }}</b></div>
            <div class="ev-row"><span>框数</span><b>{{ metaBoxes }}</b></div>
          </aside>
        </div>

        <div class="ev-actions">
          <a v-if="evidenceShot?.image" class="btn btn-sm primary" :href="evidenceShot.image"
             :download="downloadName">下载原图</a>
          <span class="grow" />
          <button type="button" class="btn btn-sm" :disabled="!canPrev" @click="stepEvidence(-1)">上一张</button>
          <button type="button" class="btn btn-sm" :disabled="!canNext" @click="stepEvidence(1)">下一张</button>
          <button type="button" class="btn btn-sm" @click="closeEvidence">关闭</button>
        </div>
      </div>
    </div>

    <div v-if="shelveFor" class="mask" @click.self="shelveFor = null">
      <div class="shelve-dlg">
        <h3>搁置告警 #{{ shelveFor.id }}</h3>
        <p class="dim small">{{ shelveFor.message }}</p>
        <label class="fld"><span>搁置时长（分钟，1–10080）</span>
          <input class="input" type="number" min="1" max="10080" v-model.number="shelveMinutes" /></label>
        <label class="fld"><span>原因（必填，审计留痕）</span>
          <input class="input" v-model="shelveReason" placeholder="如：探头标定中 / 检修动火 / 更换传感器" /></label>
        <p class="dim small">搁置期间同指标不会再产生新告警；到期自动恢复，也可手动解除。</p>
        <div class="acts">
          <button type="button" class="btn btn-sm" @click="shelveFor = null">取消</button>
          <button type="button" class="btn btn-sm primary" @click="saveShelve">确认搁置</button>
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

/* AI 告警缩略图：60×44，替代「图」字按钮；hover 高亮边框 */
.ai-thumb-btn { padding: 0; border: 2px solid rgba(111, 227, 255, .3); background: #001a33;
  line-height: 0; cursor: pointer; }
.ai-thumb-btn:hover, .ai-thumb-btn:focus-visible {
  border-color: #6fe3ff; box-shadow: 0 0 6px rgba(111, 227, 255, .65); outline: none;
}
.ai-thumb { width: 60px; height: 44px; object-fit: cover; display: block; }

/* AI 告警证据面板：宽 960，左大图 + 右元数据 */
.ev-mask { position: fixed; inset: 0; z-index: 260; display: grid; place-items: center;
  background: rgba(2, 10, 22, .85); }
.ev-dlg { width: min(960px, 94vw); max-height: 92vh; overflow: auto; padding: 12px 14px 14px;
  background: linear-gradient(180deg, rgba(6, 46, 92, .98), rgba(4, 24, 48, .99));
  border: 1px solid rgba(111, 227, 255, .55); }
.ev-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.ev-body { display: grid; grid-template-columns: minmax(0, 1fr) 224px; gap: 14px; align-items: start; }
.ev-frame { position: relative; line-height: 0; border: 1px solid rgba(111, 227, 255, .35); }
.ev-frame img { width: 100%; height: auto; display: block; }
.ev-box { position: absolute; border: 2px solid #ffd23f; box-shadow: 0 0 0 1px rgba(0, 0, 0, .45) inset; }
.ev-box em { position: absolute; left: -2px; top: -19px; padding: 0 5px; font-style: normal;
  font-size: 11px; line-height: 19px; white-space: nowrap; font-weight: 600; }
.ev-meta { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px;
  background: rgba(0, 20, 40, .55); border: 1px solid rgba(111, 227, 255, .25); }
.ev-row { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; }
.ev-row span { color: #9fd2ff; }
.ev-row b { color: #e8f6ff; font-weight: 500; text-align: right; word-break: break-all; }
.ev-actions { display: flex; align-items: center; gap: 8px; margin-top: 12px; }

.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel:first-of-type { flex: 1; min-height: 0; overflow: auto; }
.small { font-size: 12px; line-height: 1.6; }
.num { font-variant-numeric: tabular-nums; }


.p-badge { background: rgba(255, 168, 46, .18); color: #ffc355; margin-right: 4px; }

.tag.shelved { background: rgba(255, 208, 64, .18); color: #ffd040; margin-right: 4px; }
.mask { position: fixed; inset: 0; z-index: 200; background: rgba(2, 12, 26, .7); display: grid; place-items: center; }
.shelve-dlg { width: 460px; padding: 14px 16px; background: linear-gradient(180deg, rgba(6,46,92,.98), rgba(4,26,54,.99));
  border: 1px solid rgba(111,227,255,.55); border-radius: 4px; }
.shelve-dlg h3 { margin: 0 0 6px; font-size: 14px; color: #ffd040; }
.shelve-dlg .fld { display: flex; flex-direction: column; gap: 4px; margin: 10px 0; font-size: 12px; color: #9fd2ff; }
.shelve-dlg .acts { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
</style>
