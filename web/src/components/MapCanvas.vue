<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
let img: HTMLImageElement | null = null
let ready = false
let scale = 1
let offsetX = 0
let offsetY = 0
let dragging = false
let lastX = 0
let lastY = 0
let ro: ResizeObserver | null = null

function loadImage(url: string) {
  if (!url) return
  ready = false
  const image = new Image()
  image.onload = () => {
    img = image
    ready = true
    fit()
    draw()
  }
  image.src = url
}

/** 地图坐标(米) -> 画布像素。y 轴要翻转：第 0 行是地图最上方。 */
function worldToPixel(x: number, y: number): [number, number] {
  const meta = props.mapMeta
  if (!meta || !img) return [0, 0]
  const res = meta.resolution || 0.05
  const ox = meta.origin?.[0] ?? 0
  const oy = meta.origin?.[1] ?? 0
  const px = (x - ox) / res
  const py = img.height - (y - oy) / res
  return [px, py]
}

function fit() {
  const el = canvas.value
  if (!el || !img) return
  const w = el.clientWidth
  const h = el.clientHeight
  scale = Math.min(w / img.width, h / img.height) * 0.95
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
  ctx.fillStyle = '#070d16'
  ctx.fillRect(0, 0, w, h)

  if (!img || !ready) {
    ctx.fillStyle = '#5f7590'
    ctx.font = '14px sans-serif'
    ctx.fillText('地图加载中…', 20, 30)
    return
  }

  ctx.save()
  ctx.translate(offsetX, offsetY)
  ctx.scale(scale, scale)
  // 底图压暗 + 提亮：让点位和机器人成为视觉主体
  ctx.drawImage(img, 0, 0)
  ctx.fillStyle = 'rgba(7, 13, 22, 0.45)'
  ctx.fillRect(0, 0, img.width, img.height)
  ctx.restore()

  // 点位
  for (const p of props.points) {
    const [px, py] = worldToPixel(p.x, p.y)
    const sx = offsetX + px * scale
    const sy = offsetY + py * scale
    ctx.beginPath()
    ctx.arc(sx, sy, 4, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(46, 168, 255, 0.9)'
    ctx.shadowColor = 'rgba(46, 168, 255, 0.8)'
    ctx.shadowBlur = 8
    ctx.fill()
    ctx.shadowBlur = 0
    if (p.name) {
      ctx.fillStyle = '#9fb3c8'
      ctx.font = '11px sans-serif'
      ctx.fillText(p.name, sx + 8, sy - 6)
    }
  }

  // 轨迹尾迹
  if (props.trail?.length) {
    ctx.beginPath()
    props.trail.forEach((t, i) => {
      const [px, py] = worldToPixel(t.x, t.y)
      const sx = offsetX + px * scale
      const sy = offsetY + py * scale
      if (i === 0) ctx.moveTo(sx, sy)
      else ctx.lineTo(sx, sy)
    })
    ctx.strokeStyle = 'rgba(46, 168, 255, 0.35)'
    ctx.lineWidth = 1.5
    ctx.stroke()
  }

  // 机器人
  const pose = props.pose
  if (pose && typeof pose.x === 'number' && typeof pose.y === 'number') {
    const [px, py] = worldToPixel(pose.x, pose.y)
    const sx = offsetX + px * scale
    const sy = offsetY + py * scale
    const theta = pose.theta_rad ?? 0
    ctx.save()
    ctx.translate(sx, sy)
    ctx.rotate(-theta) // 画布 y 向下，与地图 y 向上相反
    ctx.beginPath()
    ctx.moveTo(12, 0)
    ctx.lineTo(-8, 7)
    ctx.lineTo(-8, -7)
    ctx.closePath()
    ctx.fillStyle = props.stale ? '#5f7590' : '#37d399'
    ctx.shadowColor = props.stale ? 'transparent' : 'rgba(55, 211, 153, .8)'
    ctx.shadowBlur = 10
    ctx.fill()
    ctx.restore()
  }

  if (props.stale) {
    ctx.fillStyle = 'rgba(7, 13, 22, 0.55)'
    ctx.fillRect(0, 0, w, h)
    ctx.fillStyle = '#ffb020'
    ctx.font = 'bold 15px sans-serif'
    ctx.fillText('数据过期', w / 2 - 32, 26)
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
  const next = Math.min(4, Math.max(0.5, scale * factor))
  const real = next / scale
  offsetX = mx - (mx - offsetX) * real
  offsetY = my - (my - offsetY) * real
  scale = next
  draw()
}

function onDown(e: MouseEvent) {
  dragging = true
  lastX = e.clientX
  lastY = e.clientY
}
function onMove(e: MouseEvent) {
  if (!dragging) return
  offsetX += e.clientX - lastX
  offsetY += e.clientY - lastY
  lastX = e.clientX
  lastY = e.clientY
  draw()
}
function onUp() { dragging = false }

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
      @mouseleave="onUp"
    />
    <div class="hint muted">滚轮缩放 · 拖拽平移</div>
  </div>
</template>

<style scoped>
.map-wrap { position: relative; width: 100%; height: 100%; min-height: 320px; }
canvas { width: 100%; height: 100%; display: block; cursor: grab; }
.hint { position: absolute; right: 10px; bottom: 6px; font-size: 11px; }
</style>
