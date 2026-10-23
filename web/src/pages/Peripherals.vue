<script setup lang="ts">
/**
 * 外设管理：现场换云台/加传感器后，在这里登记；首页面板会跟着变。
 * 不用改代码——能力是外设派生出来的（见 services/capabilities.py）。
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

type Periph = {
  id: number; robot_id: number; kind: string; vendor: string | null; model: string | null
  channel: string | null; sensor_id: number | null; video_id: number | null; enabled: boolean
  config: Record<string, unknown> | null
}
type Device = { id: number; name: string; station: string }
type Sensor = { id: number; name: string; kind: string; unit: string }
type Video = { id: number; name: string; stream_name: string }

const auth = useAuthStore()
const devices = ref<Device[]>([])
const deviceId = ref('')
const rows = ref<Periph[]>([])
const sensors = ref<Sensor[]>([])
const videos = ref<Video[]>([])
const caps = ref<string[]>([])
const loading = ref(false)

const KIND_LABEL: Record<string, string> = {
  camera: '云台可见光', thermal: '热像仪', ptz: '云台控制', gas: '气体传感器',
  env: '环境传感器', temp: '温度', humidity: '湿度', noise: '噪声', dust: '粉尘', speaker: '喊话器',
}

const deviceOptions = computed(() => devices.value.map((d) => ({ value: String(d.id), label: `${d.name}（${d.station}）` })))
const kindOptions = Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))
const sensorOptions = computed(() => [
  { value: '', label: '不关联' },
  ...sensors.value.map((s) => ({ value: String(s.id), label: `${s.name}（${s.unit}）` })),
])
const videoOptions = computed(() => [
  { value: '', label: '不关联' },
  ...videos.value.map((v) => ({ value: String(v.id), label: `${v.name}（${v.stream_name}）` })),
])

// 新增表单
const form = ref({ kind: 'camera', vendor: 'hikvision', model: '', channel: '', sensor_id: '', video_id: '' })
const adding = ref(false)

async function load() {
  if (!deviceId.value) return
  loading.value = true
  try {
    const id = Number(deviceId.value)
    const [p, s, v, c] = await Promise.all([
      api.peripherals(id), api.sensors(id), api.videos(id), api.robotCapabilities(id),
    ])
    rows.value = p as Periph[]
    sensors.value = s as Sensor[]
    videos.value = v as Video[]
    caps.value = (c as { capabilities?: string[] }).capabilities ?? []
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '外设加载失败', 'danger')
  } finally {
    loading.value = false
  }
}

async function add() {
  if (!deviceId.value) return
  if (!form.value.channel && !form.value.sensor_id && !form.value.video_id) {
    return toast('至少填通道，或关联传感器/视频', 'warn')
  }
  adding.value = true
  try {
    await api.createPeripheral({
      robot_id: Number(deviceId.value),
      kind: form.value.kind,
      vendor: form.value.vendor || null,
      model: form.value.model || null,
      channel: form.value.channel || null,
      sensor_id: form.value.sensor_id ? Number(form.value.sensor_id) : null,
      video_id: form.value.video_id ? Number(form.value.video_id) : null,
    })
    toast('外设已添加，首页面板会跟着出现', 'ok', 4000)
    form.value = { kind: 'camera', vendor: 'hikvision', model: '', channel: '', sensor_id: '', video_id: '' }
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '添加失败', 'danger')
  } finally {
    adding.value = false
  }
}

async function toggle(p: Periph) {
  try {
    await api.updatePeripheral(p.id, { enabled: !p.enabled })
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '操作失败', 'danger')
  }
}

async function remove(p: Periph) {
  if (!window.confirm(`删除外设「${KIND_LABEL[p.kind] ?? p.kind}」？首页对应面板会消失`)) return
  try {
    await api.deletePeripheral(p.id)
    toast('已删除', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '删除失败', 'danger')
  }
}

onMounted(async () => {
  try {
    devices.value = await api.devices() as Device[]
    if (devices.value.length) { deviceId.value = String(devices.value[0].id); await load() }
  } catch { /* 忽略 */ }
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="bar">
        <h2>外设管理</h2>
        <span class="dim small">现场换云台、加传感器后在这里登记；首页面板按外设自动出现/消失</span>
        <div class="spacer" />
        <DarkSelect v-model="deviceId" :options="deviceOptions" width="240px" @update:model-value="load" />
        <button class="btn" :disabled="loading" @click="load">刷新</button>
      </div>

      <p v-if="caps.length" class="caps">
        当前能力：
        <span v-for="c in caps" :key="c" class="tag">{{ c }}</span>
      </p>

      <table class="grid">
        <thead>
          <tr><th style="width:60px">ID</th><th style="width:130px">类型</th><th>厂商/型号</th>
            <th style="width:150px">通道</th><th style="width:150px">关联</th>
            <th style="width:80px">启用</th><th style="width:150px">操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in rows" :key="p.id">
            <td class="dim">{{ p.id }}</td>
            <td class="strong">{{ KIND_LABEL[p.kind] ?? p.kind }}</td>
            <td class="dim">{{ p.vendor || '—' }} {{ p.model || '' }}</td>
            <td class="dim">{{ p.channel || '—' }}</td>
            <td class="dim">
              <template v-if="p.sensor_id">传感器 #{{ p.sensor_id }}</template>
              <template v-else-if="p.video_id">视频 #{{ p.video_id }}</template>
              <template v-else>—</template>
            </td>
            <td>
              <span class="tag" :class="p.enabled ? 'ok' : 'warn'">{{ p.enabled ? '是' : '否' }}</span>
            </td>
            <td>
              <button class="btn btn-xs" :disabled="!auth.canWrite" @click="toggle(p)">
                {{ p.enabled ? '停用' : '启用' }}
              </button>
              <button class="btn btn-xs danger" :disabled="!auth.canWrite" @click="remove(p)">删除</button>
            </td>
          </tr>
          <tr v-if="!rows.length"><td colspan="7" class="dim">这台设备还没有登记外设</td></tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <div class="bar"><h2>新增外设</h2></div>
      <div class="form">
        <label>类型<DarkSelect v-model="form.kind" :options="kindOptions" width="150px" /></label>
        <label>厂商<input v-model="form.vendor" class="input" placeholder="hikvision / dahua" /></label>
        <label>型号<input v-model="form.model" class="input" placeholder="可选" /></label>
        <label>通道<input v-model="form.channel" class="input" placeholder="CH201 / /dev/ttyUSB0 / camera_02" /></label>
        <label>关联传感器<DarkSelect v-model="form.sensor_id" :options="sensorOptions" width="200px" /></label>
        <label>关联视频<DarkSelect v-model="form.video_id" :options="videoOptions" width="200px" /></label>
        <button class="btn primary" :disabled="adding || !auth.canWrite" @click="add">添加</button>
      </div>
      <p class="dim small">
        例：热像仪选「热像仪」+ 通道 CH201 → 首页出现热红外面板；
        粉尘仪选「粉尘」并关联一个传感器 → 环境面板多一项。
      </p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; padding: 12px; }
.panel { padding: 10px 12px; }
.bar { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.bar h2 { margin: 0; font-size: 14px; }
.spacer { flex: 1; }
.caps { margin: 0 0 8px; font-size: 12px; color: #9fd2ff; }
.caps .tag { margin-right: 4px; }
.form { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)) auto; gap: 8px 12px; align-items: end; }
.form label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #9fd2ff; }
.input { width: 100%; box-sizing: border-box; }
</style>
