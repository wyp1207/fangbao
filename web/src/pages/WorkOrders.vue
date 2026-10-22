<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

interface Order {
  id: number
  code: string | null
  title: string
  source: string
  level: string
  status: string
  status_label: string
  assignee_id: number | null
  due_at: string | null
  description: string | null
  resolution: string | null
  escalated_at: string | null
  created_at: string | null
  closed_at: string | null
  mobile_url?: string | null
}

const auth = useAuthStore()
const rows = ref<Order[]>([])
const total = ref(0)
const status = ref('')
const loading = ref(false)
const acting = ref<Order | null>(null)
const resolution = ref('')
const users = ref<{ id: number; username: string }[]>([])

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'open', label: '待派单' },
  { value: 'assigned', label: '已派单' },
  { value: 'processing', label: '处置中' },
  { value: 'review', label: '待复核' },
  { value: 'closed', label: '已销号' },
]
const userOptions = computed(() => users.value.map((u) => ({ value: String(u.id), label: u.username })))

const LEVEL: Record<string, string> = { critical: '紧急', warn: '一般', info: '提示' }
const LEVEL_TONE: Record<string, string> = { critical: 'danger', warn: 'warn', info: '' }

async function load() {
  loading.value = true
  try {
    const res = await api.workOrders({ status: status.value })
    rows.value = res.items as unknown as Order[]
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function assign(o: Order, userId: string) {
  try {
    await api.assignWorkOrder(o.id, { assignee_id: Number(userId), due_hours: 24 })
    toast('已派单', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '派单失败', 'danger')
  }
}

async function move(o: Order, target: string) {
  try {
    await api.transitionWorkOrder(o.id, { status: target, resolution: resolution.value || null })
    toast(`已${target === 'closed' ? '销号' : '更新'}`, 'ok')
    acting.value = null
    resolution.value = ''
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '操作失败', 'danger')
  }
}

async function copyLink(o: Order) {
  const url = new URL(o.mobile_url!, window.location.origin).toString()
  try {
    await navigator.clipboard.writeText(url)
    toast('手机处理链接已复制：' + url, 'ok', 5000)
  } catch {
    window.prompt('复制这个链接给现场人员', url)
  }
}

async function escalate(o: Order) {
  try {
    await api.escalateWorkOrder(o.id)
    toast('已升级并通知值班长', 'warn')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '升级失败', 'danger')
  }
}

function overdue(o: Order): boolean {
  return !!o.due_at && o.status !== 'closed' && Date.parse(o.due_at) < Date.now()
}

onMounted(async () => {
  await load()
  try {
    users.value = (await api.users()) as unknown as { id: number; username: string }[]
  } catch { /* 非管理员看不到用户列表，不影响工单 */ }
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>工单</span>
        <span class="muted small">告警或人工缺陷转单 → 派单到人 → 处置回填 → 复核销号；不能跳步</span>
        <span class="grow" />
        <span class="muted small">共 {{ total }} 条</span>
      </div>

      <div class="toolbar">
        <label>状态</label>
        <DarkSelect v-model="status" :options="statusOptions" width="120px" @update:model-value="load" />
        <button class="btn btn-sm ok" :disabled="loading" @click="load">刷新</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 150px">编号</th>
            <th>标题</th>
            <th style="width: 90px">等级</th>
            <th style="width: 100px">状态</th>
            <th style="width: 110px">责任人</th>
            <th style="width: 150px">期限</th>
            <th style="width: 210px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in rows" :key="o.id">
            <td class="num dim">{{ o.code || '#' + o.id }}</td>
            <td>
              {{ o.title }}
              <span v-if="overdue(o)" class="tag danger" title="超过期限">超期</span>
              <span v-if="o.escalated_at" class="tag warn" title="已升级">已升级</span>
            </td>
            <td><span class="tag" :class="LEVEL_TONE[o.level]">{{ LEVEL[o.level] ?? o.level }}</span></td>
            <td><span class="tag" :class="o.status === 'closed' ? 'ok' : o.status === 'review' ? '' : 'warn'">{{ o.status_label }}</span></td>
            <td class="dim">
              {{ o.assignee_id ? '#' + o.assignee_id : '未派' }}
              <button v-if="o.mobile_url" class="link" title="复制手机处理链接"
                      @click="copyLink(o)">📱</button>
            </td>
            <td class="num dim">{{ (o.due_at ?? '—').replace('T', ' ') }}</td>
            <td>
              <div class="row-actions">
                <DarkSelect
                  v-if="o.status === 'open' && auth.canWrite"
                  :model-value="''" :options="userOptions" width="96px" placeholder="派给"
                  @update:model-value="assign(o, $event)"
                />
                <button v-if="o.status === 'assigned'" class="btn btn-xs primary" :disabled="!auth.canWrite"
                        @click="move(o, 'processing')">开始处置</button>
                <button v-if="o.status === 'processing'" class="btn btn-xs primary" :disabled="!auth.canWrite"
                        @click="acting = o; resolution = o.resolution ?? ''">提交复核</button>
                <button v-if="o.status === 'review'" class="btn btn-xs warn" :disabled="!auth.canWrite"
                        @click="acting = o; resolution = o.resolution ?? ''">复核销号</button>
                <button v-if="o.status !== 'closed' && !o.escalated_at" class="act" title="超时升级"
                        :disabled="!auth.canWrite" @click="escalate(o)">↑</button>
              </div>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="7" class="dim">{{ loading ? '读取中…' : '还没有工单。告警页可以把告警转成工单。' }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <div v-if="acting" class="modal-mask" @click.self="acting = null">
      <div class="modal">
        <div class="panel-title">
          <span>{{ acting.status === 'review' ? '复核销号' : '提交复核' }} · {{ acting.code || '#' + acting.id }}</span>
        </div>
        <p class="dim small">{{ acting.title }}</p>
        <label class="fld">
          <span>处置结果{{ acting.status === 'review' ? '（销号必填）' : '' }}</span>
          <textarea v-model="resolution" class="input" rows="4"
                    placeholder="做了什么处理、换了什么件、还需要什么跟进" />
        </label>
        <div class="modal-actions">
          <button class="btn" @click="acting = null">取消</button>
          <button v-if="acting.status === 'processing'" class="btn primary" @click="move(acting, 'review')">提交复核</button>
          <button v-else class="btn warn" @click="move(acting, 'closed')">确认销号</button>
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
.link { background: none; border: none; cursor: pointer; font-size: 12px; padding: 0 2px; }
.modal-mask { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 14, 30, 0.66); }
.modal { width: 520px; padding: 14px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6); }
.fld { display: block; margin-bottom: 10px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; box-sizing: border-box; resize: vertical; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
