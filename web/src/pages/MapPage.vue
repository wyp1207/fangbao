<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import MapCanvas from '@/components/MapCanvas.vue'
import DarkSelect from '@/components/DarkSelect.vue'
import { api, type LibraryMap, type MapMeta, type NavPoint, type PointDraft } from '@/api'
import { ApiError } from '@/api/client'
import { toast } from '@/composables/useToast'
import { useRobotStore } from '@/stores/robot'

const robot = useRobotStore()
const route = useRoute()

const robotMaps = ref<MapMeta[]>([])
const library = ref<LibraryMap[]>([])
/** 当前查看的是平台库地图时，这里非空 */
const libId = ref(0)
const points = ref<NavPoint[]>([])
const drafts = ref<PointDraft[]>([])
const selectedPoint = ref<NavPoint | null>(null)
const error = ref('')

// 打点模式
const picking = ref(false)
const pickAt = ref<{ x: number; y: number } | null>(null)
const draftName = ref('')
const draftNote = ref('')

// 导入地图
const importing = ref(false)
const impForm = ref({
  name: '', floor: '1F', station: '默认场站', resolution: 0.05,
  origin_x: 0, origin_y: 0, origin_theta: 0, robot_map_name: '', note: '',
})
const impFile = ref<File | null>(null)
const impBusy = ref(false)

const libMap = computed(() => library.value.find((m) => m.id === libId.value) ?? null)
const robotMap = computed(() => robotMaps.value.find((m) => m.name === selectedName.value) ?? null)
const selectedName = ref('')

const meta = computed<MapMeta | null>(() => {
  if (libMap.value) {
    const m = libMap.value
    return {
      name: m.name,
      resolution: m.resolution,
      origin: m.origin,
      width: m.width,
      height: m.height,
      slam_type: '平台导入',
    } as unknown as MapMeta
  }
  return robotMap.value
})

const imageUrl = computed(() => {
  if (libMap.value) return api.libraryImageUrl(libMap.value.id)
  return selectedName.value ? api.mapPng(1, selectedName.value) : ''
})

const pointRows = computed(() => [
  ...drafts.value.map((d) => ({ key: `d${d.id}`, name: d.name, x: d.x, y: d.y, draft: true, id: d.id })),
  ...points.value.map((p, i) => ({ key: `r${i}`, name: p.name || `点位 ${String(i + 1).padStart(2, '0')}`, x: p.x, y: p.y, draft: false, id: i })),
])

async function loadDrafts(mapId: number) {
  drafts.value = mapId ? await api.libraryPoints(mapId) : []
}

async function loadRobotPoints(name: string) {
  error.value = ''
  try {
    const raw = await api.navPoints(1, name, '')
    points.value = raw.points
  } catch (e) {
    error.value = e instanceof Error ? e.message : '点位加载失败'
  }
}

async function chooseRobot(name: string) {
  libId.value = 0
  selectedName.value = name
  drafts.value = []
  await loadRobotPoints(name)
}

async function chooseLib(id: number) {
  libId.value = id
  selectedName.value = ''
  points.value = []
  await loadDrafts(id)
}

async function refreshLibrary() {
  library.value = await api.libraryMaps()
}

function openImport() {
  impForm.value = { name: '', floor: '1F', station: '默认场站', resolution: 0.05,
                    origin_x: 0, origin_y: 0, origin_theta: 0, robot_map_name: '', note: '' }
  impFile.value = null
  importing.value = true
}

function onFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0] ?? null
  impFile.value = f
  if (f && !impForm.value.name) impForm.value.name = f.name.replace(/\.[^.]+$/, '')
}

async function submitImport() {
  if (!impFile.value) { toast('请选择 PNG/JPG 图纸', 'warn'); return }
  if (!impForm.value.name) { toast('地图名称必填', 'warn'); return }
  impBusy.value = true
  try {
    const fd = new FormData()
    fd.append('file', impFile.value)
    for (const [k, v] of Object.entries(impForm.value)) fd.append(k, String(v))
    const m = await api.importLibraryMap(fd)
    toast(`已导入「${m.name}」（${m.width}×${m.height}）`, 'ok')
    importing.value = false
    await refreshLibrary()
    await chooseLib(m.id)
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '导入失败', 'danger')
  } finally {
    impBusy.value = false
  }
}

function startPick() {
  if (!libId.value) { toast('只有平台导入的地图才能打点', 'warn'); return }
  picking.value = true
  toast('在地图上点一下要放点位的位置', 'ok', 2500)
}

function onPick(w: { x: number; y: number }) {
  if (!picking.value) return
  pickAt.value = w
  draftName.value = `点位 ${pointRows.value.length + 1}`
  draftNote.value = ''
}

async function saveDraft() {
  if (!pickAt.value || !draftName.value) return
  try {
    await api.addLibraryPoint(libId.value, {
      name: draftName.value, x: Number(pickAt.value.x.toFixed(2)),
      y: Number(pickAt.value.y.toFixed(2)), note: draftNote.value || null,
    })
    toast('已存为草稿（待同步到机器人）', 'ok')
    pickAt.value = null
    picking.value = false
    await loadDrafts(libId.value)
    await refreshLibrary()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '保存失败', 'danger')
  }
}

async function removeDraft(id: number) {
  if (!window.confirm('删除这个草稿点位？')) return
  await api.deleteLibraryPoint(id)
  await loadDrafts(libId.value)
  await refreshLibrary()
}

onMounted(async () => {
  robot.start()
  robotMaps.value = await api.maps()
  await refreshLibrary()
  const wantMap = route.query.map
  const wantLib = Number(route.query.lib ?? 0)
  if (wantLib) await chooseLib(wantLib)
  else if (typeof wantMap === 'string' && wantMap) await chooseRobot(wantMap)
  else if (robotMaps.value.length) await chooseRobot(robotMaps.value[0].name)
  else if (library.value.length) await chooseLib(library.value[0].id)
})
</script>

<template>
  <div class="page">
    <aside class="panel side">
      <div class="panel-title">
        <span>机器人地图</span>
        <span class="muted small">{{ robotMaps.length }}</span>
      </div>
      <button
        v-for="m in robotMaps" :key="m.name" class="map-item"
        :class="{ active: !libId && m.name === selectedName }"
        @click="chooseRobot(m.name)"
      >
        <span>{{ m.name }}</span>
        <span class="muted small">{{ m.slam_type }} · {{ m.resolution?.toFixed(3) }} m/px</span>
      </button>
      <p v-if="!robotMaps.length" class="muted small">机器人暂无地图（真机 /navigation/saved_maps 有数据后出现）</p>

      <div class="panel-title" style="margin-top: 14px">
        <span>平台地图库</span>
        <button class="btn btn-xs" @click="openImport">导入</button>
      </div>
      <button
        v-for="m in library" :key="m.id" class="map-item"
        :class="{ active: m.id === libId }"
        @click="chooseLib(m.id)"
      >
        <span>{{ m.name }}</span>
        <span class="muted small">{{ m.floor }} · {{ m.draft_points }} 草稿</span>
      </button>
      <p v-if="!library.length" class="muted small">还没有导入过地图。换场地时把客户图纸导进来。</p>

      <div class="panel-title" style="margin-top: 14px">点位（{{ pointRows.length }}）</div>
      <ul class="points">
        <li v-for="p in pointRows" :key="p.key">
          <span :class="{ draft: p.draft }">{{ p.draft ? '草' : '机' }}</span>
          <span>{{ p.name }}</span>
          <span class="muted mono">{{ p.x.toFixed(1) }}, {{ p.y.toFixed(1) }}</span>
          <button v-if="p.draft" class="del" title="删除草稿" @click="removeDraft(p.id)">×</button>
        </li>
      </ul>
      <p class="muted small">
        草稿=平台上点的坐标，还没下发给机器人（写权限等真机联调 + 现场授权）。
      </p>
    </aside>

    <section class="panel main">
      <div class="panel-title">
        <span>{{ libMap?.name || selectedName || '未选地图' }}</span>
        <span class="muted small" v-if="meta">
          origin [{{ meta.origin?.[0]?.toFixed(2) }}, {{ meta.origin?.[1]?.toFixed(2) }}]
          · {{ meta.width }}×{{ meta.height }} px · {{ meta.resolution?.toFixed(3) }} m/px
        </span>
        <span v-if="picking" class="tag warn">打点模式：点地图选位置</span>
      </div>
      <div class="map-box" :class="{ picking }">
        <MapCanvas
          :map-meta="meta"
          :image-url="imageUrl"
          :points="points"
          :pose="libId ? null : robot.pose"
          :stale="robot.stale || !robot.online"
          @pick="onPick"
        />
      </div>
      <p v-if="error" class="danger small">{{ error }}</p>

      <div class="actions">
        <button class="btn" :disabled="!libId" :title="libId ? '在图上打点并保存为草稿' : '机器人地图只读，先导入平台地图'" @click="startPick">
          新增点位
        </button>
        <button class="btn" :disabled="!picking" @click="picking = false">退出打点</button>
        <span class="spacer" />
        <span class="muted small" v-if="libId">
          这张图是平台台账，未下发给机器人；{{ libMap?.robot_map_name ? `已映射机器人地图 ${libMap.robot_map_name}` : '还没和机器人地图对应' }}
        </span>
      </div>
    </section>

    <!-- 打点确认 -->
    <div v-if="pickAt" class="modal-mask" @click.self="pickAt = null">
      <div class="modal">
        <div class="panel-title"><span>新增点位（草稿）</span></div>
        <p class="muted small">坐标 x={{ pickAt.x.toFixed(2) }} y={{ pickAt.y.toFixed(2) }}（米）</p>
        <label class="fld"><span>点位名称</span><input class="input" v-model="draftName" autofocus /></label>
        <label class="fld"><span>备注</span><input class="input" v-model="draftNote" placeholder="如：1号配电柜正面" /></label>
        <div class="modal-actions">
          <button class="btn" @click="pickAt = null">取消</button>
          <button class="btn primary" @click="saveDraft">保存草稿</button>
        </div>
      </div>
    </div>

    <!-- 导入地图 -->
    <div v-if="importing" class="modal-mask" @click.self="importing = false">
      <div class="modal wide">
        <div class="panel-title"><span>导入地图</span><span class="muted small">PNG/JPG 图纸或截图，人工标定比例尺与原点</span></div>

        <label class="fld">
          <span>地图文件（PNG/JPG，≤20MB）</span>
          <input class="input" type="file" accept="image/png,image/jpeg" @change="onFile" />
        </label>
        <div class="two">
          <label class="fld"><span>名称</span><input class="input" v-model="impForm.name" placeholder="泰安厂区-1F" /></label>
          <label class="fld"><span>楼层</span><input class="input" v-model="impForm.floor" /></label>
        </div>
        <div class="two">
          <label class="fld"><span>场站</span><input class="input" v-model="impForm.station" /></label>
          <label class="fld"><span>对应机器人地图名</span><input class="input" v-model="impForm.robot_map_name" placeholder="留空=仅平台底图" /></label>
        </div>
        <div class="three">
          <label class="fld"><span>分辨率 m/px</span><input class="input" type="number" step="0.001" v-model.number="impForm.resolution" /></label>
          <label class="fld"><span>原点 X (m)</span><input class="input" type="number" step="0.1" v-model.number="impForm.origin_x" /></label>
          <label class="fld"><span>原点 Y (m)</span><input class="input" type="number" step="0.1" v-model.number="impForm.origin_y" /></label>
        </div>
        <label class="fld"><span>备注</span><input class="input" v-model="impForm.note" placeholder="图纸来源/标定人/日期" /></label>
        <p class="muted small">
          比例尺怎么来：图纸上找一段已知长度（如 10 米），量出像素长度，用「米 ÷ 像素」填进分辨率。
          原点填机器人建图时的 map 原点；不知道就填 0，等真机联调再校。
        </p>
        <div class="modal-actions">
          <button class="btn" @click="importing = false">取消</button>
          <button class="btn primary" :disabled="impBusy" @click="submitImport">{{ impBusy ? '导入中…' : '导入并查看' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { display: grid; grid-template-columns: 300px 1fr; gap: 12px; height: 100%; }
.side { overflow: auto; }
.main { display: flex; flex-direction: column; min-height: 0; }
.map-box { flex: 1; min-height: 0; }
.map-box.picking { outline: 1px dashed rgba(255, 207, 63, 0.7); }
.map-item {
  width: 100%; display: flex; justify-content: space-between; align-items: center; gap: 8px;
  background: var(--bg-2); border: 1px solid var(--line); color: var(--text-0);
  border-radius: 8px; padding: 7px 9px; margin-bottom: 6px; cursor: pointer; font-size: 13px;
}
.map-item.active { border-color: var(--accent); }
.points { list-style: none; padding: 0; margin: 0; }
.points li {
  display: grid; grid-template-columns: 22px 1fr auto 20px; gap: 6px; align-items: center;
  padding: 5px 7px; border-radius: 6px; font-size: 12px;
}
.points li:hover { background: var(--bg-2); }
.points .draft { color: #ffcf3f; font-size: 11px; }
.del { background: none; border: none; color: #ff8a8a; cursor: pointer; }
.actions { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
.spacer { flex: 1; }
.small { font-size: 12px; }
.mono { font-variant-numeric: tabular-nums; }
.btn-xs { padding: 2px 8px; font-size: 12px; }
.modal-mask {
  position: fixed; inset: 0; z-index: 120; display: grid; place-items: center;
  background: rgba(2, 14, 30, 0.66);
}
.modal {
  width: 460px; max-height: 90vh; overflow: auto; padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
}
.modal.wide { width: 600px; }
.fld { display: block; margin-bottom: 11px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.three { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
</style>
