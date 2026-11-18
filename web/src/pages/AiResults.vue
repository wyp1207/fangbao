<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, type AiResultItem, type AiResultStats } from '@/api'
import DarkSelect from '@/components/DarkSelect.vue'

const rows = ref<AiResultItem[]>([])
const stats = ref<AiResultStats | null>(null)
const algorithms = ref<{ code: string; name: string }[]>([])
const algo = ref('')
const camera = ref('')
const confidence = ref('')
const level = ref('')
const loading = ref(false)
const error = ref('')
const preview = ref<AiResultItem | null>(null)
const dialogEl = ref<HTMLDialogElement | null>(null)

/** 真实回调是盒子侧三路相机；固定给出，stats 有数时再补计数。 */
const CAMERAS = [
  { id: 12, label: 'dog' },
  { id: 13, label: 'dog-云台' },
  { id: 14, label: '室外' },
]

const cameraOptions = computed(() => {
  const counts = new Map<number | null, number>()
  for (const c of stats.value?.by_camera ?? []) counts.set(c.external_camera_id, c.count)
  return [
    { value: '', label: '全部相机' },
    ...CAMERAS.map((c) => ({
      value: String(c.id),
      label: counts.get(c.id) ? `${c.label} · ${counts.get(c.id)}` : c.label,
    })),
  ]
})

const confidenceOptions = [
  { value: '', label: '全部置信度' },
  { value: '0.4', label: '≥ 40%' },
  { value: '0.6', label: '≥ 60%' },
  { value: '0.8', label: '≥ 80%' },
]

/** 告警级别：后端按 alarm_record.level 过滤，none 表示没建告警的结果。 */
const levelOptions = [
  { value: '', label: '全部级别' },
  { value: 'p1', label: 'P1 严重' },
  { value: 'p2', label: 'P2 一般' },
  { value: 'none', label: '未告警' },
]

/** 已注册算法（手工推送用 code）+ 真实回调里出现过的算法名，合并去重。 */
const algoOptions = computed(() => {
  const registered = new Map(algorithms.value.map((a) => [a.code, a.name]))
  const seen = new Set<string>()
  const out = [{ value: '', label: '全部算法' }]
  for (const row of stats.value?.by_algorithm ?? []) {
    seen.add(row.algorithm)
    out.push({ value: row.algorithm, label: registered.get(row.algorithm) ?? row.algorithm })
  }
  for (const a of algorithms.value) {
    if (seen.has(a.code)) continue
    seen.add(a.code)
    out.push({ value: a.code, label: a.name })
  }
  return out
})

async function loadStats() {
  try {
    stats.value = await api.aiResultStats()
  } catch {
    /* 统计失败不影响看列表 */
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.aiResults({
      algorithm: algo.value || undefined,
      external_camera_id: camera.value ? Number(camera.value) : undefined,
      min_confidence: confidence.value ? Number(confidence.value) : undefined,
      level: (level.value || undefined) as 'p1' | 'p2' | 'none' | undefined,
      limit: 200,
    })
    rows.value = res.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function refreshAll() {
  await Promise.all([load(), loadStats()])
}

// 15 秒自动刷新；页面隐藏时停表，回来先补一次再继续
let timer: ReturnType<typeof setInterval> | undefined

function startAuto() {
  stopAuto()
  timer = setInterval(() => {
    if (!document.hidden) void refreshAll()
  }, 15_000)
}

function stopAuto() {
  if (timer !== undefined) {
    clearInterval(timer)
    timer = undefined
  }
}

function onVisibility() {
  if (document.hidden) {
    stopAuto()
  } else {
    void refreshAll()
    startAuto()
  }
}

onMounted(async () => {
  try {
    algorithms.value = await api.aiAlgorithms()
  } catch { /* 无算法也不影响看结果 */ }
  await refreshAll()
  startAuto()
  document.addEventListener('visibilitychange', onVisibility)
})

onBeforeUnmount(() => {
  stopAuto()
  document.removeEventListener('visibilitychange', onVisibility)
})

function pct(c: number): string {
  return `${Math.round(c * 100)}%`
}

function confidenceClass(c: number): string {
  return c >= 0.8 ? 'ok' : c >= 0.6 ? 'warn' : 'danger'
}

function cameraText(r: AiResultItem): string {
  if (r.camera_name) return r.camera_name
  const id = r.external_camera_id ?? r.camera_id
  return id != null ? `相机 ${id}` : '—'
}

function alarmText(r: AiResultItem): string {
  const prefix = r.alarm_level === 'critical' ? 'P1' : r.alarm_level === 'warn' ? 'P2' : '告警'
  return `${prefix} #${r.alarm_id}`
}

function alarmClass(r: AiResultItem): string {
  return r.alarm_level === 'critical' ? 'danger' : r.alarm_level === 'warn' ? 'warn' : ''
}

function openImage(r: AiResultItem) {
  if (!r.image) return
  preview.value = r
  dialogEl.value?.showModal()
}

function closeImage() {
  dialogEl.value?.close()
}
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>AI 识别结果</span>
        <span class="muted small">真实回调回看 · 每 15 秒自动刷新（页面隐藏时暂停）</span>
        <span class="grow" />
        <div class="filters">
          <DarkSelect v-model="algo" width="170px" :options="algoOptions" @update:model-value="load" />
          <DarkSelect v-model="camera" width="150px" :options="cameraOptions" @update:model-value="load" />
          <DarkSelect v-model="confidence" width="130px" :options="confidenceOptions" @update:model-value="load" />
          <DarkSelect v-model="level" width="140px" :options="levelOptions" @update:model-value="load" />
          <button type="button" class="btn btn-sm ok" :disabled="loading" @click="refreshAll">刷新</button>
        </div>
      </div>

      <div class="kpis">
        <div class="kpi"><span>总数</span><b>{{ stats?.total ?? '—' }}</b></div>
        <div class="kpi"><span>今日</span><b>{{ stats?.today ?? '—' }}</b></div>
        <div class="kpi danger"><span>P1 告警</span><b>{{ stats?.p1 ?? '—' }}</b></div>
        <div class="kpi warn"><span>P2 告警</span><b>{{ stats?.p2 ?? '—' }}</b></div>
      </div>

      <p v-if="error" class="err small">{{ error }}</p>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 150px">时间</th>
            <th style="width: 130px">相机</th>
            <th style="width: 220px">算法</th>
            <th style="width: 100px">置信度</th>
            <th style="width: 140px">告警级别 / ID</th>
            <th style="width: 120px">图片</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td class="num dim">{{ (r.ts ?? '—').replace('T', ' ') }}</td>
            <td>
              {{ cameraText(r) }}
            </td>
            <td>
              {{ r.algorithm_name }}
              <span v-if="r.review_state" class="tag" style="margin-left: 6px">{{ r.review_state }}</span>
            </td>
            <td>
              <span class="tag" :class="confidenceClass(r.confidence)">{{ pct(r.confidence) }}</span>
            </td>
            <td>
              <span v-if="r.alarm_id" class="tag" :class="alarmClass(r)">{{ alarmText(r) }}</span>
              <span v-else class="dim small">未触发</span>
            </td>
            <td>
              <img
                v-if="r.image"
                class="thumb"
                :src="r.image"
                alt="识别证据图"
                loading="lazy"
                @click="openImage(r)"
              />
              <span v-else class="dim">—</span>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="6" class="dim">
              <template v-if="loading">读取中…</template>
              <template v-else>等待 .170 回调</template>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <dialog ref="dialogEl" class="lightbox" @click="closeImage" @close="preview = null">
      <div class="lightbox-inner">
        <img v-if="preview?.image" :src="preview.image" alt="识别证据大图" />
        <div class="lightbox-meta small">
          {{ preview ? `${preview.camera_name ?? '—'} · ${preview.algorithm_name} · ${pct(preview.confidence)} · ${(preview.ts ?? '').replace('T', ' ')}` : '' }}
          <span class="dim">（点击关闭）</span>
        </div>
      </div>
    </dialog>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.small { font-size: 12px; }
.num { font-variant-numeric: tabular-nums; }
.filters { display: flex; align-items: center; gap: 8px; }
.err { color: #ff9b9b; margin: 0 0 8px; }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 4px 0 14px; }
.kpi {
  padding: 9px 11px; border-radius: 4px;
  background: linear-gradient(180deg, rgba(0, 96, 170, 0.42), rgba(0, 50, 100, 0.5));
  border-left: 2px solid rgba(111, 227, 255, 0.6);
}
.kpi span { display: block; font-size: 11.5px; color: #9fd2ff; margin-bottom: 3px; }
.kpi b { font-size: 20px; color: #fff; font-variant-numeric: tabular-nums; }
.kpi.danger { border-left-color: #ff5a5a; }
.kpi.warn { border-left-color: #ffcf3f; }

.thumb {
  width: 60px; height: 44px; object-fit: cover;
  border: 1px solid rgba(111, 227, 255, 0.45);
  cursor: zoom-in;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.thumb:hover { border-color: #7fe9ff; box-shadow: 0 0 10px rgba(80, 200, 255, 0.45); }

.lightbox {
  padding: 10px;
  border: 1px solid rgba(111, 227, 255, 0.55);
  background: rgba(2, 18, 38, 0.97);
  color: #dff3ff;
  max-width: 92vw;
  max-height: 92vh;
  cursor: zoom-out;
}
.lightbox::backdrop { background: rgba(0, 8, 20, 0.78); }
.lightbox-inner { display: flex; flex-direction: column; gap: 8px; align-items: center; }
.lightbox img { max-width: 86vw; max-height: 78vh; display: block; object-fit: contain; }
.lightbox-meta { color: #cfe8ff; text-align: center; }

@media (max-width: 1100px) {
  .filters { flex-wrap: wrap; justify-content: flex-end; }
}
</style>
