<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

interface Gateway {
  id: number
  name: string
  protocol: string
  host: string
  port: number
  unit_id: number
  topic: string | null
  mapping: unknown
  interval_s: number
  enabled: boolean
  note: string | null
}
interface Sensor {
  id: number
  name: string
  kind: string
  unit: string
}

const auth = useAuthStore()
const rows = ref<Gateway[]>([])
const sensors = ref<Sensor[]>([])
const runtime = ref<{ id: number; state: string; error?: string }[]>([])
const creating = ref(false)
const form = ref({
  name: '', protocol: 'modbus', host: '', port: 502, unit_id: 1,
  topic: '', interval_s: 10, sensorId: '', register: 0, scale: 1,
})

const protoOptions = [
  { value: 'modbus', label: 'Modbus TCP' },
  { value: 'mqtt', label: 'MQTT' },
]
const sensorOptions = computed(() =>
  sensors.value.map((s) => ({ value: String(s.id), label: `${s.name}（${s.unit || s.kind}）` })))

async function load() {
  rows.value = (await api.sensorGateways()) as unknown as Gateway[]
  try {
    runtime.value = (await api.sensorGatewayRuntime()) as unknown as typeof runtime.value
  } catch { runtime.value = [] }
}

function stateOf(id: number): string {
  const r = runtime.value.find((x) => x.id === id)
  if (!r) return '未运行'
  return r.state === 'ok' ? '正常' : r.state === 'subscribed' ? '订阅中' : '异常'
}

async function create() {
  if (!form.value.name.trim() || !form.value.host.trim()) return toast('名称和地址必填', 'warn')
  const body: Record<string, unknown> = {
    name: form.value.name.trim(), protocol: form.value.protocol,
    host: form.value.host.trim(), port: Number(form.value.port),
    unit_id: Number(form.value.unit_id), interval_s: Number(form.value.interval_s),
  }
  if (form.value.protocol === 'modbus') {
    if (!form.value.sensorId) return toast('先选一个传感器', 'warn')
    body.mapping = [{
      sensor_id: Number(form.value.sensorId),
      register: Number(form.value.register),
      scale: Number(form.value.scale),
    }]
  } else {
    if (!form.value.topic.trim()) return toast('MQTT 必须填订阅主题', 'warn')
    body.topic = form.value.topic.trim()
  }
  try {
    await api.createSensorGateway(body)
    toast('网关已创建，采集线程已启动', 'ok')
    creating.value = false
    form.value.name = ''
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '创建失败', 'danger')
  }
}

async function test(g: Gateway) {
  try {
    const res = await api.testSensorGateway(g.id)
    if (res.ok) {
      toast(res.raw !== undefined
        ? `读取成功：原始 ${res.raw} → ${res.value}`
        : '连通正常', 'ok', 5000)
    } else {
      toast(`不通：${res.error}`, 'danger', 6000)
    }
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '测试失败', 'danger')
  }
}

async function remove(g: Gateway) {
  if (!window.confirm(`删除网关「${g.name}」？采集线程会停止。`)) return
  await api.deleteSensorGateway(g.id)
  toast('已删除', 'ok')
  await load()
}

onMounted(async () => {
  try {
    sensors.value = (await api.sensors()) as unknown as Sensor[]
  } catch { /* 无传感器也能看列表 */ }
  await load()
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>采集网关</span>
        <span class="muted small">
          Modbus TCP / MQTT → 平台读数；和手工录入走同一条入库与判阈值路径
        </span>
        <span class="grow" />
        <button class="btn btn-sm primary" :disabled="!auth.canWrite" @click="creating = true">新增网关</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 160px">名称</th>
            <th style="width: 110px">协议</th>
            <th style="width: 170px">地址</th>
            <th style="width: 150px">映射 / 主题</th>
            <th style="width: 90px">周期</th>
            <th style="width: 90px">运行</th>
            <th style="width: 150px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="g in rows" :key="g.id">
            <td>{{ g.id }}</td>
            <td>{{ g.name }}</td>
            <td class="dim">{{ g.protocol === 'modbus' ? 'Modbus TCP' : 'MQTT' }}</td>
            <td class="num dim">{{ g.host }}:{{ g.port }}</td>
            <td class="dim small">
              {{ g.protocol === 'mqtt' ? (g.topic || '—') : JSON.stringify(g.mapping).slice(0, 46) }}
            </td>
            <td class="num dim">{{ g.interval_s }}s</td>
            <td><span class="tag" :class="stateOf(g.id) === '正常' || stateOf(g.id) === '订阅中' ? 'ok' : 'warn'">{{ stateOf(g.id) }}</span></td>
            <td>
              <div class="row-actions">
                <button class="btn btn-xs" :disabled="!auth.canWrite" @click="test(g)">测试</button>
                <button class="act danger" :disabled="!auth.canWrite" @click="remove(g)">🗑</button>
              </div>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="8" class="dim">
              还没有采集网关。现场气体报警器如果是 Modbus TCP，填地址 + 寄存器就能接；
              没有硬件时先用 <code>python tools_sensor_sim.py --port 15020</code> 起模拟从站。
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal">
        <div class="panel-title"><span>新增采集网关</span><span class="req-legend">带 * 为必填</span></div>
        <div class="two">
          <label class="fld"><span>名称<i class="req">*</i></span>
            <input class="input" v-model="form.name" placeholder="泵房气体报警器" /></label>
          <label class="fld"><span>协议<i class="req">*</i></span>
            <DarkSelect v-model="form.protocol" :options="protoOptions" width="100%" /></label>
        </div>
        <div class="two">
          <label class="fld"><span>地址<i class="req">*</i></span>
            <input class="input" v-model="form.host" placeholder="192.168.8.x" /></label>
          <label class="fld"><span>端口</span>
            <input class="input" type="number" v-model.number="form.port" /></label>
        </div>

        <template v-if="form.protocol === 'modbus'">
          <div class="two">
            <label class="fld"><span>从站号</span>
              <input class="input" type="number" v-model.number="form.unit_id" /></label>
            <label class="fld"><span>寄存器地址</span>
              <input class="input" type="number" v-model.number="form.register" /></label>
          </div>
          <div class="two">
            <label class="fld"><span>对应传感器<i class="req">*</i></span>
              <DarkSelect v-model="form.sensorId" :options="sensorOptions" width="100%" /></label>
            <label class="fld"><span>系数（原值×系数）</span>
              <input class="input" type="number" step="0.1" v-model.number="form.scale" /></label>
          </div>
        </template>
        <template v-else>
          <label class="fld"><span>订阅主题<i class="req">*</i></span>
            <input class="input" v-model="form.topic" placeholder="factory/gas/#" /></label>
          <p class="muted small">消息格式：<code>{"sensor_id": 3, "value": 12.5}</code></p>
        </template>

        <label class="fld"><span>采集周期（秒）</span>
          <input class="input" type="number" v-model.number="form.interval_s" /></label>

        <div class="modal-actions">
          <button class="btn" @click="creating = false">取消</button>
          <button class="btn primary" @click="create">创建</button>
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
code { background: rgba(0, 30, 60, 0.6); padding: 1px 5px; border-radius: 3px; }
.modal-mask { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 14, 30, 0.66); }
.modal { width: 560px; padding: 14px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6); }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.fld { display: block; margin-bottom: 11px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 4px; }
.fld .input { width: 100%; box-sizing: border-box; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
</style>
