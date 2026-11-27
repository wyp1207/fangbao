<script setup lang="ts">
/**
 * 新告警弹窗：设置里开启「告警弹窗」后，新告警在右上角出现 1.5 秒。
 * 点击跳到告警详情（/alarms?focus=id）。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, type AiResultItem, type AlarmItem } from '@/api'
import { useRobotStore } from '@/stores/robot'

const router = useRouter()
const robot = useRobotStore()
const enabled = ref(false)
const current = ref<AlarmItem | null>(null)
const shot = ref<AiResultItem | null>(null)
let lastId = 0
let hideTimer: ReturnType<typeof setTimeout> | undefined
let settingsTimer: ReturnType<typeof setInterval> | undefined

function close() {
  if (hideTimer) clearTimeout(hideTimer)
  hideTimer = undefined
  current.value = null
  shot.value = null
}

async function loadSetting() {
  try {
    const res = await api.settings()
    enabled.value = res.values['alarm.popup_enabled'] === true
  } catch { /* 设置读不到就不弹 */ }
}

function show(a: AlarmItem) {
  if (!enabled.value) return
  current.value = a
  shot.value = null
  void api.aiResultByAlarm(a.id).then((r) => {
    if (current.value?.id === a.id) shot.value = r
  }).catch(() => { /* 非 AI 告警没有证据图 */ })
  if (hideTimer) clearTimeout(hideTimer)
  hideTimer = setTimeout(close, 1500)
}

watch(() => robot.alarms, (list) => {
  if (!list?.length) return
  const max = Math.max(...list.map((a) => a.id))
  if (!lastId) { lastId = max; return }   // 首次加载不把历史告警弹一遍
  const fresh = list.filter((a) => a.id > lastId)
  lastId = max
  if (fresh.length) show(fresh.sort((a, b) => a.id - b.id)[fresh.length - 1])
}, { deep: true })

function openDetail() {
  const id = current.value?.id
  close()
  if (id) router.push({ name: 'alarms', query: { focus: String(id) } })
}

function timeText(s: string | null | undefined): string {
  return (s ?? '').replace('T', ' ').slice(5, 19)
}

function cameraText(): string {
  if (shot.value?.camera_name) return shot.value.camera_name
  return current.value?.message?.split(' ')[0] || '—'
}

function typeText(): string {
  if (shot.value?.algorithm_name) return shot.value.algorithm_name
  return current.value?.message?.replace(/^[^ ]+\s*检测到\s*/, '') || current.value?.metric || '—'
}

onMounted(() => {
  void loadSetting()
  settingsTimer = setInterval(loadSetting, 30_000)
})
onBeforeUnmount(() => {
  if (hideTimer) clearTimeout(hideTimer)
  if (settingsTimer) clearInterval(settingsTimer)
})
</script>

<template>
  <transition name="alarm-pop">
    <div v-if="current" class="alarm-pop" :class="current.level === 'critical' ? 'critical' : 'warn'"
         role="button" tabindex="0" title="点击查看告警详情"
         @click="openDetail" @keydown.enter="openDetail">
      <div class="ap-main">
        <div class="ap-time">{{ timeText(current.started_at) }}</div>
        <div class="ap-cam">{{ cameraText() }}</div>
        <div class="ap-type">{{ typeText() }}</div>
        <div class="ap-level">{{ current.level === 'critical' ? '严重' : '提醒' }}
          <span v-if="current.priority"> · {{ current.priority }}</span>
        </div>
      </div>
      <div class="ap-pic">
        <img v-if="shot?.image" :src="shot.image" alt="告警证据" />
        <span v-else class="ap-nopic">无图</span>
      </div>
      <i class="ap-progress" />
    </div>
  </transition>
</template>

<style scoped>
.alarm-pop {
  position: fixed; right: 18px; top: 86px; z-index: 420;
  width: 322px; height: 200px;
  display: grid; grid-template-columns: minmax(0, 1fr) 44%;
  gap: 0; overflow: hidden; cursor: pointer;
  background: rgba(4, 22, 44, 0.75);
  backdrop-filter: blur(7px);
  border: 1px solid rgba(255, 207, 63, 0.75);
  border-radius: 6px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4), 0 0 18px rgba(255, 190, 40, 0.18);
  animation: ap-in 0.28s ease-out;
}
.alarm-pop.critical { border-color: rgba(255, 77, 79, 0.9); box-shadow: 0 10px 30px rgba(0,0,0,.45), 0 0 20px rgba(255,77,79,.28); }
.alarm-pop.warn { border-color: rgba(255, 207, 63, 0.85); }
.ap-main { padding: 12px 12px 10px; display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.ap-time { font-size: 11px; color: #9fd2ff; font-variant-numeric: tabular-nums; }
.ap-cam { font-size: 13px; font-weight: 700; color: #eaf7ff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ap-type { font-size: 12px; color: #cfe8ff; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.ap-level { margin-top: auto; font-size: 11px; color: #ffd76a; }
.alarm-pop.critical .ap-level { color: #ff9a97; }
.ap-pic { position: relative; background: rgba(0, 12, 26, 0.55); display: grid; place-items: center; overflow: hidden; }
.ap-pic img { width: 100%; height: 100%; object-fit: cover; display: block; }
.ap-nopic { font-size: 11px; color: #7f9bb8; }
.ap-progress {
  position: absolute; left: 0; bottom: 0; height: 2px; width: 100%;
  background: linear-gradient(90deg, #ffd76a, #ff8a3c);
  transform-origin: left; animation: ap-progress 1.5s linear forwards;
}
.alarm-pop.critical .ap-progress { background: linear-gradient(90deg, #ff6b63, #ff2f2f); }
@keyframes ap-in { from { transform: translateX(28px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
@keyframes ap-progress { from { transform: scaleX(1); } to { transform: scaleX(0); } }
.alarm-pop-leave-active { transition: opacity 0.22s ease, transform 0.22s ease; }
.alarm-pop-leave-to { opacity: 0; transform: translateX(20px); }
</style>
