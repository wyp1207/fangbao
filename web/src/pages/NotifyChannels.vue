<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

interface Channel {
  id: number
  name: string
  type: string
  type_label: string
  config: Record<string, unknown>
  min_level: string
  min_interval_min: number
  enabled: boolean
  note: string | null
}
interface LogRow {
  id: number
  ts: string | null
  channel_name: string
  alarm_id: number | null
  ok: boolean
  status: string | null
  error: string | null
}

const auth = useAuthStore()
const channels = ref<Channel[]>([])
const logs = ref<LogRow[]>([])
const logTotal = ref(0)
const onlyFailed = ref(false)
const loading = ref(false)
const busy = ref<number | null>(null)

const editing = ref<Channel | null>(null)
const creating = ref(false)
const form = ref({
  name: '', type: 'wecom', url: '', min_level: 'critical', min_interval_min: 10,
  note: '',
  // email 专用
  host: '', port: 465, user: '', password: '', to: '', tls: true,
})

const typeOptions = [
  { value: 'wecom', label: '企业微信机器人' },
  { value: 'dingtalk', label: '钉钉机器人' },
  { value: 'generic', label: '通用 Webhook' },
  { value: 'email', label: '邮件（SMTP）' },
]
const levelOptions = [
  { value: 'warn', label: '提醒及以上' },
  { value: 'critical', label: '仅严重' },
]

const typeHint = computed(() => {
  switch (form.value.type) {
    case 'wecom': return '群机器人 → 添加机器人 → Webhook 地址，直接粘进来'
    case 'dingtalk': return '钉钉群 → 智能群助手 → 添加机器人 → Webhook 地址'
    case 'generic': return '任意 HTTP 接口，平台会 POST {event, alarm, text}'
    case 'email': return '填 SMTP 服务器；收件人多个用英文逗号分隔'
    default: return ''
  }
})

async function load() {
  loading.value = true
  try {
    channels.value = (await api.notifyChannels()) as unknown as Channel[]
    const res = await api.notifyLogs({ limit: 30, only_failed: onlyFailed.value })
    logs.value = res.items as unknown as LogRow[]
    logTotal.value = res.total
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = {
    name: '', type: 'wecom', url: '', min_level: 'critical', min_interval_min: 10,
    note: '', host: '', port: 465, user: '', password: '', to: '', tls: true,
  }
  creating.value = true
}

function openEdit(c: Channel) {
  const cfg = c.config ?? {}
  form.value = {
    name: c.name, type: c.type,
    url: String(cfg.url ?? ''),
    min_level: c.min_level, min_interval_min: c.min_interval_min, note: c.note ?? '',
    host: String(cfg.host ?? ''), port: Number(cfg.port ?? 465),
    user: String(cfg.user ?? ''), password: String(cfg.password ?? ''),
    to: Array.isArray(cfg.to) ? (cfg.to as string[]).join(',') : String(cfg.to ?? ''),
    tls: Boolean(cfg.tls ?? true),
  }
  editing.value = c
}

function payload() {
  const cfg: Record<string, unknown> = form.value.type === 'email'
    ? {
        host: form.value.host, port: form.value.port, user: form.value.user,
        password: form.value.password, tls: form.value.tls,
        to: form.value.to.split(',').map((s) => s.trim()).filter(Boolean),
      }
    : { url: form.value.url }
  return {
    name: form.value.name.trim(),
    type: form.value.type,
    config: cfg,
    min_level: form.value.min_level,
    min_interval_min: form.value.min_interval_min,
    note: form.value.note || null,
  }
}

async function submitCreate() {
  if (!form.value.name.trim()) return toast('名称必填', 'warn')
  try {
    await api.createNotifyChannel(payload())
    toast('通道已添加，点「测试」发一条试试', 'ok', 3500)
    creating.value = false
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '添加失败', 'danger')
  }
}

async function submitEdit() {
  if (!editing.value) return
  try {
    await api.updateNotifyChannel(editing.value.id, payload())
    toast('已保存', 'ok')
    editing.value = null
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '保存失败', 'danger')
  }
}

async function test(c: Channel) {
  busy.value = c.id
  try {
    const res = await api.testNotifyChannel(c.id)
    toast(res.ok ? `发送成功：${res.status}` : `发送失败：${res.status}`, res.ok ? 'ok' : 'danger', 5000)
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '测试失败', 'danger')
  } finally {
    busy.value = null
  }
}

async function toggle(c: Channel) {
  await api.updateNotifyChannel(c.id, { enabled: !c.enabled })
  await load()
}

async function remove(c: Channel) {
  if (!window.confirm(`删除通道「${c.name}」？`)) return
  await api.deleteNotifyChannel(c.id)
  toast('已删除', 'ok')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>告警通知</span>
        <span class="muted small">告警产生后自动推送到企业微信 / 钉钉 / Webhook / 邮件；静默期内不重复刷屏</span>
        <span class="grow" />
        <button class="btn btn-sm primary" :disabled="!auth.canWrite" @click="openCreate">新增通道</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 160px">名称</th>
            <th style="width: 150px">类型</th>
            <th style="width: 130px">触发级别</th>
            <th style="width: 130px">静默期</th>
            <th style="width: 90px">启用</th>
            <th style="width: 190px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in channels" :key="c.id">
            <td>{{ c.id }}</td>
            <td>{{ c.name }}</td>
            <td class="dim">{{ c.type_label }}</td>
            <td><span class="tag" :class="c.min_level === 'critical' ? 'danger' : 'warn'">
              {{ c.min_level === 'critical' ? '仅严重' : '提醒及以上' }}</span></td>
            <td class="num dim">{{ c.min_interval_min }} 分钟</td>
            <td><span class="tag" :class="c.enabled ? 'ok' : 'warn'">{{ c.enabled ? '开' : '关' }}</span></td>
            <td>
              <div class="row-actions">
                <button class="btn btn-xs" :disabled="busy === c.id" @click="test(c)">测试</button>
                <button class="act" title="启用/停用" @click="toggle(c)">{{ c.enabled ? '⏸' : '▶' }}</button>
                <button class="act" title="编辑" @click="openEdit(c)">✎</button>
                <button class="act danger" title="删除" @click="remove(c)">🗑</button>
              </div>
            </td>
          </tr>
          <tr v-if="!channels.length">
            <td colspan="7" class="dim">
              {{ loading ? '读取中…' : '还没有通道。最常见的是加一个企业微信群机器人，1 分钟就能配好。' }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <div class="panel-title">
        <span>投递记录</span>
        <span class="grow" />
        <label class="chk"><input type="checkbox" v-model="onlyFailed" @change="load" /> 只看失败</label>
        <button class="btn btn-sm" @click="load">刷新</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 160px">时间</th>
            <th style="width: 160px">通道</th>
            <th style="width: 90px">告警</th>
            <th style="width: 90px">结果</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="l in logs" :key="l.id">
            <td>{{ l.id }}</td>
            <td class="num dim">{{ (l.ts ?? '').replace('T', ' ') }}</td>
            <td>{{ l.channel_name }}</td>
            <td class="dim">{{ l.alarm_id ? '#' + l.alarm_id : '测试' }}</td>
            <td><span class="tag" :class="l.ok ? 'ok' : 'danger'">{{ l.ok ? '成功' : '失败' }}</span></td>
            <td class="dim small">{{ l.ok ? l.status : l.error }}</td>
          </tr>
          <tr v-if="!logs.length"><td colspan="6" class="dim">还没有投递记录</td></tr>
        </tbody>
      </table>
      <p class="muted small">共 {{ logTotal }} 条（最近 30 条）</p>
    </section>

    <!-- 新增/编辑 -->
    <div v-if="creating || editing" class="modal-mask" @click.self="creating = false; editing = null">
      <div class="modal">
        <div class="panel-title"><span>{{ editing ? '编辑通道 · ' + editing.name : '新增通知通道' }}</span></div>

        <div class="two">
          <label class="fld"><span>名称</span><input class="input" v-model="form.name" placeholder="值班群（企微）" /></label>
          <label class="fld">
            <span>类型</span>
            <DarkSelect v-model="form.type" :options="typeOptions" width="100%" :disabled="!!editing" />
          </label>
        </div>

        <template v-if="form.type !== 'email'">
          <label class="fld">
            <span>Webhook 地址</span>
            <input class="input" v-model="form.url" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..." />
          </label>
        </template>
        <template v-else>
          <div class="two">
            <label class="fld"><span>SMTP 主机</span><input class="input" v-model="form.host" placeholder="smtp.example.com" /></label>
            <label class="fld"><span>端口</span><input class="input" type="number" v-model.number="form.port" /></label>
          </div>
          <div class="two">
            <label class="fld"><span>账号</span><input class="input" v-model="form.user" /></label>
            <label class="fld"><span>密码/授权码</span><input class="input" type="password" v-model="form.password" placeholder="留空不改" /></label>
          </div>
          <label class="fld"><span>收件人（逗号分隔）</span><input class="input" v-model="form.to" /></label>
          <label class="chk"><input type="checkbox" v-model="form.tls" /> 使用 SSL（465 端口一般要勾）</label>
        </template>

        <p class="muted small">{{ typeHint }}</p>

        <div class="two">
          <label class="fld">
            <span>触发级别</span>
            <DarkSelect v-model="form.min_level" :options="levelOptions" width="100%" />
          </label>
          <label class="fld">
            <span>静默期（分钟）</span>
            <input class="input" type="number" min="0" v-model.number="form.min_interval_min" />
          </label>
        </div>
        <label class="fld"><span>备注</span><input class="input" v-model="form.note" /></label>

        <div class="modal-actions">
          <button class="btn" @click="creating = false; editing = null">取消</button>
          <button class="btn primary" @click="editing ? submitEdit() : submitCreate()">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: none; }
.small { font-size: 12px; }
.num { font-variant-numeric: tabular-nums; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: #9fd2ff; margin-bottom: 10px; }
.btn-xs { padding: 2px 8px; font-size: 12px; }
.modal-mask { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 14, 30, 0.66); }
.modal {
  width: 560px; max-height: 90vh; overflow: auto; padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
}
.fld { display: block; margin-bottom: 11px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
