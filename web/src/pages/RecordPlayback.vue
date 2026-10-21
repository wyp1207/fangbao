<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type RecordingItem, type VideoRow } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'

const route = useRoute()
const videos = ref<VideoRow[]>([])
const items = ref<RecordingItem[]>([])
const current = ref<RecordingItem | null>(null)
const videoId = ref('')
const date = ref(typeof route.query.date === 'string' ? route.query.date : '')
const targetTime = ref(typeof route.query.t === 'string' ? route.query.t : '')
const loading = ref(false)
const playback = ref<HTMLVideoElement | null>(null)

const videoOptions = computed(() => [
  { value: '', label: '全部摄像头' },
  ...videos.value.map((v) => ({ value: String(v.id), label: v.name })),
])
const nameOf = (id: number) => videos.value.find((v) => v.id === id)?.name ?? `#${id}`

const filtered = computed(() =>
  items.value.filter((it) => {
    if (videoId.value && String(it.video_id) !== videoId.value) return false
    if (date.value && it.started_at.slice(0, 10) !== date.value) return false
    return true
  }),
)

const fileUrl = computed(() =>
  current.value ? api.recordingFileUrl(current.value.path) : '',
)

function mb(n: number) {
  return (n / 1024 / 1024).toFixed(1)
}

async function load() {
  loading.value = true
  try {
    videos.value = await api.videos()
    const res = await api.recordings(videoId.value ? Number(videoId.value) : undefined)
    items.value = res.items
    if (current.value && !items.value.find((i) => i.path === current.value?.path)) current.value = null
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '录像列表读取失败', 'danger')
  } finally {
    loading.value = false
  }
}

async function play(it: RecordingItem) {
  current.value = it
  toast(`播放 ${it.path.split('/').pop()}`, 'info', 1500)
  await nextTick()        // <video> 是 v-if 渲染的，等它挂上再 play
  const el = playback.value
  if (el) {
    el.load()
    void el.play().catch(() => undefined)
  }
}

async function remove(it: RecordingItem) {
  if (!window.confirm(`删除这段录像？\n${it.path}`)) return
  try {
    await api.deleteRecording(it.path)
    toast('已删除', 'ok')
    if (current.value?.path === it.path) current.value = null
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '删除失败', 'danger')
  }
}

watch([videoId, date], load)

/** 按告警时间找所属录像段，选中并跳到告警时刻（前后各留 5 秒） */
async function jumpToTarget() {
  if (!targetTime.value || !filtered.value.length) return
  const want = `${date.value || filtered.value[0].started_at.slice(0, 10)}T${targetTime.value}`
  const target = new Date(want).getTime()
  if (Number.isNaN(target)) return

  for (const it of [...filtered.value].sort((a, b) => a.started_at.localeCompare(b.started_at))) {
    const start = new Date(it.started_at).getTime()
    const dur = (await api.recordingDuration(it.path).catch(() => ({ duration: null }))).duration ?? 300
    if (target >= start && target <= start + dur * 1000) {
      current.value = it
      await nextTick()
      const el = playback.value
      if (el) {
        const offset = Math.max(0, (target - start) / 1000 - 5)
        const seek = () => { el.currentTime = offset }
        el.addEventListener("loadedmetadata", seek, { once: true })
        el.load()
        void el.play().catch(() => undefined)
      }
      toast(`已定位到告警时刻 ${targetTime.value}`, "ok", 2500)
      return
    }
  }
  toast("这个时刻没有对应录像（可能没开录）", "warn", 3000)
}

onMounted(async () => {
  await load()
  await jumpToTarget()
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>录像回放</span>
        <span class="muted">按段点播，可拖动进度；导出就是下载这段 mp4</span>
      </div>

      <div class="toolbar">
        <label>摄像头</label>
        <DarkSelect v-model="videoId" :options="videoOptions" width="200px" />
        <label>日期</label>
        <input class="input date" type="date" v-model="date" />
        <button class="btn btn-sm ok" :disabled="loading" @click="load">查询</button>
        <button class="btn btn-sm warn" @click="videoId = ''; date = ''">重置</button>
        <span class="grow" />
        <router-link class="btn btn-sm" :to="{ name: 'record-plan' }">去录像计划</router-link>
      </div>

      <div class="split">
        <div class="list">
          <table class="grid">
            <thead>
              <tr>
                <th style="width: 60px">#</th>
                <th style="width: 160px">开始时间</th>
                <th>摄像头</th>
                <th style="width: 90px">大小</th>
                <th style="width: 120px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(it, i) in filtered" :key="it.path" :class="{ sel: current?.path === it.path }">
                <td>{{ i + 1 }}</td>
                <td class="num">{{ it.started_at.replace('T', ' ') }}</td>
                <td>{{ nameOf(it.video_id) }}</td>
                <td class="num dim">{{ mb(it.size) }} MB</td>
                <td>
                  <div class="row-actions">
                    <button class="act" title="播放" @click="play(it)">▶</button>
                    <a class="act" :href="api.recordingFileUrl(it.path)" :download="it.path.split('/').pop()" title="下载">⤓</a>
                    <button class="act danger" title="删除" @click="remove(it)">🗑</button>
                  </div>
                </td>
              </tr>
              <tr v-if="!filtered.length">
                <td colspan="5" class="dim">{{ loading ? '读取中…' : '这个条件下没有录像' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="player">
          <video v-if="current" ref="playback" :key="fileUrl" :src="fileUrl" controls preload="metadata" />
          <div v-else class="empty">
            <p>左侧选一段录像播放</p>
            <em>还没有录像？去「录像计划」点开始录制</em>
          </div>
          <div class="meta" v-if="current">
            <span>{{ current.started_at.replace('T', ' ') }}</span>
            <span>{{ nameOf(current.video_id) }}</span>
            <span>{{ mb(current.size) }} MB</span>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; display: flex; flex-direction: column; }

.split { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 46%); gap: 12px; }
.list { overflow: auto; min-height: 0; }
.player { display: flex; flex-direction: column; justify-content: center; gap: 8px; min-height: 0; }
.player video { width: 100%; max-height: 100%; aspect-ratio: 16 / 9; background: #02101f; }
.empty {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
  border: 1px dashed rgba(111, 227, 255, 0.3); color: #9fd2ff; background: rgba(2, 16, 34, 0.6);
}
.empty p { margin: 0; font-size: 13px; }
.empty em { font-style: normal; font-size: 11.5px; color: #6f9ec9; }
.meta { display: flex; gap: 14px; font-size: 11.5px; color: #8fc4f0; }
tr.sel td { background: rgba(41, 212, 255, 0.18) !important; }
.date { min-width: 140px; }
.num { font-variant-numeric: tabular-nums; }
.row-actions { display: flex; gap: 6px; }
a.act { display: inline-grid; place-items: center; text-decoration: none; }
</style>
