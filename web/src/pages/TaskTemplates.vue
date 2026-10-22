<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type LibraryMap, type PointDraft } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

interface TemplateRow {
  id: number
  name: string
  map_id: number | null
  loop: boolean
  note: string | null
  actions: { point_id: number; action: string; params: Record<string, unknown> }[]
  action_count: number
  summary: string
  created_at: string | null
}

const auth = useAuthStore()
const rows = ref<TemplateRow[]>([])
const maps = ref<LibraryMap[]>([])
const points = ref<PointDraft[]>([])
const actionTypes = ref<{ value: string; label: string }[]>([])
const loading = ref(false)

const editing = ref<TemplateRow | null>(null)
const creating = ref(false)
const form = ref({
  name: '', mapId: '', loop: false, note: '',
})
/** point_id -> action（勾选即加入，取消即移除） */
const picked = ref<Record<number, string>>({})

const mapOptions = computed(() => maps.value.map((m) => ({ value: String(m.id), label: `${m.name}（${m.floor}）` })))
const actionOptions = computed(() => actionTypes.value)
const pickedCount = computed(() => Object.keys(picked.value).length)

async function load() {
  loading.value = true
  try {
    rows.value = (await api.taskTemplates()) as unknown as TemplateRow[]
  } finally {
    loading.value = false
  }
}

async function loadMapPoints(mapId: string) {
  if (!mapId) { points.value = []; return }
  try {
    points.value = await api.libraryPoints(Number(mapId))
  } catch {
    points.value = []
  }
}

function openCreate() {
  form.value = { name: '', mapId: maps.value[0] ? String(maps.value[0].id) : '', loop: false, note: '' }
  picked.value = {}
  creating.value = true
  void loadMapPoints(form.value.mapId)
}

function openEdit(t: TemplateRow) {
  form.value = { name: t.name, mapId: t.map_id ? String(t.map_id) : '', loop: t.loop, note: t.note ?? '' }
  picked.value = {}
  for (const a of t.actions) picked.value[a.point_id] = a.action
  editing.value = t
  void loadMapPoints(form.value.mapId)
}

function togglePoint(id: number) {
  if (picked.value[id]) {
    const next = { ...picked.value }
    delete next[id]
    picked.value = next
  } else {
    picked.value = { ...picked.value, [id]: 'photo' }
  }
}

function setAction(id: number, action: string) {
  picked.value = { ...picked.value, [id]: action }
}

function payload() {
  return {
    name: form.value.name.trim(),
    map_id: form.value.mapId ? Number(form.value.mapId) : null,
    loop: form.value.loop,
    note: form.value.note || null,
    actions: Object.entries(picked.value).map(([pid, action]) => ({
      point_id: Number(pid), action, params: {},
    })),
  }
}

async function submit() {
  if (!form.value.name.trim()) return toast('模板名称必填', 'warn')
  if (!pickedCount.value) return toast('至少勾选一个点位', 'warn')
  try {
    if (editing.value) {
      await api.updateTaskTemplate(editing.value.id, payload())
      toast('模板已保存', 'ok')
      editing.value = null
    } else {
      await api.createTaskTemplate(payload())
      toast('模板已创建（还不能下发，等真机联调）', 'ok', 4000)
      creating.value = false
    }
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '保存失败', 'danger')
  }
}

async function remove(t: TemplateRow) {
  if (!window.confirm(`删除模板「${t.name}」？`)) return
  await api.deleteTaskTemplate(t.id)
  toast('已删除', 'ok')
  await load()
}

function dispatchTip(t: TemplateRow) {
  return '下发需要机器人写权限：等真机联调 + 现场授权后开放'
}

onMounted(async () => {
  try {
    maps.value = await api.libraryMaps()
  } catch { /* 没有地图也能看列表 */ }
  try {
    actionTypes.value = (await api.taskTemplateMeta()).actions
  } catch {
    actionTypes.value = [{ value: 'photo', label: '拍照' }]
  }
  await load()
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>任务模板</span>
        <span class="muted small">先把"走哪几个点、每个点做什么"配好；真机到场一键下发</span>
        <span class="grow" />
        <button class="btn btn-sm primary" :disabled="!auth.canWrite || !maps.length" @click="openCreate">新建模板</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 160px">名称</th>
            <th>动作序列</th>
            <th style="width: 80px">点数</th>
            <th style="width: 80px">循环</th>
            <th style="width: 190px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in rows" :key="t.id">
            <td>{{ t.id }}</td>
            <td>{{ t.name }}</td>
            <td class="dim small">{{ t.summary || '—' }}</td>
            <td class="num">{{ t.action_count }}</td>
            <td><span class="tag" :class="t.loop ? 'ok' : ''">{{ t.loop ? '循环' : '单次' }}</span></td>
            <td>
              <div class="row-actions">
                <button class="btn btn-xs" disabled :title="dispatchTip(t)">下发</button>
                <button class="act" title="编辑" :disabled="!auth.canWrite" @click="openEdit(t)">✎</button>
                <button class="act danger" title="删除" :disabled="!auth.canWrite" @click="remove(t)">🗑</button>
              </div>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="6" class="dim">
              {{ loading ? '读取中…' : maps.length ? '还没有模板。选一张平台地图，把点位串成一条巡检路线。' : '先去「地图监控 → 平台地图库」导入一张地图，再回来建模板。' }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 新建/编辑 -->
    <div v-if="creating || editing" class="modal-mask" @click.self="creating = false; editing = null">
      <div class="modal">
        <div class="panel-title"><span>{{ editing ? '编辑模板 · ' + editing.name : '新建任务模板' }}</span></div>

        <div class="two">
          <label class="fld"><span>模板名称<i class="req">*</i></span><input class="input" v-model="form.name" placeholder="夜间巡检-A" /></label>
          <label class="fld">
            <span>地图</span>
            <DarkSelect v-model="form.mapId" :options="mapOptions" width="100%" @update:model-value="picked = {}; loadMapPoints(form.mapId)" />
          </label>
        </div>

        <div class="fld">
          <span>点位与动作（勾选即加入）<i class="req">*</i></span>
          <div class="points">
            <div v-for="p in points" :key="p.id" class="prow" :class="{ on: picked[p.id] }">
              <label class="chk">
                <input type="checkbox" :checked="!!picked[p.id]" @change="togglePoint(p.id)" />
                <span>{{ p.name }}</span>
                <em class="dim">{{ p.group || '默认分组' }} · {{ p.x.toFixed(1) }},{{ p.y.toFixed(1) }}</em>
              </label>
              <DarkSelect
                v-if="picked[p.id]"
                :model-value="picked[p.id]"
                :options="actionOptions"
                width="130px"
                @update:model-value="setAction(p.id, $event)"
              />
            </div>
            <p v-if="!points.length" class="dim small">这张图还没有点位，先去地图页打点或导入 CSV。</p>
          </div>
        </div>

        <div class="two">
          <label class="chk"><input type="checkbox" v-model="form.loop" /> 循环执行</label>
          <label class="fld"><span>备注</span><input class="input" v-model="form.note" /></label>
        </div>

        <p class="muted small">
          已选 <b>{{ pickedCount }}</b> 个点位。模板只存在平台侧，<b>不会下发</b>到机器人——
          下发要等真机联调 + 现场授权。
        </p>

        <div class="modal-actions">
          <button class="btn" @click="creating = false; editing = null">取消</button>
          <button class="btn primary" @click="submit">保存</button>
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
.modal-mask { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 14, 30, 0.66); }
.modal {
  width: 640px; max-height: 90vh; overflow: auto; padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
}
.fld { display: block; margin-bottom: 11px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.points {
  max-height: 280px; overflow: auto; border: 1px solid rgba(111, 227, 255, 0.2);
  border-radius: 4px; padding: 6px;
}
.prow {
  display: flex; align-items: center; gap: 8px; justify-content: space-between;
  padding: 4px 6px; border-radius: 4px;
}
.prow.on { background: rgba(41, 212, 255, 0.12); }
.chk { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: #dceeff; }
.chk em { font-style: normal; font-size: 11px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
