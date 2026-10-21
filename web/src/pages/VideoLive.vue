<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, type VideoRow } from '@/api'
import { ApiError } from '@/api/client'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'

const props = withDefaults(defineProps<{ group?: string }>(), { group: '' })

const rows = ref<VideoRow[]>([])
const current = ref<VideoRow | null>(null)
const loading = ref(false)
const error = ref('')
const tick = ref(Date.now())
const snapFailed = ref(false)
const mjpegFailed = ref(false)

const snapUrl = computed(() =>
  current.value ? api.snapshotUrl(current.value.id, tick.value) : '',
)
// MJPEG 是长连接，URL 必须稳定；加时间戳会让 <img> 每 2 秒重建一次流
const mjpegUrl = computed(() =>
  current.value ? `/api/v1/videos/${current.value.id}/mjpeg` : '',
)

function onMjpegError() {
  mjpegFailed.value = true
  tick.value = Date.now()   // 立刻切到抓帧
}

const visible = computed(() =>
  rows.value.filter((r) => (props.group ? r.group_name === props.group : true)),
)
const options = computed(() => visible.value.map((v) => ({ value: String(v.id), label: v.name })))
const currentId = computed({
  get: () => (current.value ? String(current.value.id) : ''),
  set: (v: string) => {
    current.value = visible.value.find((r) => String(r.id) === v) ?? null
  },
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    rows.value = await api.videos()
    if (!current.value) current.value = visible.value[0] ?? null
    if (current.value) { mjpegFailed.value = false; snapFailed.value = false }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : '视频源读取失败'
  } finally {
    loading.value = false
  }
}

function test() {
  if (!current.value) return
  void api.testVideo(current.value.id)
    .then((r) => toast(`${r.target}：${r.message}`, r.ok ? 'ok' : 'danger', 3200))
    .catch(() => toast('测试失败', 'danger'))
}

let timer = 0
let snapTimer = 0
onMounted(async () => {
  await load()
  timer = window.setInterval(load, 30000)       // 配置偶尔刷新
  snapTimer = window.setInterval(() => {
    // 只有退到抓帧模式才需要刷新；MJPEG 是持续流，不要动 URL
    if (current.value && !current.value.play_url && mjpegFailed.value && !snapFailed.value) {
      tick.value = Date.now()
    }
  }, 2000)
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  window.clearInterval(snapTimer)
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>{{ group ? group + '监控' : '视频监控' }}</span>
        <span v-if="current?.go2rtc_url" class="tag ok">go2rtc MSE ~0.5s</span>
        <span v-else-if="current?.play_url" class="tag ok">HLS 播放</span>
        <span v-else-if="current && !mjpegFailed" class="tag ok">MJPEG 实时</span>
        <span v-else-if="current && !snapFailed" class="tag ok">抓帧预览</span>
        <span v-else class="tag warn">无可用画面</span>
      </div>

      <div class="toolbar">
        <label>视频源</label>
        <DarkSelect v-if="options.length" v-model="currentId" :options="options" width="220px" />
        <span v-else class="muted small">{{ loading ? '读取中…' : '还没有视频源' }}</span>
        <button class="btn btn-sm" :disabled="!current" @click="test">测试连通</button>
        <button class="btn btn-sm" @click="load">刷新列表</button>
        <span class="grow" />
        <router-link class="btn btn-sm" :to="{ name: 'cameras' }">去管理视频源</router-link>
      </div>

      <div class="player">
        <iframe
          v-if="current?.go2rtc_url" :src="current.go2rtc_url"
          class="gz" allow="autoplay; fullscreen" title="go2rtc 实时画面"
        />
        <video v-else-if="current?.play_url" :src="current.play_url" controls autoplay muted />
        <div v-else-if="current && !mjpegFailed" class="snap-wrap">
          <img :src="mjpegUrl" alt="实时画面" @error="onMjpegError" />
          <span class="snap-badge">MJPEG 实时 · 首帧约 0.5s</span>
        </div>
        <div v-else-if="current && !snapFailed" class="snap-wrap">
          <img
            :src="snapUrl" alt="抓帧预览"
            @error="snapFailed = true"
          />
          <span class="snap-badge">抓帧预览 · 每 2s 一帧</span>
        </div>
        <div v-else class="empty">
          <div class="screen-frame">
            <span class="c tl" /><span class="c tr" /><span class="c bl" /><span class="c br" />
            <div class="center">
              <div class="icon">▷</div>
              <p v-if="current">抓帧失败：{{ current.name }}</p>
              <p v-else>还没有可播放的视频源</p>
              <em v-if="current">rtsp 需要转流服务（MediaMTX / ffmpeg → HLS）才能在这里播放</em>
              <em v-else>先到「设备管理 → 摄像头」添加一路视频流</em>
            </div>
          </div>
        </div>
      </div>

      <div class="meta" v-if="current">
        <span>ID：{{ current.id }}</span>
        <span>分组：{{ current.group_name }}</span>
        <span>厂商：{{ current.vendor }}</span>
        <span class="mono">{{ current.url }}</span>
      </div>

      <p v-if="error" class="danger small">{{ error }}</p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; display: flex; flex-direction: column; }

.player { flex: 1; min-height: 260px; display: flex; }
.player video { flex: 1; min-height: 0; background: #02101f; object-fit: contain; }
.player .gz { flex: 1; min-height: 0; width: 100%; border: 0; background: #02101f; }
.snap-wrap { position: relative; flex: 1; min-height: 0; display: flex; background: #02101f; }
.snap-wrap img { width: 100%; height: 100%; object-fit: contain; }
.snap-badge {
  position: absolute; left: 10px; bottom: 10px;
  padding: 2px 8px; font-size: 11px; color: #cfe8ff;
  background: rgba(2, 16, 34, 0.75);
  border: 1px solid rgba(111, 227, 255, 0.45);
}

.empty { flex: 1; display: flex; }
.screen-frame {
  position: relative; flex: 1;
  border: 1px solid rgba(111, 227, 255, 0.35);
  background: radial-gradient(circle at 50% 45%, rgba(20, 90, 170, 0.45), rgba(2, 16, 34, 0.95) 70%);
}
.c { position: absolute; width: 14px; height: 14px; border: 0 solid #6fe3ff; }
.tl { top: 6px; left: 6px; border-top-width: 2px; border-left-width: 2px; }
.tr { top: 6px; right: 6px; border-top-width: 2px; border-right-width: 2px; }
.bl { bottom: 6px; left: 6px; border-bottom-width: 2px; border-left-width: 2px; }
.br { bottom: 6px; right: 6px; border-bottom-width: 2px; border-right-width: 2px; }
.center {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
  color: #9fd2ff;
}
.center .icon {
  width: 46px; height: 46px; display: grid; place-items: center;
  border: 1px solid rgba(111, 227, 255, 0.6); border-radius: 50%;
  color: #7fe9ff; font-size: 18px;
}
.center p { margin: 8px 0 0; font-size: 13px; color: #cfe8ff; }
.center em { font-style: normal; font-size: 11px; color: #6f9ec9; }

.meta {
  display: flex; gap: 16px; flex-wrap: wrap;
  margin-top: 8px; font-size: 11.5px; color: #8fc4f0;
}
.mono { font-family: ui-monospace, Consolas, monospace; }
.small { font-size: 12px; }
</style>
