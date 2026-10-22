<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import DarkSelect from '@/components/DarkSelect.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const caps = ref<Record<string, unknown> | null>(null)
const health = ref<Awaited<ReturnType<typeof api.deepHealth>> | null>(null)
const robot = ref<Awaited<ReturnType<typeof api.robots>>[number] | null>(null)
const message = ref('')

// ---- 平台设置（落库、可审计、立即生效）----
interface SchemaItem {
  key: string
  label: string
  type: 'int' | 'float' | 'bool' | 'str'
  group: string
  effect: string
  min?: number
  max?: number
  default: unknown
}
const schema = ref<SchemaItem[]>([])
const values = ref<Record<string, unknown>>({})
const dirty = ref<Record<string, unknown>>({})
const saving = ref(false)

const groups = computed(() => {
  const out: Record<string, SchemaItem[]> = {}
  for (const it of schema.value) (out[it.group] ||= []).push(it)
  return out
})
const dirtyCount = computed(() => Object.keys(dirty.value).length)

async function loadSettings() {
  try {
    const res = await api.settings()
    schema.value = res.schema as unknown as SchemaItem[]
    values.value = res.values
    dirty.value = {}
  } catch (e) {
    message.value = e instanceof Error ? e.message : '设置读取失败'
  }
}

function onEdit(key: string, raw: unknown) {
  dirty.value = { ...dirty.value, [key]: raw }
}

function canEditKey(key: string): boolean {
  if (auth.user?.role === 'admin') return true
  if (auth.user?.role === 'safety') return key.startsWith('alarm.') || key.startsWith('notify.') || key.startsWith('clock.')
  return false
}

async function saveSettings() {
  if (!dirtyCount.value) return
  saving.value = true
  message.value = ''
  try {
    const res = await api.saveSettings(dirty.value)
    values.value = res.values
    dirty.value = {}
    message.value = `已保存 ${Object.keys(res.changed).length} 项，立即生效`
  } catch (e) {
    message.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function loadRobot() {
  try {
    robot.value = (await api.robots())[0] ?? null
  } catch (e) {
    message.value = e instanceof Error ? e.message : '机器人配置读取失败'
  }
}

async function loadCaps() {
  try {
    caps.value = await api.capabilities(1)
  } catch (e) {
    message.value = e instanceof Error ? e.message : '能力读取失败'
  }
}

async function loadHealth() {
  try {
    health.value = await api.deepHealth()
  } catch (e) {
    message.value = e instanceof Error ? e.message : '探针失败'
  }
}

async function probe() {
  message.value = ''
  try {
    caps.value = await api.probe(1)
    message.value = '能力探测完成'
  } catch (e) {
    message.value = e instanceof Error ? e.message : '探测失败'
  }
}

onMounted(async () => {
  await loadSettings()
  await loadRobot()
  await loadCaps()
  await loadHealth()
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>平台设置</span>
        <span class="muted small">改完立即生效，不用重启；写库并记审计</span>
        <span class="grow" />
        <span v-if="dirtyCount" class="tag warn">{{ dirtyCount }} 项未保存</span>
        <button class="btn btn-sm" :disabled="!dirtyCount" @click="dirty = {}">撤销</button>
        <button class="btn btn-sm primary" :disabled="!dirtyCount || saving || !auth.canWrite" @click="saveSettings">
          {{ saving ? '保存中…' : '保存配置' }}
        </button>
      </div>

      <div class="set-grid">
        <div v-for="(items, g) in groups" :key="g" class="set-group">
          <div class="set-head">{{ g }}</div>
          <div v-for="it in items" :key="it.key" class="set-row" :class="{ wide: it.type === 'str' }">
            <label :title="it.effect">{{ it.label }}</label>
            <DarkSelect
              v-if="it.type === 'bool'"
              :model-value="String(dirty[it.key] ?? values[it.key])"
              :options="[{ value: 'true', label: '开启' }, { value: 'false', label: '关闭' }]"
              width="110px"
              @update:model-value="onEdit(it.key, $event === 'true')"
            />
            <input
              v-else-if="it.type === 'str'"
              class="input"
              :value="dirty[it.key] ?? values[it.key]"
              @input="onEdit(it.key, ($event.target as HTMLInputElement).value)"
            />
            <input
              v-else
              class="input num-in"
              type="number"
              :min="it.min" :max="it.max"
              :step="it.type === 'float' ? 0.01 : 1"
              :value="dirty[it.key] ?? values[it.key]"
              @input="onEdit(it.key, Number(($event.target as HTMLInputElement).value))"
            />
            <span class="eff">{{ it.effect }}</span>
          </div>
        </div>
      </div>
      <p v-if="message" class="muted small">{{ message }}</p>
    </section>

    <section class="panel">
      <div class="panel-title"><span>机器人连接</span></div>
      <table class="grid" v-if="robot">
        <thead>
          <tr><th>名称</th><th>IP</th><th>HTTP 端口</th><th>模式</th><th>固件</th><th>导航源</th><th>最后在线</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>{{ robot.name }}</td>
            <td class="num">{{ robot.ip }}</td>
            <td class="num">{{ robot.port }}</td>
            <td><span class="tag" :class="robot.mode === 'mock' ? 'warn' : 'ok'">{{ robot.mode }}</span></td>
            <td class="num">{{ robot.version ?? '待探测' }}</td>
            <td>{{ robot.slam_type ?? '待探测' }}</td>
            <td class="dim">{{ robot.last_seen ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted small">读取中…</p>
      <p class="muted small">
        连接参数存在服务端配置里，改 IP/账号走 <code>server/.env</code>；页面只读展示，避免误改。
      </p>
    </section>

    <section class="panel">
      <div class="panel-title">
        <span>能力矩阵</span>
        <button class="btn" :disabled="!auth.canWrite" @click="probe">重新探测</button>
      </div>
      <p class="muted small">
        不按固件版本写死能力：启动时逐接口探测，缺什么就隐藏/置灰。不支持时接口返回
        <code>JCROB_NOT_SUPPORTED</code>，页面显示“当前固件不支持”，不弹成功。
      </p>
      <pre v-if="caps" class="json">{{ JSON.stringify(caps, null, 2) }}</pre>
      <p v-else class="muted small">还没有探测结果。</p>
    </section>

    <section class="panel">
      <div class="panel-title">
        <span>运行状态</span>
        <button class="btn" @click="loadHealth">刷新</button>
      </div>
      <div v-if="health" class="health">
        <div class="kv"><span>链路在线</span><b :class="health.cache.online ? 'ok' : 'danger'">{{ health.cache.online ? '是' : '否' }}</b></div>
        <div class="kv"><span>数据年龄</span><b>{{ health.cache.age_s.toFixed(1) }} s</b></div>
        <div class="kv"><span>连续失败</span><b>{{ health.cache.consecutive_failures }}</b></div>
        <div class="kv"><span>事件循环延迟</span><b>{{ health.loop_lag_ms }} ms</b></div>
        <div class="kv" v-for="s in health.services" :key="s.name">
          <span>后台循环 {{ s.name }}</span>
          <b :class="s.running ? 'ok' : 'danger'">{{ s.running ? '运行中' : '已停止' }}（重启 {{ s.restarts }} 次）</b>
        </div>
        <p v-if="health.cache.last_error" class="danger small">最近错误：{{ health.cache.last_error }}</p>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title">关于</div>
      <p class="muted small">
        一期范围：驾驶舱、地图与点位、任务只读、告警、历史、审计、基础 RBAC。
        视频 / 云台 / 测温 / 三维场站 / BMS / AI 识别 / 多机器人 / 7×24 录像 均为二期或不排期。
      </p>
      <p class="muted small">
        部署：Docker Compose 三容器（jc-server / jc-mysql / jc-nginx），nginx 宿主端口 8099。
      </p>
      <p v-if="message" class="small">{{ message }}</p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.json {
  background: var(--bg-2); border: 1px solid var(--line); border-radius: 8px;
  padding: 12px; font-size: 12px; max-height: 320px; overflow: auto;
}
.health { display: flex; flex-direction: column; gap: 4px; }
.kv { display: flex; justify-content: space-between; font-size: 13px; padding: 3px 0; }
.kv span { color: var(--text-2); }
.small { font-size: 12px; line-height: 1.6; }

/* 设置分组 */
.set-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
.set-group {
  overflow: hidden;
  border: 1px solid rgba(111, 227, 255, 0.18);
  background: rgba(0, 60, 110, 0.28);
  border-radius: 6px; padding: 8px 10px 10px;
}
.set-head {
  font-size: 12px; font-weight: 700; color: #ffe08a; letter-spacing: 0.08em;
  margin-bottom: 8px; padding-bottom: 5px;
  border-bottom: 1px solid rgba(255, 207, 63, 0.22);
}
.set-row {
  display: grid; grid-template-columns: minmax(0, 1fr) 104px; gap: 8px 10px;
  align-items: center; margin-bottom: 9px;
}
/* 不加这两条，input 的 padding/border 会把行撑出格子 */
.set-row > * { min-width: 0; }
.set-row .input, .set-row .dasel { width: 100%; box-sizing: border-box; }
.set-row.wide { grid-template-columns: minmax(0, 1fr) 190px; }
.set-row label { font-size: 12.5px; color: #dceeff; }

.num-in { text-align: right; }
.eff { grid-column: 1 / -1; font-size: 11px; color: #7fa8cc; line-height: 1.5; margin-top: -4px; }
</style>
