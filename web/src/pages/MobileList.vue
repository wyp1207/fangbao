<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'

const props = defineProps<{ tab?: 'task' | 'wo' }>()
const route = useRoute()
const router = useRouter()
const tab = ref<'task' | 'wo'>(props.tab ?? (route.path.includes('work-order') ? 'wo' : 'task'))
const loading = ref(false)
const error = ref('')
const rows = ref<any[]>([])

const title = computed(() => (tab.value === 'task' ? '我的巡检任务' : '我的工单'))

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (tab.value === 'task') {
      const res = await api.inspectionTasks({ mine: true })
      rows.value = ((res as any).items ?? res ?? []) as any[]
    } else {
      const res = await api.workOrders({})
      rows.value = ((res as any).items ?? res ?? []) as any[]
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
    rows.value = []
  } finally {
    loading.value = false
  }
}

function open(row: any) {
  if (tab.value === 'task') void router.push(`/m/task/${row.id}`)
  else void router.push(`/m/wo/${row.id}`)
}

function label(row: any): string {
  return row.title || row.name || row.order_no || `#${row.id}`
}

function status(row: any): string {
  const s = String(row.status ?? row.state ?? '')
  const map: Record<string, string> = {
    pending: '待执行', planned: '待执行', running: '执行中', done: '已完成',
    failed: '异常', cancelled: '已取消', open: '待派单', assigned: '已派单',
    doing: '处理中', closed: '已关闭',
  }
  return map[s] ?? s ?? '—'
}

onMounted(load)
</script>

<template>
  <div class="ml">
    <header>
      <h3>{{ title }}</h3>
      <button class="btn btn-sm" :disabled="loading" @click="load">刷新</button>
    </header>

    <div class="tabs">
      <button :class="{ on: tab === 'task' }" @click="tab = 'task'; load()">巡检任务</button>
      <button :class="{ on: tab === 'wo' }" @click="tab = 'wo'; load()">工单</button>
    </div>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="loading" class="dim">加载中…</p>
    <p v-else-if="!rows.length" class="dim">暂无数据（扫码进入具体任务/工单也可以）</p>

    <ul v-else class="list">
      <li v-for="r in rows" :key="r.id" @click="open(r)">
        <span class="name">{{ label(r) }}</span>
        <span class="st">{{ status(r) }}</span>
        <span class="go">›</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.ml { min-height: 100vh; padding: 16px; background: #071a30; color: #dff0ff; }
header { display: flex; align-items: center; justify-content: space-between; }
h3 { margin: 0; font-size: 17px; letter-spacing: 1px; }
.tabs { display: flex; gap: 8px; margin: 12px 0; }
.tabs button { flex: 1; padding: 8px; border-radius: 8px; border: 1px solid rgba(0,168,255,.35); background: transparent; color: #9fd6ee; }
.tabs button.on { background: rgba(0,150,220,.35); color: #fff; }
.list { list-style: none; margin: 0; padding: 0; }
.list li { display: flex; align-items: center; gap: 10px; padding: 14px 12px; margin-bottom: 8px; border-radius: 10px; background: #0b2747; border: 1px solid rgba(0,168,255,.25); }
.list .name { flex: 1; font-size: 14px; }
.list .st { font-size: 12px; color: #ffd166; }
.list .go { color: #6fb6ff; font-size: 18px; }
.dim { color: #7fa8c4; font-size: 13px; }
.err { color: #ff8f8f; font-size: 13px; }
</style>
