<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { useRobotStore } from '@/stores/robot'
import DarkSelect from '@/components/DarkSelect.vue'

interface SysMsg {
  id: number
  ts: number
  level: 'info' | 'warn' | 'danger'
  source: string
  title: string
  body: string
  link: Record<string, unknown>
}

const robot = useRobotStore()
const router = useRouter()

const sys = ref<SysMsg[]>([])
const filter = ref('all')
const loading = ref(false)

const READ_KEY = 'jc_msg_read_ts'
const readTs = ref(Number(localStorage.getItem(READ_KEY) ?? 0))

const sourceText: Record<string, string> = {
  alarm: '告警', video: '视频', user: '账号', system: '系统',
}
const levelText: Record<string, string> = { info: '提示', warn: '注意', danger: '严重' }
const levelTone: Record<string, string> = { info: 'ok', warn: 'warn', danger: 'danger' }

const filters = [
  { value: 'all', label: '全部' },
  { value: 'alarm', label: '告警' },
  { value: 'video', label: '视频' },
  { value: 'system', label: '系统' },
]

/** 统一消息流：系统消息（后端环形缓冲）+ 告警（平台规则实时生成） */
const merged = computed(() => {
  const alarms = robot.alarms.map((a) => ({
    key: `a${a.id}`,
    ts: Date.parse(a.started_at) / 1000 || 0,
    source: 'alarm',
    level: a.level === 'critical' ? 'danger' : 'warn',
    title: a.message,
    body: a.acked_at ? `已于 ${a.acked_at.slice(11, 19)} 由 ${a.acked_by} 确认` : '未确认',
    to: { name: 'alarms', query: { status: a.acked_at ? 'acked' : 'unacked' } } as Record<string, unknown>,
  }))
  const systems = sys.value.map((m) => {
    const l = (m.link ?? {}) as { to?: string; query?: Record<string, string> }
    return {
      key: `s${m.id}`,
      ts: m.ts,
      source: m.source,
      level: m.level,
      title: m.title,
      body: m.body,
      to: (l.to ? { name: l.to, query: l.query } : {}) as Record<string, unknown>,
    }
  })
  return [...alarms, ...systems].sort((a, b) => b.ts - a.ts)
})

const rows = computed(() =>
  merged.value.filter((m) => (filter.value === 'all' ? true : m.source === filter.value)),
)
const unread = computed(() => rows.value.filter((m) => m.ts > readTs.value).length)

function fmt(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function open(m: { to: Record<string, unknown> }) {
  const t = m.to as { name?: string; query?: Record<string, unknown> }
  if (!t?.name) return
  void router.push({ name: t.name, query: t.query as Record<string, string> })
}

function markAllRead() {
  readTs.value = Date.now() / 1000
  localStorage.setItem(READ_KEY, String(readTs.value))
}

async function load() {
  loading.value = true
  try {
    const res = await api.messages()
    sys.value = res.items as unknown as SysMsg[]
  } catch {
    sys.value = []
  } finally {
    loading.value = false
  }
}

let timer = 0
onMounted(async () => {
  await load()
  void robot.refreshAlarms()
  timer = window.setInterval(load, 10000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>消息中心</span>
        <span class="tag warn" v-if="unread">{{ unread }} 条未读</span>
        <span class="muted">告警 + 视频 + 账号等系统事件，重启后系统消息清空</span>
      </div>

      <div class="toolbar">
        <label>类型</label>
        <DarkSelect v-model="filter" :options="filters" width="130px" />
        <button class="btn btn-sm" :disabled="loading" @click="load">刷新</button>
        <button class="btn btn-sm warn" @click="markAllRead">全部标为已读</button>
        <span class="grow" />
        <span class="muted small">共 {{ rows.length }} 条</span>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 150px">时间</th>
            <th style="width: 90px">类型</th>
            <th style="width: 80px">级别</th>
            <th>内容</th>
            <th style="width: 110px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in rows" :key="m.key" :class="{ unread: m.ts > readTs }">
            <td class="num dim">{{ fmt(m.ts) }}</td>
            <td>{{ sourceText[m.source] ?? m.source }}</td>
            <td><span class="tag" :class="levelTone[m.level]">{{ levelText[m.level] }}</span></td>
            <td>
              <b class="title">{{ m.title }}</b>
              <div v-if="m.body" class="dim small">{{ m.body }}</div>
            </td>
            <td>
              <button v-if="(m.to as any)?.name" class="link-btn" @click="open(m)">查看</button>
              <span v-else class="dim">—</span>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="5" class="dim">
              {{ loading ? '读取中…' : '暂无消息。视频源注册、录像起停、告警确认都会在这里留痕' }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.num { font-variant-numeric: tabular-nums; }
.title { color: #eaf7ff; font-weight: 600; font-size: 13px; }
.small { font-size: 12px; }
tr.unread td { background: rgba(41, 212, 255, 0.12); }
tr.unread .title::before {
  content: ""; display: inline-block;
  width: 6px; height: 6px; margin-right: 6px; border-radius: 50%;
  background: #ffcf3f; box-shadow: 0 0 6px rgba(255, 207, 63, 0.9);
}
.link-btn { background: none; border: none; cursor: pointer; color: #7fe9ff; font-size: 12px; }
</style>
