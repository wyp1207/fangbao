<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, type VideoRow } from '@/api'
import { ApiError } from '@/api/client'
import { toast } from '@/composables/useToast'

const videos = ref<VideoRow[]>([])
const running = ref<Record<number, boolean>>({})
const storage = ref({ files: 0, bytes: 0, dir: '' })
const keepDays = ref(30)
const maxGb = ref(800)
const ready = ref(false)
const ffmpeg = ref(true)
const paused = ref(false)

// ---- 录制计划 ----
interface PlanRow {
  id: number; video_id: number; video_name: string; name: string; days: string
  start_time: string; end_time: string; enabled: boolean; active_now: boolean
}
const plans = ref<PlanRow[]>([])
const planOpen = ref(false)
const DAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']
const planForm = ref({ name: '', videoId: '', days: '1111111', start_time: '08:00', end_time: '18:00', note: '' })
const videoOptions = computed(() => videos.value.map((v) => ({ value: String(v.id), label: v.name })))

function daysText(days: string): string {
  const on = DAY_LABELS.filter((_, i) => days[i] === '1')
  return on.length === 7 ? '每天' : on.length ? '周' + on.join('、') : '不启用'
}

async function loadPlans() {
  try { plans.value = (await api.recordPlans()) as unknown as PlanRow[] } catch { plans.value = [] }
}

function openPlan() {
  planForm.value = { name: '', videoId: videos.value[0] ? String(videos.value[0].id) : '',
                     days: '1111111', start_time: '08:00', end_time: '18:00', note: '' }
  planOpen.value = true
}

function toggleDay(i: number) {
  const arr = planForm.value.days.split('')
  arr[i] = arr[i] === '1' ? '0' : '1'
  planForm.value.days = arr.join('')
}

async function submitPlan() {
  try {
    await api.createRecordPlan({
      video_id: Number(planForm.value.videoId),
      name: planForm.value.name.trim(),
      days: planForm.value.days,
      start_time: planForm.value.start_time,
      end_time: planForm.value.end_time,
      note: planForm.value.note || null,
    })
    toast('计划已保存，最多 30 秒后生效', 'ok')
    planOpen.value = false
    await loadPlans()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '保存失败', 'danger')
  }
}

async function togglePlan(pl: PlanRow) {
  await api.updateRecordPlan(pl.id, { enabled: !pl.enabled })
  await loadPlans()
}

async function removePlan(pl: PlanRow) {
  if (!window.confirm(`删除计划「${pl.name}」？`)) return
  await api.deleteRecordPlan(pl.id)
  await loadPlans()
}   // 由后端 /recordings/status 的 enabled 决定

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
    paused.value = !status.enabled
    ready.value = true
    const map: Record<number, boolean> = {}
    for (const r of status.recorders) map[r.video_id] = r.running
    running.value = map
    storage.value = st
    keepDays.value = status.keep_days
    maxGb.value = status.max_gb
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '录像状态读取失败', 'danger')
  }
}

async function start(v: VideoRow) {
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
  void loadPlans()
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
        <span class="tag" :class="paused ? 'warn' : 'ok'">{{ paused ? '录像已暂停' : '录像已启用' }}</span>
        <span class="muted">保留 {{ keepDays }} 天 / 上限 {{ maxGb }} GB，超限自动删最老</span>
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
        当前状态：<b :class="paused ? 'warn' : 'ok'">{{ paused ? '暂停录制（JC_RECORDING_ENABLED=false）' : '录制已启用' }}</b>。
        保留策略见 docs/录像保留策略-20261021.xlsx；清理每 10 分钟跑一次，磁盘低于 5GB 会自动停录并告警。<br />
        录制是服务端 ffmpeg 把 RTSP 转成 H.264 分段落盘，每段 5 分钟（可配 <code>JC_RECORD_SEGMENT_SECONDS</code>）。
        1080p 转码约吃 0.3–0.5 核，所以同时最多录 2 路；要更多路建议在 go2rtc 侧录制或加转码机。
      </p>
    </section>

    <section class="panel">
      <div class="panel-title">
        <span>定时录制计划</span>
        <span class="muted">到点自动开录、过点自动停；只停由计划启动的录制，不碰手动开的</span>
        <span class="grow" />
        <button class="btn btn-sm primary" :disabled="!videos.length" @click="openPlan">新增计划</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">ID</th>
            <th style="width: 150px">名称</th>
            <th style="width: 160px">摄像头</th>
            <th style="width: 180px">星期</th>
            <th style="width: 150px">时段</th>
            <th style="width: 100px">当前</th>
            <th style="width: 90px">启用</th>
            <th style="width: 90px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="pl in plans" :key="pl.id">
            <td>{{ pl.id }}</td>
            <td>{{ pl.name }}</td>
            <td class="dim">{{ pl.video_name }}</td>
            <td class="dim">{{ daysText(pl.days) }}</td>
            <td class="num">{{ pl.start_time }} – {{ pl.end_time }}</td>
            <td><span class="tag" :class="pl.active_now ? 'ok' : ''">{{ pl.active_now ? '窗口内' : '窗口外' }}</span></td>
            <td><span class="tag" :class="pl.enabled ? 'ok' : 'warn'">{{ pl.enabled ? '开' : '关' }}</span></td>
            <td>
              <div class="row-actions">
                <button class="act" title="启用/停用" @click="togglePlan(pl)">{{ pl.enabled ? '⏸' : '▶' }}</button>
                <button class="act danger" title="删除" @click="removePlan(pl)">🗑</button>
              </div>
            </td>
          </tr>
          <tr v-if="!plans.length"><td colspan="8" class="dim">还没有计划。设一个「每天 08:00–18:00」就能自动录。</td></tr>
        </tbody>
      </table>
    </section>

    <!-- 新建计划 -->
    <div v-if="planOpen" class="modal-mask" @click.self="planOpen = false">
      <div class="modal">
        <div class="panel-title"><span>新增录制计划</span></div>
        <div class="two">
          <label class="fld"><span>名称<i class="req">*</i></span><input class="input" v-model="planForm.name" placeholder="白天巡检录制" /></label>
          <label class="fld">
            <span>摄像头<i class="req">*</i></span>
            <DarkSelect v-model="planForm.videoId" :options="videoOptions" width="100%" />
          </label>
        </div>
        <div class="fld">
          <span>星期</span>
          <div class="days">
            <button v-for="(d, i) in DAY_LABELS" :key="i" class="day" :class="{ on: planForm.days[i] === '1' }" @click="toggleDay(i)">{{ d }}</button>
          </div>
        </div>
        <div class="two">
          <label class="fld"><span>开始</span><input class="input" type="time" v-model="planForm.start_time" /></label>
          <label class="fld"><span>结束</span><input class="input" type="time" v-model="planForm.end_time" /></label>
        </div>
        <label class="fld"><span>备注</span><input class="input" v-model="planForm.note" /></label>
        <div class="modal-actions">
          <button class="btn" @click="planOpen = false">取消</button>
          <button class="btn primary" :disabled="!planForm.name.trim()" @click="submitPlan">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-mask { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; background: rgba(2, 14, 30, 0.66); }
.modal {
  width: 520px; padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
}
.fld { display: block; margin-bottom: 11px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.days { display: flex; gap: 6px; }
.day {
  width: 34px; height: 28px; border-radius: 4px; cursor: pointer;
  background: rgba(0, 60, 110, 0.6); color: #9fd2ff;
  border: 1px solid rgba(111, 227, 255, 0.3);
}
.day.on { background: rgba(41, 212, 255, 0.35); color: #fff; border-color: #7fe9ff; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }

.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.summary { display: flex; gap: 18px; align-items: center; margin-bottom: 10px; font-size: 12.5px; color: #bcdcff; }
.small { font-size: 12px; line-height: 1.8; }
.mono { font-family: ui-monospace, Consolas, monospace; font-size: 11.5px; }
.row-actions { display: flex; gap: 6px; align-items: center; }
.link-btn { background: none; border: none; cursor: pointer; color: #7fe9ff; font-size: 12px; }
</style>
