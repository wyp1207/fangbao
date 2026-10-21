<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { MapMeta, NavPoint } from '@/api'

const props = defineProps<{
  mapMeta: MapMeta | null
  imageUrl: string
  points: NavPoint[]
  pose: { x?: number; y?: number; theta_rad?: number } | null
  stale: boolean
  trail?: { x: number; y: number }[]
}>()

const canvas = ref<HTMLCanvasElement | null>(null)
const wrap = ref<HTMLDivElement | null>(null)
const hover = ref<{ x: number; y: number } | null>(null)
let img: HTMLImageElement | null = null
let ready = false
let scale = 1
let offsetX = 0
let offsetY = 0
let dragging = false
let lastX = 0
let lastY = 0
let ro: ResizeObserver | null = null

const res = computed(() => props.mapMeta?.resolution || 0.05)
const scaleLabel = computed(() => {
  const meters = (60 / scale) * res.value
  return meters >= 1 ? `${meters.toFixed(1)} m` : `${(meters * 100).toFixed(0)} cm`
})

function loadImage(url: string) {
  if (!url) return
  ready = false
  const image = new Image()
  image.onload = () => { img = image; ready = true; fit(); draw() }
  image.src = url
}

/** 地图坐标(米) -> 画布像素。y 轴翻转：第 0 行是地图最上方。 */
function worldToPixel(x: number, y: number): [number, number] {
  const meta = props.mapMeta
  if (!meta || !img) return [0, 0]
  const ox = meta.origin?.[0] ?? 0
  const oy = meta.origin?.[1] ?? 0
  return [(x - ox) / res.value, img.height - (y - oy) / res.value]
}

function screenToWorld(sx: number, sy: number): { x: number; y: number } | null {
  const meta = props.mapMeta
  if (!meta || !img) return null
  const px = (sx - offsetX) / scale
  const py = (sy - offsetY) / scale
  const ox = meta.origin?.[0] ?? 0
  const oy = meta.origin?.[1] ?? 0
  return { x: ox + px * res.value, y: oy + (img.height - py) * res.value }
}

function fit() {
  const el = canvas.value
  if (!el || !img) return
  const w = el.clientWidth
  const h = el.clientHeight
  scale = Math.min(w / img.width, h / img.height) * 0.94
  offsetX = (w - img.width * scale) / 2
  offsetY = (h - img.height * scale) / 2
}

function draw() {
  const el = canvas.value
  if (!el) return
  const dpr = window.devicePixelRatio || 1
  const w = el.clientWidth
  const h = el.clientHeight
  if (el.width !== w * dpr || el.height !== h * dpr) {
    el.width = w * dpr
    el.height = h * dpr
  }
  const ctx = el.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)
  ctx.fillStyle = '#f7f9fc'
  ctx.fillRect(0, 0, w, h)

  if (!img || !ready) {
    ctx.fillStyle = '#9aa8b8'
    ctx.font = '13px "PingFang SC", "Microsoft YaHei", sans-serif'
    ctx.fillText('地图加载中…', 20, 28)
    return
  }

  // 底图略微提亮，让点位和机器人更清楚
  ctx.save()
  ctx.translate(offsetX, offsetY)
  ctx.scale(scale, scale)
  ctx.drawImage(img, 0, 0)
  ctx.fillStyle = 'rgba(255, 255, 255, 0.18)'
  ctx.fillRect(0, 0, img.width, img.height)
  ctx.restore()

  // 轨迹
  if (props.trail?.length) {
    ctx.beginPath()
    props.trail.forEach((t, i) => {
      const [px, py] = worldToPixel(t.x, t.y)
      const sx = offsetX + px * scale
      const sy = offsetY + py * scale
      if (i === 0) ctx.moveTo(sx, sy)
      else ctx.lineTo(sx, sy)
    })
    ctx.strokeStyle = 'rgba(22, 119, 255, 0.35)'
    ctx.lineWidth = 1.6
    ctx.lineJoin = 'round'
    ctx.stroke()
  }

  // 点位
  for (const p of props.points) {
    const [px, py] = worldToPixel(p.x, p.y)
    const sx = offsetX + px * scale
    const sy = offsetY + py * scale
    ctx.beginPath()
    ctx.arc(sx, sy, 7, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(22, 119, 255, 0.14)'
    ctx.fill()
    ctx.beginPath()
    ctx.arc(sx, sy, 3.2, 0, Math.PI * 2)
    ctx.fillStyle = '#1677ff'
    ctx.fill()
    if (p.name) {
      ctx.font = '11px "PingFang SC", "Microsoft YaHei", sans-serif'
      const tw = ctx.measureText(p.name).width
      ctx.fillStyle = 'rgba(255, 255, 255, 0.9)'
      ctx.fillRect(sx + 9, sy - 17, tw + 8, 15)
      ctx.fillStyle = '#6b7a8c'
      ctx.fillText(p.name, sx + 13, sy - 6)
    }
  }

  // 机器人
  const pose = props.pose
  if (pose && typeof pose.x === 'number' && typeof pose.y === 'number') {
    const [px, py] = worldToPixel(pose.x, pose.y)
    const sx = offsetX + px * scale
    const sy = offsetY + py * scale
    const color = props.stale ? '#9aa8b8' : '#1677ff'

    ctx.beginPath()
    ctx.arc(sx, sy, 13, 0, Math.PI * 2)
    ctx.fillStyle = props.stale ? 'rgba(154, 168, 184, 0.15)' : 'rgba(22, 119, 255, 0.12)'
    ctx.fill()

    ctx.save()
    ctx.translate(sx, sy)
    ctx.rotate(-(pose.theta_rad ?? 0))
    ctx.beginPath()
    ctx.moveTo(10, 0)
    ctx.lineTo(-6.5, 6)
    ctx.lineTo(-6.5, -6)
    ctx.closePath()
    ctx.fillStyle = color
    ctx.fill()
    ctx.restore()
  }

  if (props.stale) {
    ctx.fillStyle = 'rgba(247, 249, 252, 0.55)'
    ctx.fillRect(0, 0, w, h)
    ctx.fillStyle = '#e8912a'
    ctx.font = 'bold 13px "PingFang SC", "Microsoft YaHei", sans-serif'
    ctx.fillText('数据过期', 16, 26)
  }
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  const el = canvas.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top
  const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12
  const next = Math.min(5, Math.max(0.4, scale * factor))
  const real = next / scale
  offsetX = mx - (mx - offsetX) * real
  offsetY = my - (my - offsetY) * real
  scale = next
  draw()
}

function onDown(e: MouseEvent) { dragging = true; lastX = e.clientX; lastY = e.clientY }
function onMove(e: MouseEvent) {
  const el = canvas.value
  if (el) {
    const rect = el.getBoundingClientRect()
    hover.value = screenToWorld(e.clientX - rect.left, e.clientY - rect.top)
  }
  if (!dragging) return
  offsetX += e.clientX - lastX
  offsetY += e.clientY - lastY
  lastX = e.clientX
  lastY = e.clientY
  draw()
}
function onUp() { dragging = false }
function onLeave() { dragging = false; hover.value = null }

watch(() => props.imageUrl, (url) => loadImage(url), { immediate: true })
watch(() => [props.points, props.pose, props.stale, props.mapMeta], () => draw(), { deep: true })

onMounted(() => {
  if (wrap.value) {
    ro = new ResizeObserver(() => { fit(); draw() })
    ro.observe(wrap.value)
  }
  draw()
})
onBeforeUnmount(() => ro?.disconnect())
</script>

<template>
  <div ref="wrap" class="map-wrap">
    <canvas
      ref="canvas"
      @wheel="onWheel"
      @mousedown="onDown"
      @mousemove="onMove"
      @mouseup="onUp"
      @mouseleave="onLeave"
    />

    <div class="hud legend">
      <span><i class="k point" />点位 {{ points.length }}</span>
      <span><i class="k robot" />机器人</span>
      <span><i class="k trail" />轨迹</span>
    </div>

    <div class="hud meta">
      <span v-if="mapMeta">{{ mapMeta.resolution?.toFixed(3) }} m/px · {{ mapMeta.width }}×{{ mapMeta.height }}</span>
    </div>

    <div class="hud coords num">
      <span v-if="hover">X {{ hover.x.toFixed(2) }} · Y {{ hover.y.toFixed(2) }} m</span>
      <span v-else class="muted">滚轮缩放 · 拖拽平移</span>
    </div>

    <div class="hud scalebar">
      <i />
      <span class="num">{{ scaleLabel }}</span>
    </div>
  </div>
</template>

<style scoped>
.map-wrap {
  position: relative; width: 100%; height: 100%; min-height: 320px;
  border-radius: var(--radius-sm); overflow: hidden;
  background-color: #f8fafc;
  background-image: radial-gradient(#dde4ee 1px, transparent 1px);
  background-size: 18px 18px;
  border: 1px solid var(--line);
}
canvas { width: 100%; height: 100%; display: block; cursor: crosshair; }

.hud {
  position: absolute; display: flex; align-items: center; gap: 12px;
  font-size: 12px; color: var(--text-1);
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--line);
  border-radius: 7px; padding: 5px 10px;
  box-shadow: 0 1px 4px rgba(15, 35, 60, 0.06);
  pointer-events: none;
}
.legend { top: 12px; left: 12px; }
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.k { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.k.point { background: #1677ff; box-shadow: 0 0 0 3px rgba(22, 119, 255, 0.16); }
.k.robot { background: #1677ff; border-radius: 2px; }
.k.trail { background: transparent; border-top: 2px solid rgba(22, 119, 255, 0.4); border-radius: 0; width: 12px; height: 0; }

.meta { top: 12px; right: 12px; }
.coords { bottom: 12px; left: 12px; min-width: 180px; justify-content: center; }

.scalebar { bottom: 12px; right: 12px; gap: 8px; }
.scalebar i {
  display: inline-block; width: 60px; height: 6px;
  border-left: 1px solid var(--text-1); border-right: 1px solid var(--text-1);
  border-bottom: 1px solid var(--text-1);
}
</style>
