<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type DeviceItem } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'

interface AdapterMeta {
  label: string
  device_type: string
  supported: boolean
  needs: string[]
  note: string
}

const rows = ref<DeviceItem[]>([])
const meta = ref<{ device_types: { value: string; label: string }[]; adapters: Record<string, AdapterMeta> }>({
  device_types: [],
  adapters: {},
})
const loading = ref(false)
const testing = ref<number | null>(null)

const editing = ref<DeviceItem | null>(null)
const creating = ref(false)
const tried = ref(false)
const form = ref({
  name: '', device_type: 'jcrob_wheel', adapter: 'jcrob_http', station: '默认场站',
  ip: '', port: 3546, ws_port: 3547, username: 'admin', password: '', mode: 'http', note: '',
})

const deviceTypeOptions = computed(() => meta.value.device_types)
const adapterOptions = computed(() => {
  const want = form.value.device_type
  const all = Object.entries(meta.value.adapters)
    .filter(([, m]) => m.device_type === want)
    .map(([key, m]) => ({ value: key, label: m.supported ? m.label : `${m.label}（未实现）` }))
  return all.length ? all : Object.entries(meta.value.adapters).map(([key, m]) => ({ value: key, label: m.label }))
})
const currentAdapter = computed<AdapterMeta | null>(() => meta.value.adapters[form.value.adapter] ?? null)

function adapterLabel(key: string): string {
  return meta.value.adapters[key]?.label ?? key
}

async function load() {
  loading.value = true
  try {
    rows.value = await api.devices()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '设备列表读取失败', 'danger')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = {
    name: '', device_type: 'jcrob_wheel', adapter: 'jcrob_http', station: '默认场站',
    ip: '', port: 3546, ws_port: 3547, username: 'admin', password: '', mode: 'http', note: '',
  }
  creating.value = true
}

function openEdit(d: DeviceItem) {
  form.value = {
    name: d.name, device_type: d.device_type, adapter: d.adapter, station: d.station,
    ip: d.ip, port: d.port, ws_port: d.ws_port, username: d.username ?? '',
    password: '', mode: d.mode, note: d.note ?? '',
  }
  editing.value = d
}

async function submitCreate() {
  tried.value = true
  if (!form.value.name.trim() || !form.value.ip.trim()) {
    toast('设备名和 IP 必填', 'warn')
    return
  }
  try {
    await api.createDevice({ ...form.value })
    toast(`已添加 ${form.value.name}`, 'ok')
    creating.value = false
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '添加失败', 'danger')
  }
}

async function submitEdit() {
  if (!editing.value) return
  try {
    const patch: Record<string, unknown> = { ...form.value }
    if (!form.value.password) delete patch.password
    await api.updateDevice(editing.value.id, patch)
    toast('已保存', 'ok')
    editing.value = null
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '保存失败', 'danger')
  }
}

async function test(d: DeviceItem) {
  testing.value = d.id
  try {
    const res = await api.testDevice(d.id)
    toast(`${d.name}：${res.detail}`, res.tcp ? 'ok' : 'danger', 4000)
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '测试失败', 'danger')
  } finally {
    testing.value = null
  }
}

async function remove(d: DeviceItem) {
  if (!window.confirm(`删除设备「${d.name}」？只删台账，不影响机器人本体。`)) return
  try {
    await api.deleteDevice(d.id)
    toast('已删除', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '删除失败', 'danger')
  }
}

onMounted(async () => {
  try {
    meta.value = await api.deviceMeta()
  } catch { /* 下拉拿不到也能看列表 */ }
  await load()
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>设备台账</span>
        <span class="muted">一台设备 = 一套连接参数 + 一个适配器；协议没实现就标「待接入」</span>
      </div>

      <div class="toolbar">
        <span class="grow" />
        <button class="btn btn-sm" :disabled="loading" @click="load">刷新</button>
        <button class="btn btn-sm primary" @click="openCreate">新增设备</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 150px">名称</th>
            <th style="width: 200px">类型</th>
            <th style="width: 170px">协议</th>
            <th style="width: 110px">场站</th>
            <th style="width: 170px">地址</th>
            <th style="width: 110px">状态</th>
            <th style="width: 190px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in rows" :key="d.id">
            <td>{{ d.id }}</td>
            <td>{{ d.name }}</td>
            <td class="dim">{{ meta.device_types.find((t) => t.value === d.device_type)?.label ?? d.device_type }}</td>
            <td>
              <span class="tag" :class="d.supported ? 'ok' : 'warn'">{{ d.adapter_label }}</span>
            </td>
            <td class="dim">{{ d.station }}</td>
            <td class="num">{{ d.ip }}<span class="dim">:{{ d.port }}</span></td>
            <td>
              <span v-if="d.supported" class="tag">{{ d.is_active ? '协议可用' : '已停用' }}</span>
              <span v-else class="tag warn" :title="d.needs.join('、')">待接入</span>
            </td>
            <td>
              <div class="row-actions">
                <button class="act" title="测试连接" :disabled="testing === d.id" @click="test(d)">⇄</button>
                <button class="act" title="编辑" @click="openEdit(d)">✎</button>
                <button class="act danger" title="删除" :disabled="d.id === 1" @click="remove(d)">🗑</button>
              </div>
            </td>
          </tr>
          <tr v-if="!rows.length"><td colspan="8" class="dim">{{ loading ? '读取中…' : '还没有设备' }}</td></tr>
        </tbody>
      </table>

      <p class="muted small">
        「待接入」的协议只登记台账、不做通信——下方会列出它还缺什么。删除只删台账，不影响机器人本体；
        主设备（ID 1）只能停用不能删除。
      </p>
    </section>

    <!-- 接入差异说明 -->
    <section class="panel">
      <div class="panel-title"><span>接入一台新设备需要什么</span></div>
      <table class="grid">
        <thead><tr><th style="width: 200px">协议</th><th style="width: 150px">适用本体</th><th style="width: 100px">状态</th><th>还缺什么</th></tr></thead>
        <tbody>
          <tr v-for="(m, key) in meta.adapters" :key="key">
            <td>{{ m.label }}</td>
            <td class="dim">{{ meta.device_types.find((t) => t.value === m.device_type)?.label ?? m.device_type }}</td>
            <td><span class="tag" :class="m.supported ? 'ok' : 'warn'">{{ m.supported ? '可用' : '待接入' }}</span></td>
            <td class="dim">{{ m.supported ? m.note : (m.needs.join('、') || m.note) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 新增 -->
    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal">
        <div class="panel-title"><span>新增设备</span><span class="req-legend">带 * 为必填</span></div>
        <label class="fld"><span>设备名称<i class="req">*</i></span><input class="input" :class="{ missing: tried && !form.name.trim() }" v-model="form.name" placeholder="如 X30-巡检狗" /></label>
        <label class="fld">
          <span>本体类型</span>
          <DarkSelect v-model="form.device_type" :options="deviceTypeOptions" width="100%" @update:model-value="form.adapter = adapterOptions[0]?.value ?? form.adapter" />
        </label>
        <label class="fld">
          <span>通信协议</span>
          <DarkSelect v-model="form.adapter" :options="adapterOptions" width="100%" />
        </label>
        <p v-if="currentAdapter && !currentAdapter.supported" class="warn small">
          该协议适配器还没实现，只能登记台账。缺：{{ currentAdapter.needs.join('、') }}
        </p>
        <label class="fld"><span>场站</span><input class="input" v-model="form.station" /></label>
        <div class="two">
          <label class="fld"><span>IP / 主机<i class="req">*</i></span><input class="input" :class="{ missing: tried && !form.ip.trim() }" v-model="form.ip" placeholder="192.168.1.105" /></label>
          <label class="fld"><span>端口<i class="req">*</i></span><input class="input" type="number" v-model.number="form.port" /></label>
        </div>
        <div class="two">
          <label class="fld"><span>账号</span><input class="input" v-model="form.username" /></label>
          <label class="fld"><span>密码</span><input class="input" type="password" v-model="form.password" placeholder="留空表示用服务端默认" /></label>
        </div>
        <label class="fld"><span>备注</span><input class="input" v-model="form.note" /></label>
        <div class="modal-actions">
          <button class="btn btn-sm" @click="creating = false">取消</button>
          <button class="btn btn-sm primary" :disabled="!form.name.trim() || !form.ip.trim()" @click="submitCreate">保存</button>
        </div>
      </div>
    </div>

    <!-- 编辑 -->
    <div v-if="editing" class="modal-mask" @click.self="editing = null">
      <div class="modal">
        <div class="panel-title"><span>编辑 · {{ editing.name }}</span><span class="req-legend">带 * 为必填</span></div>
        <label class="fld"><span>设备名称</span><input class="input" v-model="form.name" /></label>
        <label class="fld"><span>本体类型</span><DarkSelect v-model="form.device_type" :options="deviceTypeOptions" width="100%" /></label>
        <label class="fld"><span>通信协议</span><DarkSelect v-model="form.adapter" :options="adapterOptions" width="100%" /></label>
        <label class="fld"><span>场站</span><input class="input" v-model="form.station" /></label>
        <div class="two">
          <label class="fld"><span>IP / 主机</span><input class="input" v-model="form.ip" /></label>
          <label class="fld"><span>端口<i class="req">*</i></span><input class="input" type="number" v-model.number="form.port" /></label>
        </div>
        <div class="two">
          <label class="fld"><span>账号</span><input class="input" v-model="form.username" /></label>
          <label class="fld"><span>密码</span><input class="input" type="password" v-model="form.password" placeholder="留空不改" /></label>
        </div>
        <label class="fld"><span>备注</span><input class="input" v-model="form.note" /></label>
        <div class="modal-actions">
          <button class="btn btn-sm" @click="editing = null">取消</button>
          <button class="btn btn-sm primary" @click="submitEdit">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.small { font-size: 12px; line-height: 1.8; }
.num { font-variant-numeric: tabular-nums; }
.warn { color: #ffe08a; }
.modal-mask {
  position: fixed; inset: 0; z-index: 120;
  display: grid; place-items: center;
  background: rgba(2, 14, 30, 0.66);
}
.modal {
  width: 540px; max-height: 88vh; overflow: auto;
  padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
  box-shadow: 0 0 30px rgba(0, 60, 140, 0.7);
}
.fld { display: block; margin-bottom: 12px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; }
.two { display: grid; grid-template-columns: 1fr 120px; gap: 10px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
</style>
