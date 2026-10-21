<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type TaskItem } from '@/api'

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

function reset() {
  keyword.value = ''
  stateFilter.value = ''
  loopFilter.value = ''
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
        <select class="select" v-model="stateFilter">
          <option value="">全部</option>
          <option v-for="(label, key) in stateText" :key="key" :value="key">{{ label }}</option>
        </select>
        <label>循环</label>
        <select class="select" v-model="loopFilter">
          <option value="">全部</option>
          <option value="true">是</option>
          <option value="false">否</option>
        </select>
        <button class="btn btn-sm" :disabled="loading" @click="reload">查询</button>
        <button class="btn btn-sm" @click="reset">重置</button>
        <span class="grow" />
        <button class="btn btn-sm" disabled>新建任务</button>
        <button class="btn btn-sm" disabled>批量删除</button>
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
          <tr v-for="(t, i) in filtered" :key="t.id">
            <td>{{ i + 1 }}</td>
            <td>{{ t.name }}</td>
            <td><span class="tag" :class="stateTone[t.state] ?? ''">{{ stateText[t.state] ?? t.state }}</span></td>
            <td class="num">{{ Array.isArray(t.sub_tasks) ? t.sub_tasks.length : 0 }}</td>
            <td class="dim">未标定（原值 {{ t.progress }}）</td>
            <td>{{ t.loop_flag ? '是' : '否' }}</td>
            <td class="num dim">{{ t.id.slice(0, 8) }}…</td>
            <td>
              <div class="row-actions">
                <button class="link-btn" disabled>下发</button>
                <button class="link-btn" disabled>暂停</button>
                <button class="link-btn" disabled>取消</button>
              </div>
            </td>
          </tr>
          <tr v-if="!filtered.length">
            <td colspan="8" class="dim">没有匹配的任务</td>
          </tr>
        </tbody>
      </table>

      <div class="pager">
        <span>共 {{ filtered.length }} 条</span>
        <span class="spacer" />
        <button class="on">1</button>
        <button disabled>下一页</button>
      </div>

      <p v-if="error" class="danger small">{{ error }}</p>
    </section>

    <section class="panel">
      <div class="panel-title"><span>下发与执行</span></div>
      <div class="toolbar" style="margin-bottom: 8px">
        <button class="btn btn-sm" disabled>下发</button>
        <button class="btn btn-sm" disabled>暂停</button>
        <button class="btn btn-sm" disabled>继续</button>
        <button class="btn btn-sm" disabled>取消当前任务</button>
        <span class="grow" />
        <span class="tag warn">写操作未开放</span>
      </div>
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
</style>
