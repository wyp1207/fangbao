<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, type SensorItem, type SensorKind } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const rows = ref<SensorItem[]>([])
const kinds = ref<SensorKind[]>([])
const loading = ref(false)

const editing = ref<SensorItem | null>(null)
const creating = ref(false)
const form = ref({
  name: '', kind: 'gas', station: '默认场站', location: '', serial: '',
  warn_high: '' as string | number, crit_high: '' as string | number,
  warn_low: '' as string | number, crit_low: '' as string | number,
  note: '',
})

// 加读数
const reading = ref<SensorItem | null>(null)
const readingValue = ref<string>('')

const kindOptions = computed(() => kinds.value.map((k) => ({ value: k.value, label: k.label })))
const unitOf = (kind: string) => kinds.value.find((k) => k.value === kind)?.unit ?? ''

async function load() {
  loading.value = true
  try {
    rows.value = await api.sensors()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '读取失败', 'danger')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { name: '', kind: 'gas', station: '默认场站', location: '', serial: '',
                 warn_high: '', crit_high: '', warn_low: '', crit_low: '', note: '' }
  creating.value = true
}

function openEdit(s: SensorItem) {
  form.value = {
    name: s.name, kind: s.kind, station: s.station, location: s.location ?? '',
    serial: s.serial ?? '', warn_high: s.warn_high ?? '', crit_high: s.crit_high ?? '',
    warn_low: s.warn_low ?? '', crit_low: s.crit_low ?? '', note: s.note ?? '',
  }
  editing.value = s
}

function payload() {
  const num = (v: string | number) => (v === '' || v === null ? null : Number(v))
  return {
    name: form.value.name.trim(), kind: form.value.kind, station: form.value.station,
    location: form.value.location || null, serial: form.value.serial || null,
    warn_high: num(form.value.warn_high), crit_high: num(form.value.crit_high),
    warn_low: num(form.value.warn_low), crit_low: num(form.value.crit_low),
    note: form.value.note || null,
  }
}

async function submitCreate() {
  if (!form.value.name.trim()) { toast('传感器名称必填', 'warn'); return }
  try {
    await api.createSensor(payload())
    toast('已添加，记得标定阈值后才会告警', 'ok', 3500)
    creating.value = false
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '添加失败', 'danger')
  }
}

async function submitEdit() {
  if (!editing.value) return
  try {
    await api.updateSensor(editing.value.id, payload())
    toast('已保存', 'ok')
    editing.value = null
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '保存失败', 'danger')
  }
}

async function remove(s: SensorItem) {
  if (!window.confirm(`删除传感器「${s.name}」？读数一并删除。`)) return
  try {
    await api.deleteSensor(s.id)
    toast('已删除', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '删除失败', 'danger')
  }
}

function openReading(s: SensorItem) {
  reading.value = s
  readingValue.value = ''
}

async function submitReading() {
  if (!reading.value || readingValue.value === '') return
  try {
    const res = await api.addSensorReading(reading.value.id, Number(readingValue.value))
    toast(res.raised ? `已触发告警：${res.message}` : '读数已记录', res.raised ? 'warn' : 'ok', 3500)
    reading.value = null
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '记录失败', 'danger')
  }
}

let timer = 0
onMounted(async () => {
  try { kinds.value = (await api.sensorMeta()).kinds } catch { /* 下拉兜底 */ }
  await load()
  timer = window.setInterval(load, 15000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>环境传感器</span>
        <span class="muted small">阈值留空 = 未标定，只记录不告警；标定后超限自动进告警中心</span>
      </div>

      <div class="toolbar">
        <span class="grow" />
        <button class="btn btn-sm" :disabled="loading" @click="load">刷新</button>
        <button class="btn btn-sm primary" :disabled="!auth.canWrite" @click="openCreate">新增传感器</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 160px">名称</th>
            <th style="width: 110px">类型</th>
            <th style="width: 120px">位置</th>
            <th style="width: 130px">最新读数</th>
            <th style="width: 200px">阈值（提醒 / 严重）</th>
            <th style="width: 110px">标定</th>
            <th style="width: 150px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in rows" :key="s.id">
            <td>{{ s.id }}</td>
            <td>{{ s.name }}</td>
            <td class="dim">{{ s.kind_label }}</td>
            <td class="dim">{{ s.location || '—' }}</td>
            <td class="num">
              <b v-if="s.latest">{{ s.latest.value }} <span class="dim">{{ s.unit }}</span></b>
              <span v-else class="dim">无数据</span>
            </td>
            <td class="num dim">
              {{ s.warn_low ?? '—' }} ~ {{ s.warn_high ?? '—' }} /
              {{ s.crit_low ?? '—' }} ~ {{ s.crit_high ?? '—' }}
            </td>
            <td>
              <span class="tag" :class="s.calibrated ? 'ok' : 'warn'">{{ s.calibrated ? '已标定' : '未标定' }}</span>
            </td>
            <td>
              <div class="row-actions">
                <button class="act" title="录入一条读数" :disabled="!auth.canWrite" @click="openReading(s)">＋</button>
                <button class="act" title="编辑/标定" :disabled="!auth.canWrite" @click="openEdit(s)">✎</button>
                <button class="act danger" title="删除" :disabled="!auth.canWrite" @click="remove(s)">🗑</button>
              </div>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="8" class="dim">
              {{ loading ? '读取中…' : '还没有传感器。可燃气体/温湿度/烟雾等接上后在这里登记，填阈值才会告警。' }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 新增/编辑 -->
    <div v-if="creating || editing" class="modal-mask" @click.self="creating = false; editing = null">
      <div class="modal">
        <div class="panel-title"><span>{{ editing ? '编辑传感器 · ' + editing.name : '新增传感器' }}</span></div>
        <div class="two">
          <label class="fld"><span>名称</span><input class="input" v-model="form.name" placeholder="可燃气体-泵房" /></label>
          <label class="fld">
            <span>类型</span>
            <DarkSelect v-model="form.kind" :options="kindOptions" width="100%" :disabled="!!editing" />
          </label>
        </div>
        <div class="two">
          <label class="fld"><span>场站</span><input class="input" v-model="form.station" /></label>
          <label class="fld"><span>安装位置</span><input class="input" v-model="form.location" placeholder="泵房东侧 1.5m" /></label>
        </div>
        <label class="fld"><span>出厂编号</span><input class="input" v-model="form.serial" /></label>

        <div class="th-head">
          阈值（{{ unitOf(form.kind) }}）
          <span class="muted small">留空 = 未标定，不告警</span>
        </div>
        <div class="four">
          <label class="fld"><span>提醒下限</span><input class="input" v-model="form.warn_low" /></label>
          <label class="fld"><span>提醒上限</span><input class="input" v-model="form.warn_high" /></label>
          <label class="fld"><span>严重下限</span><input class="input" v-model="form.crit_low" /></label>
          <label class="fld"><span>严重上限</span><input class="input" v-model="form.crit_high" /></label>
        </div>
        <label class="fld"><span>备注</span><input class="input" v-model="form.note" placeholder="检定证书编号 / 标定人 / 日期" /></label>

        <div class="modal-actions">
          <button class="btn" @click="creating = false; editing = null">取消</button>
          <button v-if="!editing" class="btn primary" @click="submitCreate">保存</button>
          <button v-else class="btn primary" @click="submitEdit">保存</button>
        </div>
      </div>
    </div>

    <!-- 录入读数 -->
    <div v-if="reading" class="modal-mask" @click.self="reading = null">
      <div class="modal narrow">
        <div class="panel-title"><span>{{ reading.name }} · 录入读数</span></div>
        <label class="fld">
          <span>读数（{{ reading.unit }}）</span>
          <input class="input big" type="number" step="0.1" v-model="readingValue" @keyup.enter="submitReading" autofocus />
        </label>
        <p class="muted small">
          现在是手填。真机环境模块或采集网关接上后，改成自动写入同一个接口，页面不用改。
        </p>
        <div class="modal-actions">
          <button class="btn" @click="reading = null">取消</button>
          <button class="btn primary" :disabled="readingValue === ''" @click="submitReading">记录</button>
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
.modal-mask { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 14, 30, 0.66); }
.modal {
  width: 600px; max-height: 90vh; overflow: auto; padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
}
.modal.narrow { width: 420px; }
.fld { display: block; margin-bottom: 11px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; }
.input.big { font-size: 20px; padding: 10px; text-align: center; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.four { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.th-head {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: #ffe08a; margin: 4px 0 8px;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
</style>
