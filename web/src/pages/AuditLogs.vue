<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type AuditItem } from '@/api'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'

const rows = ref<AuditItem[]>([])
const total = ref(0)
const loading = ref(false)
const action = ref('')
const page = ref(1)
const pageSize = 50

const actionOptions = computed(() => {
  const set = new Set(rows.value.map((r) => r.action))
  return [{ value: '', label: '全部动作' }, ...[...set].map((a) => ({ value: a, label: a }))]
})
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const ACTION_TEXT: Record<string, string> = {
  'auth.login': '登录',
  'auth.password': '修改密码',
  'alarm.ack': '确认告警',
  'user.create': '新建账号',
  'user.update': '修改账号',
  'user.delete': '删除账号',
  'user.password': '重置密码',
}

async function reload() {
  loading.value = true
  try {
    const res = await api.auditLogs({ limit: pageSize, offset: (page.value - 1) * pageSize, action: action.value })
    rows.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function goto(p: number) {
  page.value = Math.min(Math.max(1, p), pageCount.value)
  await reload()
}

// 审计链自检：任何一行被改过，这里的哈希校验就会失败
const verifying = ref(false)
const verifyResult = ref<{ ok: boolean; checked: number; broken_at?: number; legacy_rows?: number } | null>(null)

async function verifyChain() {
  verifying.value = true
  try {
    verifyResult.value = await api.auditVerify()
  } catch (e) {
    verifyResult.value = { ok: false, checked: 0, broken_at: -1 }
    toast(e instanceof Error ? e.message : '校验失败', 'danger')
  } finally {
    verifying.value = false
  }
}

onMounted(reload)
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>操作日志</span>
        <span class="muted">谁在什么时候做了什么；写库，重启不丢</span>
      </div>

      <div class="toolbar">
        <label>动作</label>
        <DarkSelect v-model="action" :options="actionOptions" width="170px" />
        <button class="btn btn-sm ok" :disabled="loading" @click="page = 1; reload()">查询</button>
        <button class="btn btn-sm warn" @click="action = ''; page = 1; reload()">重置</button>
        <button class="btn btn-sm" :disabled="verifying" @click="verifyChain">
          {{ verifying ? '校验中…' : '校验审计链' }}
        </button>
        <span class="grow" />
        <span class="muted small">共 {{ total }} 条</span>
      </div>

      <p v-if="verifyResult" class="verify-bar" :class="verifyResult.ok ? 'ok' : 'bad'">
        <template v-if="verifyResult.ok">
          审计链完整：已校验 {{ verifyResult.checked }} 条，哈希全部对得上
          <span v-if="verifyResult.legacy_rows">（其中 {{ verifyResult.legacy_rows }} 条为早期无哈希记录）</span>
        </template>
        <template v-else>
          审计链异常：第 {{ verifyResult.broken_at }} 条开始对不上，可能被改动过
        </template>
      </p>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">#</th>
            <th style="width: 160px">时间</th>
            <th style="width: 110px">账号</th>
            <th style="width: 130px">动作</th>
            <th style="width: 150px">对象</th>
            <th>说明</th>
            <th style="width: 120px">来源 IP</th>
            <th style="width: 70px">结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rows" :key="r.id">
            <td>{{ (page - 1) * pageSize + i + 1 }}</td>
            <td class="num dim">{{ (r.ts ?? '').replace('T', ' ') }}</td>
            <td>{{ r.username ?? '—' }}</td>
            <td>{{ ACTION_TEXT[r.action] ?? r.action }}</td>
            <td class="dim">{{ r.target ?? '—' }}</td>
            <td class="dim">{{ r.summary ?? r.detail ?? '—' }}</td>
            <td class="num dim">{{ r.client_ip ?? '—' }}</td>
            <td><span class="tag" :class="r.success ? 'ok' : 'danger'">{{ r.success ? '成功' : '失败' }}</span></td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="8" class="dim">{{ loading ? '读取中…' : '还没有操作记录' }}</td>
          </tr>
        </tbody>
      </table>

      <div class="pager">
        <span>第 {{ page }}/{{ pageCount }} 页</span>
        <span class="spacer" />
        <button :disabled="page <= 1" @click="goto(page - 1)">上一页</button>
        <button class="on">{{ page }}</button>
        <button :disabled="page >= pageCount" @click="goto(page + 1)">下一页</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.num { font-variant-numeric: tabular-nums; }
.small { font-size: 12px; }

.verify-bar { margin: 8px 0; padding: 8px 10px; border-radius: 3px; font-size: 12px; }
.verify-bar.ok { background: rgba(48, 208, 64, .12); border: 1px solid rgba(48, 208, 64, .5); color: #8ef0a0; }
.verify-bar.bad { background: rgba(255, 64, 64, .12); border: 1px solid rgba(255, 64, 64, .55); color: #ff9a9a; }
</style>
