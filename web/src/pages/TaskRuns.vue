<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

// 单页行数：不一次拉全量（执行记录只会越攒越多），翻页用 offset。
// 页头必须显示「共 N 条，当前第 x–y 条」，否则 total 与可见行数对不上。
const PAGE_SIZE = 50

interface RunRow {
  id: number
  name: string
  status: string
  status_label: string
  robot_id: number | null
  template_id: number | null
  started_at: string | null
  finished_at: string | null
  created_at: string | null
  external_id: string | null
  note: string | null
  paused?: boolean
  dispatch_error?: string | null
  step_count?: number
}
interface Step {
  id: number
  seq: number
  point_name: string | null
  action: string
  status: string
  result: Record<string, unknown> | null
  error: string | null
}

const auth = useAuthStore()
const rows = ref<RunRow[]>([])
const total = ref(0)
const status = ref('')
const loading = ref(false)
const error = ref('')
const page = ref(1)                       // 1 起：第几页
const detail = ref<(RunRow & { steps: Step[]; progress: { total: number; ok: number; failed: number } }) | null>(null)
const templates = ref<{ id: number; name: string }[]>([])
const creating = ref(false)
const form = ref({ templateId: '', name: '', note: '' })
// 没有可续跑点位的任务：查过一次就置灰，别让人反复点
const noResume = ref<Set<number>>(new Set())
const resuming = ref(0)                  // 正在读详情的 run id，防连点

const pages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const pageFrom = computed(() => (total.value ? (page.value - 1) * PAGE_SIZE + 1 : 0))
const pageTo = computed(() => Math.min(page.value * PAGE_SIZE, total.value))

const STATUS_TEXT: Record<string, string> = {
  planned: '计划中', running: '执行中', done: '已完成', failed: '失败', cancelled: '已取消',
}
const STATUS_TONE: Record<string, string> = {
  planned: 'warn', running: '', done: 'ok', failed: 'danger', cancelled: 'warn',
}
const statusOptions = [
  { value: '', label: '全部' },
  { value: 'planned', label: '计划中' },
  { value: 'running', label: '执行中' },
  { value: 'done', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]
const templateOptions = computed(() => templates.value.map((t) => ({ value: String(t.id), label: t.name })))

function exportReport(id: number) {
  window.open(api.taskReportUrl(id), '_blank')
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.taskRuns({ status: status.value, limit: PAGE_SIZE, offset: (page.value - 1) * PAGE_SIZE })
    rows.value = res.items as unknown as RunRow[]
    total.value = res.total
    // 停在末页时把最后一页的任务取消/删掉了：页号会越界，回落到最后一页重拉，别显示空表
    if (!rows.value.length && page.value > 1 && total.value > 0) {
      page.value = Math.min(page.value, Math.ceil(total.value / PAGE_SIZE))
      loading.value = false
      return load()
    }
  } catch (e) {
    // 不能把请求失败伪装成「还没有执行记录」
    error.value = e instanceof ApiError ? e.message : (e instanceof Error ? e.message : '加载失败')
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function onStatusChange() {
  page.value = 1
  void load()
}

function goPage(p: number) {
  const target = Math.min(Math.max(1, p), pages.value)
  if (target === page.value) return
  page.value = target
  void load()
}

async function openDetail(r: RunRow) {
  try {
    detail.value = (await api.taskRun(r.id)) as unknown as typeof detail.value
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '详情读取失败', 'danger')
  }
}

async function openCreate() {
  if (!templates.value.length) {
    toast('先到「任务模板」建一个模板', 'warn')
    return
  }
  form.value = { templateId: String(templates.value[0].id), name: '', note: '' }
  creating.value = true
}

async function submitCreate() {
  try {
    await api.createTaskRun({
      template_id: form.value.templateId ? Number(form.value.templateId) : null,
      name: form.value.name || null,
      note: form.value.note || null,
    })
    toast('已生成计划（未下发，等真机联调）', 'ok', 4000)
    creating.value = false
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '创建失败', 'danger')
  }
}

async function dispatch(r: RunRow) {
  try {
    await api.dispatchTaskRun(r.id)
    toast('已下发，等待机器人接单', 'ok')
    await load()
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : '下发失败'
    toast(msg, e instanceof ApiError && e.code === 'WRITE_LOCKED' ? 'warn' : 'danger', 6000)
  }
}

async function cruise(r: RunRow) {
  try {
    const res = await api.startCruise(r.id)
    toast(`巡航已启动（${res.steps} 个点位），到点自动进行下一个`, 'ok', 5000)
    await load()
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : '启动失败'
    toast(msg, e instanceof ApiError && e.code === 'WRITE_LOCKED' ? 'warn' : 'danger', 6000)
  }
}

async function pause(r: RunRow) {
  try {
    await api.pauseTaskRun(r.id)
    toast('已暂停', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '暂停失败', 'danger')
  }
}

async function resume(r: RunRow) {
  try {
    await api.resumeTaskRun(r.id)
    toast('已继续', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '继续失败', 'danger')
  }
}

async function resumeFromFailed(r: RunRow) {
  // 「接着跑」：从**最后完成点的下一个点**继续，不重复已完成的点；
  // 后端的 from_seq 是**闭区间**起点（server/app/services/cruise.py：`TaskRunStep.seq >= from_seq`），
  // 所以传 lastOk + 1。若产品要求"重跑最后一个完成点"，把 +1 去掉即可。
  resuming.value = r.id
  try {
    const d = (await api.taskRun(r.id)) as unknown as { steps?: Step[] }
    const steps = d.steps ?? []
    const ok = steps.filter((s) => s.status === 'ok').map((s) => s.seq)
    const lastOk = ok.length ? Math.max(...ok) : 0
    // 没有已完成的点 = 没断点可续；已完成点之后没有剩余点 = 任务其实已经跑完
    if (!lastOk || !steps.some((s) => s.seq > lastOk)) {
      noResume.value = new Set(noResume.value).add(r.id)
      toast('没有可续跑的点位', 'warn')
      return
    }
    const fromSeq = lastOk + 1
    const res = await api.startCruise(r.id, fromSeq)
    toast(`从第 ${fromSeq} 点接着跑（前 ${lastOk} 点已完成，共 ${res.steps} 个点位）`, 'ok', 5000)
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '启动失败', 'danger')
  } finally {
    resuming.value = 0
  }
}

async function retry(s: Step) {
  try {
    if (!detail.value) return
    await api.retryStep(detail.value.id, s.seq)
    toast(`第 ${s.seq} 点动作重试成功`, 'ok')
    await openDetail(detail.value!)
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '重试失败', 'danger')
  }
}

async function cancel(r: RunRow) {
  const reason = window.prompt(`取消「${r.name}」的原因（会写进审计，必填）`, '')
  if (reason === null) return
  if (!reason.trim()) return toast('必须填取消原因', 'warn')
  try {
    await api.cancelTaskRunWithReason(r.id, reason.trim())
    toast('已取消', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '取消失败', 'danger')
  }
}

function dur(a: string | null, b: string | null): string {
  if (!a || !b) return '—'
  const s = (Date.parse(b) - Date.parse(a)) / 1000
  if (s < 60) return `${Math.round(s)} 秒`
  if (s < 3600) return `${Math.round(s / 60)} 分钟`
  return `${(s / 3600).toFixed(1)} 小时`
}

onMounted(async () => {
  try {
    templates.value = (await api.taskTemplates()) as unknown as { id: number; name: string }[]
  } catch { /* 无模板也能看列表 */ }
  await load()
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>任务执行</span>
        <span class="muted small">平台只生成「计划」；执行结果由机器人回传（真机接了才有数据）</span>
        <span class="grow" />
        <button class="btn btn-sm primary" :disabled="!auth.canWrite" @click="openCreate">从模板生成计划</button>
      </div>

      <div class="toolbar">
        <label>状态</label>
        <DarkSelect v-model="status" :options="statusOptions" width="120px" @update:model-value="onStatusChange" />
        <button class="btn btn-sm ok" :disabled="loading" @click="load">刷新</button>
        <span class="grow" />
        <span class="muted small">
          共 {{ total }} 条<template v-if="total">，当前第 {{ pageFrom }}–{{ pageTo }} 条</template>
        </span>
        <button class="btn btn-sm" :disabled="loading || page <= 1" @click="goPage(page - 1)">上一页</button>
        <span class="muted small">{{ page }}/{{ pages }}</span>
        <button class="btn btn-sm" :disabled="loading || page >= pages" @click="goPage(page + 1)">下一页</button>
      </div>

      <div v-if="error" class="errbar">
        <span>加载失败：{{ error }}</span>
        <button class="btn btn-sm" :disabled="loading" @click="load">重试</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 180px">名称</th>
            <th style="width: 110px">状态</th>
            <th style="width: 90px">点数</th>
            <th style="width: 160px">开始</th>
            <th style="width: 110px">耗时</th>
            <th style="width: 130px">来源</th>
            <th style="width: 150px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.name }}</td>
            <td><span class="tag" :class="STATUS_TONE[r.status]">{{ STATUS_TEXT[r.status] ?? r.status }}</span></td>
            <td class="num">{{ r.step_count ?? 0 }}</td>
            <td class="num dim">{{ (r.started_at ?? r.created_at ?? '').replace('T', ' ').slice(0, 19) }}</td>
            <td class="num dim">{{ dur(r.started_at, r.finished_at) }}</td>
            <td class="dim small">
              {{ r.external_id ? '机器人回传' : '平台计划' }}
              <span v-if="r.dispatch_error" class="tag danger" :title="r.dispatch_error">
                {{ r.status === 'failed' ? '有失败点位' : '下发失败' }}
              </span>
            </td>
            <td>
              <div class="row-actions">
                <button class="btn btn-xs" @click="openDetail(r)">详情</button>
              <button class="btn btn-xs" title="导出这趟巡检的 xlsx 报告"
                      @click="exportReport(r.id)">报告</button>
                <button v-if="r.status === 'planned'" class="btn btn-xs"
                        :disabled="!auth.canWrite" @click="dispatch(r)">单点下发</button>
                <button v-if="['planned','failed','cancelled'].includes(r.status)" class="btn btn-xs primary"
                        title="重新巡航：从第 1 点开始重跑全部点位（不跳过已完成的点）"
                        :disabled="!auth.canWrite" @click="cruise(r)">巡航</button>
                <button v-if="['failed','cancelled'].includes(r.status)" class="btn btn-xs"
                        :title="noResume.has(r.id) ? '没有可续跑的点位' : '从最后完成点的下一个点继续，不重复已完成的点'"
                        :disabled="!auth.canWrite || resuming === r.id || noResume.has(r.id)"
                        @click="resumeFromFailed(r)">接着跑</button>
                <template v-if="r.status === 'running'">
                  <button v-if="!r.paused" class="btn btn-xs" :disabled="!auth.canWrite" @click="pause(r)">暂停</button>
                  <button v-else class="btn btn-xs ok" :disabled="!auth.canWrite" @click="resume(r)">继续</button>
                </template>
                <button v-if="['planned','running'].includes(r.status)" class="act danger"
                        title="取消" :disabled="!auth.canWrite" @click="cancel(r)">✕</button>
              </div>
            </td>
          </tr>
          <tr v-if="!rows.length && !error">
            <td colspan="8" class="dim">
              {{ loading ? '读取中…' : '还没有执行记录。真机接入后，机器人回传的任务会自动出现在这里。' }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 详情 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal wide">
        <div class="panel-title">
          <span>{{ detail.name }}</span>
          <span class="tag" :class="STATUS_TONE[detail.status]">{{ STATUS_TEXT[detail.status] }}</span>
        </div>
        <p class="muted small">
          开始 {{ (detail.started_at ?? '—').replace('T',' ') }} ·
          结束 {{ (detail.finished_at ?? '—').replace('T',' ') }} ·
          点位 {{ detail.progress?.ok ?? 0 }}/{{ detail.progress?.total ?? 0 }} 成功
          <template v-if="detail.progress?.failed"> · {{ detail.progress.failed }} 失败</template>
        </p>

        <table class="grid">
          <thead>
            <tr><th style="width: 60px">序</th><th style="width: 160px">点位</th><th style="width: 90px">动作</th>
                <th style="width: 90px">结果</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="s in detail.steps" :key="s.id">
              <td>{{ s.seq }}</td>
              <td>{{ s.point_name || '—' }}</td>
              <td class="dim">{{ s.action }}</td>
              <td>
                <span class="tag" :class="s.status === 'ok' ? 'ok' : s.status === 'failed' ? 'danger' : 'warn'">
                  {{ s.status === 'ok' ? '成功' : s.status === 'failed' ? '失败' : s.status }}
                </span>
              </td>
              <td class="dim small">
                <button v-if="s.status === 'failed'" class="btn btn-xs" :disabled="!auth.canWrite"
                        @click="retry(s)">重试动作</button>
                <span v-if="s.error">{{ s.error }}</span>
                <span v-else-if="s.result">{{ JSON.stringify(s.result).slice(0, 80) }}</span>
                <span v-else>—</span>
              </td>
            </tr>
            <tr v-if="!detail.steps?.length"><td colspan="5" class="dim">这条记录还没有点位结果</td></tr>
          </tbody>
        </table>

        <div class="modal-actions">
          <button class="btn" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 生成计划 -->
    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal">
        <div class="panel-title"><span>从模板生成计划</span><span class="req-legend">带 * 为必填</span></div>
        <label class="fld">
          <span>模板<i class="req">*</i></span>
          <DarkSelect v-model="form.templateId" :options="templateOptions" width="100%" />
        </label>
        <label class="fld"><span>名称（留空用模板名）</span><input class="input" v-model="form.name" /></label>
        <label class="fld"><span>备注</span><input class="input" v-model="form.note" placeholder="如：明早班执行" /></label>
        <p class="muted small">
          生成的是<b>计划</b>，不会下发到机器人——写操作要等真机联调 + 现场授权。
        </p>
        <div class="modal-actions">
          <button class="btn" @click="creating = false">取消</button>
          <button class="btn primary" @click="submitCreate">生成</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.small { font-size: 12px; }
.num { font-variant-numeric: tabular-nums; }
.btn-xs { padding: 2px 8px; font-size: 12px; }
.errbar {
  display: flex; align-items: center; gap: 10px; margin: 6px 0 8px;
  padding: 7px 10px; font-size: 12.5px; color: #ffb3b3;
  background: rgba(255, 90, 90, 0.12); border: 1px solid rgba(255, 90, 90, 0.5);
}
.modal-mask { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 14, 30, 0.66); }
.modal {
  width: 520px; max-height: 90vh; overflow: auto; padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
}
.modal.wide { width: 720px; }
.fld { display: block; margin-bottom: 11px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
</style>
