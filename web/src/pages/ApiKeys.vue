<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

interface Client {
  id: number
  name: string
  prefix: string
  scopes: string[]
  enabled: boolean
  created_at: string | null
  last_used_at: string | null
}

const auth = useAuthStore()
const rows = ref<Client[]>([])
const creating = ref(false)
const form = ref({ name: '', scopes: ['task:ingest', 'ai:write'] })
const newKey = ref('')

const SCOPES = [
  { value: 'task:ingest', label: '回传任务结果' },
  { value: 'ai:write', label: '推送 AI 识别结果' },
  { value: 'sensor:write', label: '推送环境读数' },
  { value: 'read:alarms', label: '只读告警' },
]

async function load() {
  try {
    rows.value = (await api.apiClients()) as unknown as Client[]
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '读取失败', 'danger')
  }
}

function toggleScope(v: string) {
  const i = form.value.scopes.indexOf(v)
  if (i >= 0) form.value.scopes.splice(i, 1)
  else form.value.scopes.push(v)
}

async function create() {
  if (!form.value.name.trim()) return toast('名称必填', 'warn')
  if (!form.value.scopes.length) return toast('至少选一个权限', 'warn')
  try {
    const res = await api.createApiClient({ name: form.value.name.trim(), scopes: form.value.scopes })
    newKey.value = String(res.key ?? '')
    creating.value = false
    form.value = { name: '', scopes: ['task:ingest', 'ai:write'] }
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '创建失败', 'danger')
  }
}

async function revoke(c: Client) {
  if (!window.confirm(`吊销「${c.name}」？吊销后立即失效，无法恢复。`)) return
  await api.revokeApiClient(c.id)
  toast('已吊销', 'ok')
  await load()
}

async function copy() {
  try {
    await navigator.clipboard.writeText(newKey.value)
    toast('已复制', 'ok')
  } catch {
    toast('复制失败，请手动选中', 'warn')
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>接口密钥</span>
        <span class="muted small">
          机器人、算法盒、厂内系统对接用；明文只显示一次，服务端只存哈希
        </span>
        <span class="grow" />
        <button class="btn btn-sm primary" :disabled="!auth.canWrite || auth.user?.role !== 'admin'" @click="creating = true">
          新建密钥
        </button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 160px">名称</th>
            <th style="width: 120px">前缀</th>
            <th>权限</th>
            <th style="width: 90px">状态</th>
            <th style="width: 150px">最近使用</th>
            <th style="width: 90px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in rows" :key="c.id">
            <td>{{ c.id }}</td>
            <td>{{ c.name }}</td>
            <td class="mono dim">{{ c.prefix }}…</td>
            <td class="dim small">{{ c.scopes.join(' / ') }}</td>
            <td><span class="tag" :class="c.enabled ? 'ok' : 'warn'">{{ c.enabled ? '启用' : '已吊销' }}</span></td>
            <td class="num dim">{{ (c.last_used_at ?? '—').replace('T', ' ') }}</td>
            <td>
              <button v-if="c.enabled" class="act danger" title="吊销" @click="revoke(c)">🗑</button>
            </td>
          </tr>
          <tr v-if="!rows.length"><td colspan="7" class="dim">还没有密钥。给算法盒或机器人建一个。</td></tr>
        </tbody>
      </table>

      <p class="muted small">
        用法：请求头加 <code>X-Api-Key: jck_…</code>，不带 Cookie/CSRF。示例：<br />
        <code>curl -X POST http://&lt;host&gt;/api/v1/ai/results -H "X-Api-Key: jck_…" \
          -H "Content-Type: application/json" -d '{"algorithm":"meter","camera_id":1,"value":12.5,"confidence":0.92}'</code>
      </p>
    </section>

    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal">
        <div class="panel-title"><span>新建接口密钥</span><span class="req-legend">带 * 为必填</span></div>
        <label class="fld"><span>名称<i class="req">*</i></span>
          <input class="input" v-model="form.name" placeholder="算法盒-01 / 机器人-01" />
        </label>
        <div class="fld">
          <span>权限</span>
          <div class="scopes">
            <label v-for="s in SCOPES" :key="s.value" class="chk">
              <input type="checkbox" :checked="form.scopes.includes(s.value)" @change="toggleScope(s.value)" />
              {{ s.label }}
            </label>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn" @click="creating = false">取消</button>
          <button class="btn primary" @click="create">创建</button>
        </div>
      </div>
    </div>

    <div v-if="newKey" class="modal-mask" @click.self="newKey = ''">
      <div class="modal">
        <div class="panel-title"><span>密钥只显示这一次</span></div>
        <p class="warn small">关掉就看不到了；丢了只能吊销重建。</p>
        <div class="keybox">{{ newKey }}</div>
        <div class="modal-actions">
          <button class="btn" @click="copy">复制</button>
          <button class="btn primary" @click="newKey = ''">我已保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.small { font-size: 12px; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
code { background: rgba(0, 30, 60, 0.6); padding: 1px 5px; border-radius: 3px; font-size: 11.5px; }
.modal-mask { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 14, 30, 0.66); }
.modal { width: 480px; padding: 14px 16px; background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98)); border: 1px solid rgba(111, 227, 255, 0.6); }
.fld { display: block; margin-bottom: 11px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; box-sizing: border-box; }
.scopes { display: flex; flex-wrap: wrap; gap: 12px; }
.chk { display: flex; align-items: center; gap: 5px; font-size: 12.5px; }
.keybox { padding: 10px; background: #04203c; border: 1px solid rgba(111, 227, 255, 0.4); word-break: break-all; font-family: ui-monospace, monospace; font-size: 12px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
</style>
