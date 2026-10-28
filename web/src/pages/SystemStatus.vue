<script setup lang="ts">
/**
 * 系统状态：把"哪台车在轮询、哪路视频在转码、哪个采集网关在线"摊开给运维看。
 * 这些数据后端一直有接口，但之前没有页面——出问题时只能翻日志。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '@/api'

interface Rt {
  robot_id: number
  name: string
  online?: boolean
  age_s?: number | null
  last_error?: string | null
  clock_skew_s?: number | null
}

const runtimes = ref<Rt[]>([])
const streams = ref<Record<string, any>[]>([])
const gateways = ref<Record<string, any>[]>([])
const loading = ref(false)
const lastAt = ref('')
const gatewayInfo = ref<Record<number, { name: string; protocol: string }>>({})

function gatewayLabel(id: number | string): string {
  const g = gatewayInfo.value[Number(id)]
  return g ? `${g.protocol}` : '—'
}

function ageText(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  if (v < 0) return '无数据'
  return v >= 60 ? `${(v / 60).toFixed(1)} 分钟` : `${Math.round(v)} 秒`
}
// 现场自检：一次点完，直接告诉现场"是平台、网络还是设备的问题"
const selfChecks = ref<{ name: string; ok: boolean; detail: string; hint?: string }[]>([])
const selfRunAt = ref('')
const selfBusy = ref(false)

async function runSelfCheck() {
  selfBusy.value = true
  try {
    const r = await api.selfCheck()
    selfChecks.value = r.checks
    selfRunAt.value = r.ts.replace('T', ' ')
    lastAt.value = new Date().toLocaleTimeString('zh-CN')
  } finally {
    selfBusy.value = false
  }
}

let timer = 0

async function load() {
  loading.value = true
  try {
    const [r, s, g, list] = await Promise.all([
      api.robotRuntime().catch(() => []),
      api.videoStreamStats().catch(() => []),
      api.sensorGatewayRuntime().catch(() => []),
      api.sensorGateways().catch(() => []),
    ])
    runtimes.value = r as unknown as Rt[]
    streams.value = s as unknown as Record<string, any>[]
    gateways.value = g as unknown as Record<string, any>[]
    const info: Record<number, { name: string; protocol: string }> = {}
    for (const row of list as unknown as { id: number; name: string; protocol: string }[]) {
      info[row.id] = { name: row.name, protocol: row.protocol }
    }
    gatewayInfo.value = info
    lastAt.value = new Date().toLocaleTimeString('zh-CN')
  } finally {
    loading.value = false
  }
}

onMounted(() => { void load(); timer = window.setInterval(load, 10000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>设备运行时</span>
        <span class="muted small">哪台在线、数据多旧、有没有报错</span>
        <span class="grow" />
        <span class="dim small">{{ lastAt }} 更新</span>
        <button class="btn btn-sm ok" :disabled="loading" @click="load">刷新</button>
      </div>
      <table class="grid">
        <thead><tr>
          <th style="width:60px">ID</th><th style="width:180px">设备</th>
          <th style="width:100px">状态</th><th style="width:120px">数据年龄</th>
          <th style="width:120px">时钟偏差</th><th>错误</th>
        </tr></thead>
        <tbody>
          <tr v-for="r in runtimes" :key="r.robot_id">
            <td>{{ r.robot_id }}</td>
            <td>{{ r.name }}</td>
            <td><span class="tag" :class="r.online ? 'ok' : 'danger'">{{ r.online ? '在线' : '离线' }}</span></td>
            <td class="num">{{ ageText(r.age_s) }}</td>
            <td class="num">{{ r.clock_skew_s == null ? '—' : r.clock_skew_s + ' 秒' }}</td>
            <td class="dim small">{{ r.last_error || '—' }}</td>
          </tr>
          <tr v-if="!runtimes.length"><td colspan="6" class="dim">没有运行时数据</td></tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <div class="panel-title">
        <span>视频转码</span>
        <span class="muted small">每路相机只有一个 ffmpeg；观众数=几个人在看</span>
      </div>
      <table class="grid">
        <thead><tr>
          <th style="width:80px">视频源</th><th style="width:110px">观众</th>
          <th style="width:110px">转码进程</th><th>最后一帧年龄</th>
        </tr></thead>
        <tbody>
          <tr v-for="s in streams" :key="String(s.video_id)">
            <td>#{{ s.video_id }}</td>
            <td class="num">{{ s.viewers ?? 0 }}</td>
            <td><span class="tag" :class="s.running ? 'ok' : 'warn'">{{ s.running ? '运行中' : '已停' }}</span></td>
            <td class="num">{{ s.age_s === null || s.age_s === undefined ? '—' : s.age_s + ' 秒' }}</td>
          </tr>
          <tr v-if="!streams.length"><td colspan="4" class="dim">当前没有转码进程（没人看视频时会自动停）</td></tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <div class="panel-title">
        <span>采集网关</span>
        <span class="muted small">Modbus/MQTT 是否在采、上次成功是什么时候</span>
      </div>
      <table class="grid">
        <thead><tr>
          <th style="width:60px">ID</th><th style="width:200px">名称</th>
          <th style="width:150px">协议</th><th style="width:100px">状态</th>
          <th>最后采集 / 错误</th>
        </tr></thead>
        <tbody>
          <tr v-for="g in gateways" :key="String(g.id)">
            <td>{{ g.id }}</td>
            <td>{{ gatewayInfo[g.id]?.name ?? ('#' + g.id) }}</td>
            <td class="dim">{{ gatewayLabel(g.id) }}</td>
            <td>
              <span class="tag" :class="g.state === 'ok' ? 'ok' : 'danger'">
                {{ g.state === 'ok' ? '正常' : '失败' }}
              </span>
            </td>
            <td class="dim small">{{ g.error || g.ts || '—' }}</td>
          </tr>
          <tr v-if="!gateways.length"><td colspan="5" class="dim">没有采集网关</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
</style>
