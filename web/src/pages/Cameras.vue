<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, type VideoRow } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'

const route = useRoute()
const highlightId = ref<number>(Number(route?.query?.v ?? 0) || 0)
const rows = ref<VideoRow[]>([])
const devices = ref<{ id: number; name: string }[]>([])
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const groupFilter = ref('')

const editing = ref<VideoRow | null>(null)
const tried = ref(false)
const creating = ref(false)
const testing = ref<number | null>(null)

const vendors = [
  { value: 'hikvision', label: '海康' },
  { value: 'dahua', label: '大华' },
  { value: 'other', label: '其他' },
]
const vendorText: Record<string, string> = { hikvision: '海康', dahua: '大华', other: '其他' }

const form = ref({
  name: '', group_name: '默认分组', vendor: 'hikvision', url: '', note: '',
  enabled: true, stream_name: '', robot_id: '' as string, dashboard_role: 'none',
})
const dashRoles = [
  { value: 'none', label: '不上大屏' },
  { value: 'visible', label: '可见光主画面' },
  { value: 'thermal', label: '热红外画面' },
]
const deviceOptions = computed(() => [
  { value: '', label: '不绑定设备' },
  ...devices.value.map((d) => ({ value: String(d.id), label: d.name })),
])

const groups = computed(() => {
  const set = new Set(rows.value.map((r) => r.group_name))
  return [{ value: '', label: '全部' }, ...[...set].map((g) => ({ value: g, label: g }))]
})

const filtered = computed(() =>
  rows.value.filter((r) => {
    if (keyword.value && !r.name.includes(keyword.value)) return false
    if (groupFilter.value && r.group_name !== groupFilter.value) return false
    return true
  }),
)

const deviceName = computed(() => Object.fromEntries(devices.value.map((d) => [d.id, d.name])))
function deviceText(id?: number | null): string {
  return (id && deviceName.value[id]) || '未绑定'
}

async function loadDevices() {
  try {
    devices.value = (await api.devices()).map((d) => ({ id: d.id, name: d.name }))
  } catch {
    devices.value = []
  }
}

async function reload() {
  loading.value = true
  error.value = ''
  try {
    rows.value = await api.videos()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : '视频源读取失败'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = {
    name: '', group_name: '默认分组', vendor: 'hikvision', url: '', note: '',
    enabled: true, stream_name: '', robot_id: '', dashboard_role: 'none',
  }
  creating.value = true
}

function openEdit(v: VideoRow) {
  form.value = {
    name: v.name, group_name: v.group_name, vendor: v.vendor,
    url: v.url, note: v.note ?? '', enabled: v.enabled, stream_name: v.stream_name,
    robot_id: v.robot_id ? String(v.robot_id) : '',
    dashboard_role: v.dashboard_role || 'none',
  }
  editing.value = v
}

async function submitCreate() {
  tried.value = true
  if (!form.value.name.trim() || !form.value.url.trim()) {
    toast('名称和视频流地址必填', 'warn')
    return
  }
  try {
    await api.createVideo({
      name: form.value.name,
      group_name: form.value.group_name,
      vendor: form.value.vendor,
      url: form.value.url,
      note: form.value.note || null,
      enabled: form.value.enabled,
      stream_name: form.value.stream_name,
      robot_id: form.value.robot_id ? Number(form.value.robot_id) : null,
      dashboard_role: form.value.dashboard_role,
    })
    toast(`已添加视频源 ${form.value.name}`, 'ok')
    creating.value = false
    await reload()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '添加失败', 'danger')
  }
}

async function submitEdit() {
  if (!editing.value) return
  try {
    await api.updateVideo(editing.value.id, {
      name: form.value.name, group_name: form.value.group_name,
      vendor: form.value.vendor, url: form.value.url,
      note: form.value.note || null, enabled: form.value.enabled, stream_name: form.value.stream_name,
      robot_id: form.value.robot_id ? Number(form.value.robot_id) : null,
      dashboard_role: form.value.dashboard_role,
    })
    toast('已保存（密码不变则保留原值）', 'ok')
    editing.value = null
    await reload()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '保存失败', 'danger')
  }
}

async function test(v: VideoRow) {
  testing.value = v.id
  try {
    const res = await api.testVideo(v.id)
    toast(`${res.target}：${res.message}`, res.ok ? 'ok' : 'danger', 3200)
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '测试失败', 'danger')
  } finally {
    testing.value = null
  }
}

async function toggle(v: VideoRow) {
  try {
    await api.updateVideo(v.id, { enabled: !v.enabled })
    await reload()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '操作失败', 'danger')
  }
}

async function setRole(v: VideoRow, role: string) {
  try {
    await api.updateVideo(v.id, { dashboard_role: role })
    toast(role === 'none' ? '已移出首页' : role === 'thermal' ? '已设为热红外画面' : '已设为可见光主画面', 'ok')
    await reload()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '设置失败', 'danger')
  }
}

async function remove(v: VideoRow) {
  if (!window.confirm(`确定删除视频源「${v.name}」？`)) return
  try {
    await api.deleteVideo(v.id)
    toast('已删除', 'ok')
    await reload()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '删除失败', 'danger')
  }
}

async function reset() {
  keyword.value = ''
  groupFilter.value = ''
  // 清完筛选重新查一次，否则默认态下点「重置」没有任何可见变化
  await reload()
  toast('已重置', 'ok', 2000)
}

onMounted(() => { void reload(); void loadDevices() })
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>摄像头 / 视频流</span>
        <span class="muted">地址里的密码只存在服务端，列表里一律打码</span>
      </div>

      <div class="toolbar">
        <label>分组</label>
        <DarkSelect v-model="groupFilter" :options="groups" width="150px" />
        <label>名称</label>
        <input class="input" v-model="keyword" placeholder="输入摄像头名称" />
        <button type="button" class="btn btn-sm ok" :disabled="loading" @click="reload">查询</button>
        <button type="button" class="btn btn-sm warn" @click="reset">重置</button>
        <span class="grow" />
        <button type="button" class="btn btn-sm" @click="reload">刷新</button>
        <button type="button" class="btn btn-sm primary" @click="openCreate">新增视频源</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 180px">名称</th>
            <th style="width: 130px">分组</th>
            <th style="width: 140px">设备</th>
            <th style="width: 90px">厂商</th>
            <th>视频流地址</th>
            <th style="width: 90px">启用</th>
            <th style="width: 150px">大屏位置</th>
            <th style="width: 170px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="v in filtered" :key="v.id" :class="{ hl: v.id === highlightId }">
            <td>{{ v.id }}</td>
            <td>{{ v.name }}</td>
            <td class="dim">{{ v.group_name }}</td>
            <td class="dim">{{ deviceText(v.robot_id) }}</td>
            <td><span class="tag" :class="v.vendor === 'other' ? '' : 'ok'">{{ vendorText[v.vendor] }}</span></td>
            <td class="mono url">{{ v.url }}</td>
            <td><span class="tag" :class="v.enabled ? 'ok' : 'danger'">{{ v.enabled ? '启用' : '停用' }}</span></td>
            <td>
              <DarkSelect :model-value="v.dashboard_role || 'none'" :options="dashRoles" width="150px"
                          @update:model-value="(role: string) => setRole(v, role)" />
            </td>
            <td>
              <div class="row-actions">
                <button type="button" class="act" title="预览画面" @click="$router.push({ name: 'video', query: { source: String(v.id) } })">▶</button>
                <button type="button" class="act" title="编辑" @click="openEdit(v)">✎</button>
                <button type="button" class="act" title="测试连通性" :disabled="testing === v.id" @click="test(v)">⇄</button>
                <button type="button" class="act" :title="v.enabled ? '停用' : '启用'" @click="toggle(v)">{{ v.enabled ? '⏸' : '▶' }}</button>
                <button type="button" class="act danger" title="删除" @click="remove(v)">🗑</button>
              </div>
            </td>
          </tr>
          <tr v-if="!filtered.length">
            <td colspan="9" class="dim">{{ loading ? '读取中…' : '还没有视频源，点右上角新增' }}</td>
          </tr>
        </tbody>
      </table>

      <p v-if="error" class="danger small">{{ error }}</p>
      <p class="muted small">
        浏览器放不了 RTSP。要在页面上直接看画面，需要在部署机上起一个转流服务（MediaMTX / ffmpeg），
        由它把 RTSP 转成 HLS/WebRTC；「测试」按钮只验证 host:port 能不能连通，不验证账号密码。
      </p>
    </section>

    <!-- 新增 -->
    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal">
        <div class="panel-title"><span>新增视频源</span><span class="req-legend">带 * 为必填</span></div>
        <label class="fld"><span>名称<i class="req">*</i></span><input class="input" :class="{ missing: tried && !form.name.trim() }" v-model="form.name" placeholder="如：充电房-可见光" /></label>
        <label class="fld"><span>分组</span><input class="input" v-model="form.group_name" placeholder="如：充电房 / 机器人本体" /></label>
        <label class="fld"><span>归属设备</span><DarkSelect v-model="form.robot_id" :options="deviceOptions" width="260px" /></label>
        <label class="fld"><span>大屏位置</span><DarkSelect v-model="form.dashboard_role" :options="dashRoles" width="200px" /></label>
        <label class="fld"><span>厂商</span><DarkSelect v-model="form.vendor" :options="vendors" width="180px" /></label>
        <label class="fld">
          <span>视频流地址<i class="req">*</i></span>
          <input class="input" v-model="form.url" placeholder="rtsp://user:password@host:554/..." />
        </label>
        <label class="fld"><span>备注（可选）</span><input class="input" v-model="form.note" /></label>
        <div class="modal-actions">
          <button type="button" class="btn btn-sm" @click="creating = false">取消</button>
          <button type="button" class="btn btn-sm primary" @click="submitCreate">保存</button>
        </div>
      </div>
    </div>

    <!-- 编辑 -->
    <div v-if="editing" class="modal-mask" @click.self="editing = null">
      <div class="modal">
        <div class="panel-title"><span>编辑 · {{ editing.name }}</span></div>
        <label class="fld"><span>名称</span><input class="input" v-model="form.name" /></label>
        <label class="fld"><span>分组</span><input class="input" v-model="form.group_name" /></label>
        <label class="fld"><span>归属设备</span><DarkSelect v-model="form.robot_id" :options="deviceOptions" width="260px" /></label>
        <label class="fld"><span>大屏位置</span><DarkSelect v-model="form.dashboard_role" :options="dashRoles" width="200px" /></label>
        <label class="fld"><span>厂商</span><DarkSelect v-model="form.vendor" :options="vendors" width="180px" /></label>
        <label class="fld">
          <span>视频流地址<i class="req">*</i></span>
          <input class="input" v-model="form.url" />
          <em class="hint">密码显示为 ***，原样提交即保留原密码</em>
        </label>
        <div class="modal-actions">
          <button type="button" class="btn btn-sm" @click="editing = null">取消</button>
          <button type="button" class="btn btn-sm primary" @click="submitEdit">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.small { font-size: 12px; line-height: 1.8; }
.url { font-size: 12px; color: #bcdcff; word-break: break-all; }
tr.hl td { background: rgba(41, 212, 255, 0.22) !important; }
.mono { font-family: ui-monospace, Consolas, monospace; }
.modal-mask {
  position: fixed; inset: 0; z-index: 120;
  display: grid; place-items: center;
  background: rgba(2, 14, 30, 0.66);
}
.modal {
  width: 520px; max-height: 86vh; overflow: auto;
  padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
  box-shadow: 0 0 30px rgba(0, 60, 140, 0.7);
}
.fld { display: block; margin-bottom: 12px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; }
.hint { display: block; margin-top: 4px; font-size: 11px; color: #8fc4f0; font-style: normal; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.row { display: flex; align-items: center; gap: 8px; }
</style>
