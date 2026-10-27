<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

interface Plan {
  id: number
  name: string
  station: string
  shift: string
  enabled: boolean
  point_count: number
  items: { name: string; code?: string; checks?: string[] }[]
}
interface Task {
  id: number
  title: string
  status: string
  status_label: string
  due_at: string | null
  item_count?: number
  done_count?: number
  progress?: { total: number; done: number; abnormal: number }
  assignee_id: number | null
}

const auth = useAuthStore()
const router = useRouter()
const plans = ref<Plan[]>([])
const tasks = ref<Task[]>([])
const status = ref('')
const loading = ref(false)
const detail = ref<(Task & { items: any[] }) | null>(null)

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待执行' },
  { value: 'doing', label: '执行中' },
  { value: 'done', label: '已完成' },
]

const pendingCount = computed(() => tasks.value.filter((t) => t.status !== 'done').length)

async function load() {
  loading.value = true
  try {
    plans.value = (await api.inspectionPlans()) as unknown as Plan[]
    const res = await api.inspectionTasks({ status: status.value })
    tasks.value = res.items as unknown as Task[]
  } finally {
    loading.value = false
  }
}

// 计划编辑/删除：建错了不用重建
const planEdit = ref<Plan | null>(null)
const planForm = ref({ name: '', station: '', shift: '', enabled: '1' as string, note: '', itemsText: '' })

function openPlanEdit(p: Plan) {
  planEdit.value = p
  planForm.value = {
    name: p.name, station: p.station, shift: p.shift, enabled: p.enabled ? '1' : '0',
    note: (p as unknown as { note?: string }).note ?? '',
    itemsText: (p.items ?? []).map((i) => i.name).join('\n'),
  }
}

async function savePlan() {
  const p = planEdit.value
  if (!p) return
  if (!planForm.value.name.trim()) { toast('计划名称不能为空', 'warn'); return }
  const items = planForm.value.itemsText.split('\n').map((x) => x.trim()).filter(Boolean)
  try {
    await api.updateInspectionPlan(p.id, {
      name: planForm.value.name.trim(), station: planForm.value.station.trim() || '默认场站',
      shift: planForm.value.shift.trim() || '白班', enabled: planForm.value.enabled === '1',
      note: planForm.value.note,
      items: items.map((name) => ({ name, code: '', checks: [] })),
    })
    toast('计划已保存', 'ok')
    planEdit.value = null
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '保存失败', 'danger')
  }
}

async function removePlan(p: Plan) {
  if (!window.confirm(`删除计划「${p.name}」？已生成的任务不受影响。`)) return
  try {
    await api.deleteInspectionPlan(p.id)
    toast('已删除', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '删除失败', 'danger')
  }
}

async function generate(p: Plan) {
  if (!p.enabled) return toast('计划已停用', 'warn')
  try {
    const t = await api.generateInspectionTask({ plan_id: p.id })
    toast(`已生成任务「${t.title}」`, 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '生成失败', 'danger')
  }
}

async function openDetail(t: Task) {
  detail.value = (await api.inspectionTask(t.id)) as unknown as typeof detail.value
}

async function finish(t: Task) {
  try {
    await api.finishInspectionTask(t.id)
    toast('任务已完成', 'ok')
    detail.value = null
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '完成失败', 'danger')
  }
}

function pct(t: Task): number {
  const total = t.item_count ?? t.progress?.total ?? 0
  const done = t.done_count ?? t.progress?.done ?? 0
  return total ? Math.round((done / total) * 100) : 0
}

onMounted(load)
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>人工巡检</span>
        <span class="muted small">计划派发 → 扫码打点 → 现场记录 → 缺陷上报；扫码编号对不上会记录在案</span>
        <span class="grow" />
        <span class="tag" :class="pendingCount ? 'warn' : 'ok'">{{ pendingCount }} 个待执行</span>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 180px">计划</th>
            <th style="width: 100px">班次</th>
            <th style="width: 90px">点位数</th>
            <th>点位/检查项</th>
            <th style="width: 90px">状态</th>
            <th style="width: 230px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in plans" :key="p.id">
            <td>{{ p.id }}</td>
            <td>{{ p.name }}</td>
            <td>{{ p.shift }}</td>
            <td class="num">{{ p.point_count }}</td>
            <td class="dim small">
              {{ p.items.slice(0, 3).map((i) => i.name).join('、') || '—' }}{{ p.point_count > 3 ? ' …' : '' }}
            </td>
            <td><span class="tag" :class="p.enabled ? 'ok' : 'warn'">{{ p.enabled ? '启用' : '停用' }}</span></td>
            <td>
              <button class="btn btn-xs primary" :disabled="!auth.canWrite || !p.enabled" @click="generate(p)">
                生成任务
              </button>
              <button class="btn btn-xs" :disabled="!auth.canWrite" @click="openPlanEdit(p)">编辑</button>
              <button class="btn btn-xs danger" :disabled="!auth.canWrite" @click="removePlan(p)">删除</button>
            </td>
          </tr>
          <tr v-if="!plans.length">
            <td colspan="7" class="dim">还没有人工巡检计划。真机到场前，人工巡检可以先跑起来。</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <div class="panel-title">
        <span>执行任务</span>
        <span class="grow" />
        <DarkSelect v-model="status" :options="statusOptions" width="110px" @update:model-value="load" />
        <button class="btn btn-sm ok" :disabled="loading" @click="load">刷新</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 200px">任务</th>
            <th style="width: 100px">状态</th>
            <th style="width: 140px">进度</th>
            <th style="width: 160px">截止</th>
            <th style="width: 180px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.id">
            <td>{{ t.id }}</td>
            <td>{{ t.title }}</td>
            <td><span class="tag" :class="t.status === 'done' ? 'ok' : t.status === 'doing' ? '' : 'warn'">{{ t.status_label }}</span></td>
            <td>
              <div class="bar"><i :style="{ width: pct(t) + '%' }" /></div>
              <span class="dim small">{{ t.done_count ?? 0 }}/{{ t.item_count ?? 0 }}</span>
            </td>
            <td class="num dim">{{ (t.due_at ?? '—').replace('T', ' ') }}</td>
            <td>
              <div class="row-actions">
                <button class="btn btn-xs" @click="openDetail(t)">详情</button>
                <button class="btn btn-xs" @click="router.push(`/m/task/${t.id}`)">手机打卡</button>
                <button v-if="t.status !== 'done'" class="btn btn-xs primary"
                        :disabled="!auth.canWrite" @click="finish(t)">完成</button>
              </div>
            </td>
          </tr>
          <tr v-if="!tasks.length">
            <td colspan="6" class="dim">{{ loading ? '读取中…' : '还没有任务。上面选一个计划点「生成任务」。' }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal wide">
        <div class="panel-title"><span>{{ detail.title }}</span>
          <span class="tag" :class="detail.status === 'done' ? 'ok' : 'warn'">{{ detail.status_label }}</span>
        </div>
        <p class="muted small">
          进度 {{ detail.progress?.done ?? 0 }}/{{ detail.progress?.total ?? 0 }}
          <template v-if="detail.progress?.abnormal"> · 异常 {{ detail.progress.abnormal }}
    <div v-if="planEdit" class="mask" @click.self="planEdit = null">
      <div class="plan-dlg">
        <h3>编辑计划 #{{ planEdit.id }}</h3>
        <div class="grid2">
          <label class="fld"><span>名称</span><input class="input" v-model="planForm.name" /></label>
          <label class="fld"><span>场站</span><input class="input" v-model="planForm.station" /></label>
          <label class="fld"><span>班次</span><input class="input" v-model="planForm.shift" /></label>
          <label class="fld"><span>启用</span>
            <DarkSelect v-model="planForm.enabled" :options="[{ value: '1', label: '启用' }, { value: '0', label: '停用' }]" width="120px" />
          </label>
        </div>
        <label class="fld"><span>点位（每行一个）</span>
          <textarea class="input" rows="6" v-model="planForm.itemsText" /></label>
        <label class="fld"><span>备注</span><input class="input" v-model="planForm.note" /></label>
        <p class="dim small">改点位会覆盖原配置；已生成的任务不受影响。</p>
        <div class="acts">
          <button class="btn btn-sm" @click="planEdit = null">取消</button>
          <button class="btn btn-sm primary" @click="savePlan">保存</button>
        </div>
      </div>
    </div>
</template>
        </p>
        <table class="grid">
          <thead><tr><th style="width: 50px">序</th><th style="width: 160px">点位</th><th style="width: 100px">扫码</th>
            <th style="width: 90px">结论</th><th>备注</th></tr></thead>
          <tbody>
            <tr v-for="i in detail.items" :key="i.id">
              <td>{{ i.seq }}</td>
              <td>{{ i.point_name }}</td>
              <td class="dim small">{{ i.scanned_at ? '已扫' : (i.code ? '未扫' : '—') }}</td>
              <td><span class="tag" :class="i.result === 'ok' ? 'ok' : i.result === 'abnormal' ? 'danger' : 'warn'">
                {{ i.result === 'ok' ? '正常' : i.result === 'abnormal' ? '异常' : i.result === 'skipped' ? '跳过' : '未做' }}
              </span></td>
              <td class="dim small">{{ i.note || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions"><button class="btn" @click="detail = null">关闭</button></div>
      </div>
    </div>
  </div>

    <div v-if="planEdit" class="mask" @click.self="planEdit = null">
      <div class="plan-dlg">
        <h3>编辑计划 #{{ planEdit.id }}</h3>
        <div class="grid2">
          <label class="fld"><span>名称</span><input class="input" v-model="planForm.name" /></label>
          <label class="fld"><span>场站</span><input class="input" v-model="planForm.station" /></label>
          <label class="fld"><span>班次</span><input class="input" v-model="planForm.shift" /></label>
          <label class="fld"><span>启用</span>
            <DarkSelect v-model="planForm.enabled" :options="[{ value: '1', label: '启用' }, { value: '0', label: '停用' }]" width="120px" />
          </label>
        </div>
        <label class="fld"><span>点位（每行一个）</span>
          <textarea class="input" rows="6" v-model="planForm.itemsText" /></label>
        <label class="fld"><span>备注</span><input class="input" v-model="planForm.note" /></label>
        <p class="dim small">改点位会覆盖原配置；已生成的任务不受影响。</p>
        <div class="acts">
          <button class="btn btn-sm" @click="planEdit = null">取消</button>
          <button class="btn btn-sm primary" @click="savePlan">保存</button>
        </div>
      </div>
    </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.small { font-size: 12px; }
.num { font-variant-numeric: tabular-nums; }
.btn-xs { padding: 2px 8px; font-size: 12px; }
.bar { height: 5px; background: rgba(0, 40, 80, 0.6); border-radius: 3px; overflow: hidden; margin-bottom: 2px; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, #29d4ff, #6ff0c0); }
.modal-mask { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 14, 30, 0.66); }
.modal { width: 720px; max-height: 90vh; overflow: auto; padding: 14px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6); }
.modal-actions { display: flex; justify-content: flex-end; margin-top: 8px; }

.mask { position: fixed; inset: 0; z-index: 200; background: rgba(2,12,26,.7); display: grid; place-items: center; }
.plan-dlg { width: 560px; padding: 14px 16px; background: linear-gradient(180deg, rgba(6,46,92,.98), rgba(4,26,54,.99));
  border: 1px solid rgba(111,227,255,.55); border-radius: 4px; }
.plan-dlg h3 { margin: 0 0 8px; font-size: 14px; color: #ffd040; }
.plan-dlg .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; }
.plan-dlg .fld { display: flex; flex-direction: column; gap: 4px; margin: 8px 0; font-size: 12px; color: #9fd2ff; }
.plan-dlg .acts { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
</style>
