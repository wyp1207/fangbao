<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type TaskItem } from '@/api'

const tasks = ref<TaskItem[]>([])
const error = ref('')
const loading = ref(false)

const stateText: Record<string, string> = {
  WAITTING: '等待执行',
  WORKING: '执行中',
  PAUSED: '已暂停',
  CANCELLED: '已取消',
  ERROR: '错误',
  COMPLETE: '已完成',
  DRAFT: '草稿',
  UNKNOWN: '状态未知',
}

const rows = computed(() =>
  tasks.value.map((t) => ({
    ...t,
    stateLabel: stateText[t.state] ?? t.state,
    steps: Array.isArray(t.sub_tasks) ? t.sub_tasks.length : 0,
  })),
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

onMounted(reload)
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>任务列表（只读）</span>
        <button class="btn" :disabled="loading" @click="reload">刷新</button>
      </div>

      <p class="muted small">
        机器人是唯一真相源，平台库只做镜像。本期只读；下发/暂停/继续/停止要等真机联调与现场授权签字后开放。
      </p>

      <table class="grid">
        <thead>
          <tr>
            <th>任务名</th>
            <th>状态</th>
            <th>动作数</th>
            <th>进度</th>
            <th>循环</th>
            <th>ID</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in rows" :key="t.id">
            <td>{{ t.name }}</td>
            <td><span class="tag" :class="t.state === 'ERROR' ? 'danger' : t.state === 'WORKING' ? 'ok' : ''">{{ t.stateLabel }}</span></td>
            <td class="mono">{{ t.steps }}</td>
            <td class="muted">未标定（原值 {{ t.progress }}）</td>
            <td>{{ t.loop_flag ? '是' : '否' }}</td>
            <td class="mono muted">{{ t.id.slice(0, 8) }}…</td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="6" class="muted">暂无任务</td>
          </tr>
        </tbody>
      </table>

      <p v-if="error" class="danger small">{{ error }}</p>
    </section>

    <section class="panel">
      <div class="panel-title">下发与执行</div>
      <div class="actions">
        <button class="btn" disabled>新建任务</button>
        <button class="btn" disabled>下发</button>
        <button class="btn" disabled>暂停</button>
        <button class="btn" disabled>继续</button>
        <button class="btn" disabled>取消当前任务</button>
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
.actions { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.small { font-size: 12px; line-height: 1.6; }
.mono { font-variant-numeric: tabular-nums; }
</style>
