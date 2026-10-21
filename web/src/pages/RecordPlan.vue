<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, type VideoRow } from '@/api'
import { ApiError } from '@/api/client'
import { toast } from '@/composables/useToast'

const videos = ref<VideoRow[]>([])
const running = ref<Record<number, boolean>>({})
const storage = ref({ files: 0, bytes: 0, dir: '' })
const ready = ref(false)
const ffmpeg = ref(true)
const paused = ref(true)   // 与后端 JC_RECORDING_ENABLED 对应；关闭时不写盘

const totalMb = computed(() => (storage.value.bytes / 1024 / 1024).toFixed(1))

async function load() {
  try {
    const [vs, status, st] = await Promise.all([
      api.videos(),
      api.recordingStatus(),
      api.recordingStorage(),
    ])
    videos.value = vs
    ffmpeg.value = status.ffmpeg
    ready.value = true
    const map: Record<number, boolean> = {}
    for (const r of status.recorders) map[r.video_id] = r.running
    running.value = map
    storage.value = st
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '录像状态读取失败', 'danger')
  }
}

async function start(v: VideoRow) {
  if (paused.value) {
    toast('录像已暂停：保留策略待定，暂不落盘', 'warn', 3000)
    return
  }
  try {
    await api.startRecording(v.id)
    toast(`开始录制：${v.name}`, 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '开始失败', 'danger', 3200)
  }
}

async function stop(v: VideoRow) {
  try {
    await api.stopRecording(v.id)
    toast(`已停止：${v.name}`, 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '停止失败', 'danger')
  }
}

let timer = 0
onMounted(async () => {
  await load()
  timer = window.setInterval(load, 10000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>录像计划</span>
        <span class="tag warn">录像已暂停</span>
        <span class="muted">保留策略待定，暂不落盘；已录的 {{ storage.files }} 段仍可回放</span>
      </div>

      <div class="summary">
        <span>已录 {{ storage.files }} 段</span>
        <span>占用 {{ totalMb }} MB</span>
        <span class="mono dim">{{ storage.dir }}</span>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th>名称</th>
            <th style="width: 140px">分组</th>
            <th style="width: 110px">录制状态</th>
            <th style="width: 200px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="v in videos" :key="v.id">
            <td>{{ v.id }}</td>
            <td>{{ v.name }}</td>
            <td class="dim">{{ v.group_name }}</td>
            <td>
              <span class="tag" :class="running[v.id] ? 'danger' : ''">
                {{ running[v.id] ? '录制中' : '未录制' }}
              </span>
            </td>
            <td>
              <div class="row-actions">
                <button class="btn btn-sm" :disabled="paused || running[v.id]" :title="paused ? '保留策略待定，暂不落盘' : ''" @click="start(v)">开始录制</button>
                <button class="btn btn-sm" :disabled="!running[v.id]" @click="stop(v)">停止</button>
                <button class="link-btn" @click="$router.push({ name: 'record-playback' })">去回放</button>
              </div>
            </td>
          </tr>
          <tr v-if="!videos.length"><td colspan="5" class="dim">{{ ready ? '还没有视频源' : '读取中…' }}</td></tr>
        </tbody>
      </table>

      <p class="muted small">
        当前状态：<b class="warn">暂停录制</b>（<code>JC_RECORDING_ENABLED=false</code>）。
        要恢复时，先定下保留天数与容量上限（见 docs/录像保留策略-20261021.xlsx），再把这个开关打开。<br />
        录制是服务端 ffmpeg 把 RTSP 转成 H.264 分段落盘，每段 5 分钟（可配 <code>JC_RECORD_SEGMENT_SECONDS</code>）。
        1080p 转码约吃 0.3–0.5 核，所以同时最多录 2 路；要更多路建议在 go2rtc 侧录制或加转码机。
      </p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.summary { display: flex; gap: 18px; align-items: center; margin-bottom: 10px; font-size: 12.5px; color: #bcdcff; }
.small { font-size: 12px; line-height: 1.8; }
.mono { font-family: ui-monospace, Consolas, monospace; font-size: 11.5px; }
.row-actions { display: flex; gap: 6px; align-items: center; }
.link-btn { background: none; border: none; cursor: pointer; color: #7fe9ff; font-size: 12px; }
</style>
