<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type TaskItem } from '@/api'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'
import WriteLockedDialog from '@/components/WriteLockedDialog.vue'

const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const error = ref('')

const keyword = ref('')
const stateFilter = ref('')
const loopFilter = ref('')

const stateText: Record<string, string> = {
  WAITTING: '等待执行',
  WORKING: '执行中',
  PAUSED: '已暂停',
  CANCELLED: '已取消',
  ERROR: '错误',
  COMPLETE: '已完成',
}

const stateOptions = [
  { value: '', label: '全部' },
  ...Object.entries(stateText).map(([value, label]) => ({ value, label })),
]
const loopOptions = [
  { value: '', label: '全部' },
  { value: 'true', label: '是' },
  { value: 'false', label: '否' },
]

const stateTone: Record<string, string> = {
  COMPLETE: 'ok',
  WORKING: 'ok',
  ERROR: 'danger',
  CANCELLED: 'danger',
  PAUSED: 'warn',
}

const filtered = computed(() =>
  tasks.value.filter((t) => {
    if (keyword.value && !t.name.includes(keyword.value)) return false
    if (stateFilter.value && t.state !== stateFilter.value) return false
    if (loopFilter.value && String(t.loop_flag) !== loopFilter.value) return false
    return true
  }),
)

const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))

function goto(p: number) {
  page.value = Math.min(Math.max(1, p), pageCount.value)
}

async function reload() {
  loading.value = true
  error.value = ''
  try {
    tasks.value = await api.tasks()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '任务读取失败'
  } finally {
    loading.value = false
  }
}

const detail = ref<TaskItem | null>(null)
const locked = ref('')
const page = ref(1)
const pageSize = 10

function tryWrite(action: string) {
  toast(`${action}未开放：需真机联调通过 + 现场授权签字`, 'warn', 3000)
}

function reset() {
  keyword.value = ''
  stateFilter.value = ''
  loopFilter.value = ''
  page.value = 1
}

onMounted(reload)
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>任务列表</span>
        <span class="muted">机器人是唯一真相源，平台库只做镜像</span>
      </div>

      <div class="toolbar">
        <label>任务名称</label>
        <input class="input" v-model="keyword" placeholder="输入任务名称搜索" />
        <label>状态</label>
        <DarkSelect v-model="stateFilter" :options="stateOptions" width="130px" />
        <label>循环</label>
        <DarkSelect v-model="loopFilter" :options="loopOptions" width="96px" />
        <button class="btn btn-sm ok" :disabled="loading" @click="reload">查询</button>
        <button class="btn btn-sm warn" @click="reset">重置</button>
        <span class="grow" />
        <button class="btn btn-sm" @click="locked = '新建任务'">新建任务</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">序号</th>
            <th>任务名称</th>
            <th style="width: 110px">状态</th>
            <th style="width: 90px">动作数</th>
            <th style="width: 150px">进度</th>
            <th style="width: 80px">循环</th>
            <th style="width: 110px">任务 ID</th>
            <th style="width: 140px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(t, i) in paged" :key="t.id">
            <td>{{ (page - 1) * pageSize + i + 1 }}</td>
            <td>{{ t.name }}</td>
            <td><span class="tag" :class="stateTone[t.state] ?? ''">{{ stateText[t.state] ?? t.state }}</span></td>
            <td class="num">{{ Array.isArray(t.sub_tasks) ? t.sub_tasks.length : 0 }}</td>
            <td class="dim">未标定（原值 {{ t.progress }}）</td>
            <td>{{ t.loop_flag ? '是' : '否' }}</td>
            <td class="num dim">{{ t.id.slice(0, 8) }}…</td>
            <td>
              <div class="row-actions">
                <button class="act" title="查看详情" @click="detail = t">☰</button>
                <button class="act" title="下发任务（未开放）" @click="locked = '下发任务'">▶</button>
                <button class="act danger" title="取消任务（未开放）" @click="locked = '取消任务'">■</button>
              </div>
            </td>
          </tr>
          <tr v-if="!filtered.length">
            <td colspan="8" class="dim">没有匹配的任务</td>
          </tr>
        </tbody>
      </table>

      <div class="pager">
        <span>共 {{ filtered.length }} 条 · 第 {{ page }}/{{ pageCount }} 页</span>
        <span class="spacer" />
        <button :disabled="page <= 1" @click="goto(page - 1)">上一页</button>
        <button
          v-for="n in pageCount" :key="n"
          :class="{ on: n === page }" @click="goto(n)"
        >{{ n }}</button>
        <button :disabled="page >= pageCount" @click="goto(page + 1)">下一页</button>
      </div>

      <p v-if="error" class="danger small">{{ error }}</p>
    </section>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <div class="panel-title"><span>任务详情</span></div>
        <table class="grid">
          <tbody>
            <tr><th style="width: 120px">任务名</th><td>{{ detail.name }}</td></tr>
            <tr><th>状态</th><td>{{ stateText[detail.state] ?? detail.state }}</td></tr>
            <tr><th>任务 ID</th><td class="num">{{ detail.id }}</td></tr>
            <tr><th>循环</th><td>{{ detail.loop_flag ? '是' : '否' }}</td></tr>
            <tr><th>进度</th><td class="dim">未标定（原值 {{ detail.progress }}）</td></tr>
          </tbody>
        </table>
        <div class="panel-title" style="margin-top: 12px"><span>动作序列</span></div>
        <pre class="json">{{ JSON.stringify(detail.sub_tasks, null, 2) }}</pre>
        <div class="modal-actions">
          <button class="btn btn-sm" @click="tryWrite('下发')">下发</button>
          <button class="btn btn-sm" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <section class="panel">
      <div class="panel-title"><span>下发与执行</span></div>
      <div class="toolbar" style="margin-bottom: 8px">
        <button class="btn btn-sm" @click="locked = '下发任务'">下发</button>
        <button class="btn btn-sm" @click="locked = '暂停任务'">暂停</button>
        <button class="btn btn-sm" @click="locked = '继续任务'">继续</button>
        <button class="btn btn-sm" @click="locked = '取消当前任务'">取消当前任务</button>
        <span class="grow" />
        <span class="tag warn">写操作未开放</span>
      </div>
      <WriteLockedDialog :open="!!locked" :action="locked" @close="locked = ''" />

      <p class="muted small">
        “取消任务”不是安全急停。平台没有急停下发接口，安全急停只能按车上的硬件按钮。
        按方案 §5.7，取消始终带 <code>jcrob_task_id</code>；“取消全部任务”不向前端暴露。
      </p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel:first-of-type { flex: 1; min-height: 0; overflow: auto; }
.small { font-size: 12px; line-height: 1.6; }
.modal-mask {
  position: fixed; inset: 0; z-index: 120;
  display: grid; place-items: center;
  background: rgba(2, 14, 30, 0.66);
}
.modal {
  width: 560px; max-height: 78vh; overflow: auto;
  padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.96), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
  box-shadow: 0 0 30px rgba(0, 60, 140, 0.7);
}
.json {
  margin: 0; padding: 10px;
  font-size: 12px; line-height: 1.6; color: #cfe8ff;
  background: rgba(0, 40, 84, 0.7);
  border: 1px solid rgba(111, 227, 255, 0.2);
  max-height: 220px; overflow: auto;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
</style>
