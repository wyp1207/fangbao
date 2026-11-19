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
  /** 深色大屏模式：底图反色成黑底青灰栅格（浅色 SLAM 图直接贴会刺眼） */
  dark?: boolean
}>()

const canvas = ref<HTMLCanvasElement | null>(null)
const wrap = ref<HTMLDivElement | null>(null)
const hover = ref<{ x: number; y: number } | null>(null)
const showPoints = ref(true)
const showLabels = ref(false)
const showTrail = ref(true)
const hoverPoint = ref<number | null>(null)
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

function hitPoint(sx: number, sy: number): number | null {
  if (!showPoints.value) return null
  for (let i = props.points.length - 1; i >= 0; i--) {
    const [px, py] = worldToPixel(props.points[i].x, props.points[i].y)
    const dx = offsetX + px * scale - sx
    const dy = offsetY + py * scale - sy
    if (dx * dx + dy * dy <= 144) return i
  }
  return null
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
  ctx.fillStyle = props.dark ? '#040a14' : '#dbe4ee'
  ctx.fillRect(0, 0, w, h)

  if (!img || !ready) {
    ctx.fillStyle = '#9aa8b8'
    ctx.font = '13px "PingFang SC", "Microsoft YaHei", sans-serif'
    ctx.fillText('地图加载中…', 20, 28)
    return
  }

  // 底图：深色模式下反色成黑底青灰栅格，浅色模式只做轻微提亮
  ctx.save()
  ctx.translate(offsetX, offsetY)
  ctx.scale(scale, scale)
  if (props.dark) ctx.filter = 'invert(1) hue-rotate(172deg) saturate(0.55) brightness(1.25)'
  ctx.drawImage(img, 0, 0)
  ctx.filter = 'none'
  ctx.fillStyle = props.dark ? 'rgba(4, 10, 20, 0.18)' : 'rgba(255, 255, 255, 0.05)'
  ctx.fillRect(0, 0, img.width, img.height)
  ctx.restore()

  // 轨迹
  if (showTrail.value && props.trail?.length) {
    ctx.beginPath()
    props.trail.forEach((t, i) => {
      const [px, py] = worldToPixel(t.x, t.y)
      const sx = offsetX + px * scale
      const sy = offsetY + py * scale
      if (i === 0) ctx.moveTo(sx, sy)
      else ctx.lineTo(sx, sy)
    })
    ctx.strokeStyle = props.dark ? 'rgba(41, 212, 255, 0.55)' : 'rgba(22, 119, 255, 0.35)'
    if (props.dark) ctx.setLineDash([6, 5])
    ctx.lineWidth = 1.6
    ctx.lineJoin = 'round'
    ctx.stroke()
    ctx.setLineDash([])
  }

  // 点位：编号 + 状态色；标签默认收起，悬停才显示，避免满屏文字
  if (showPoints.value) {
    props.points.forEach((p, i) => {
      const [px, py] = worldToPixel(p.x, p.y)
      const sx = offsetX + px * scale
      const sy = offsetY + py * scale
      const hot = hoverPoint.value === i
      const r = hot ? 9 : 7
      ctx.beginPath()
      ctx.arc(sx, sy, r, 0, Math.PI * 2)
      ctx.fillStyle = hot ? 'rgba(41, 212, 255, 0.35)' : props.dark ? 'rgba(41, 212, 255, 0.18)' : 'rgba(22, 119, 255, 0.14)'
      ctx.fill()
      ctx.beginPath()
      ctx.arc(sx, sy, hot ? 9.5 : 7.5, 0, Math.PI * 2)
      ctx.strokeStyle = hot ? '#29d4ff' : props.dark ? 'rgba(41,212,255,.55)' : 'rgba(22,119,255,.45)'
      ctx.lineWidth = 1
      ctx.stroke()
      ctx.beginPath()
      ctx.arc(sx, sy, 5, 0, Math.PI * 2)
      ctx.fillStyle = props.dark ? '#0a2036' : '#ffffff'
      ctx.fill()
      ctx.fillStyle = props.dark ? '#8fe7ff' : '#1677ff'
      ctx.font = 'bold 8px "PingFang SC", "Microsoft YaHei", sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(String(i + 1), sx, sy + 0.5)
      ctx.textAlign = 'start'
      ctx.textBaseline = 'alphabetic'

      if (showLabels.value || hot) {
        // 真机点位可能没有 name：回退成编号名，和右侧「巡检点位」列表保持一致
        const label = p.name || `点位 ${String(i + 1).padStart(2, '0')}`
        ctx.font = '11px "PingFang SC", "Microsoft YaHei", sans-serif'
        const tw = ctx.measureText(label).width
        ctx.fillStyle = props.dark ? 'rgba(6, 14, 26, 0.92)' : 'rgba(255, 255, 255, 0.94)'
        ctx.fillRect(sx + 11, sy - 18, tw + 10, 17)
        ctx.strokeStyle = props.dark ? 'rgba(41,212,255,.35)' : 'rgba(22,119,255,.25)'
        ctx.strokeRect(sx + 11, sy - 18, tw + 10, 17)
        ctx.fillStyle = props.dark ? '#d9f4ff' : '#334155'
        ctx.fillText(label, sx + 16, sy - 6)
      }
    })
  }

  // 机器人
  const pose = props.pose
  if (pose && typeof pose.x === 'number' && typeof pose.y === 'number') {
    const [px, py] = worldToPixel(pose.x, pose.y)
    const sx = offsetX + px * scale
    const sy = offsetY + py * scale
    const color = props.stale ? '#7e8ca3' : props.dark ? '#29d4ff' : '#1677ff'

    ctx.beginPath()
    ctx.arc(sx, sy, 13, 0, Math.PI * 2)
    ctx.fillStyle = props.stale
      ? 'rgba(126, 140, 163, 0.15)'
      : props.dark ? 'rgba(41, 212, 255, 0.16)' : 'rgba(22, 119, 255, 0.12)'
    ctx.fill()

    ctx.save()
    ctx.translate(sx, sy)
    ctx.rotate(-(pose.theta_rad ?? 0))
    // 朝向扇形：一眼看出车头朝哪，而不是只有一个三角
    const beam = ctx.createLinearGradient(0, 0, 46, 0)
    beam.addColorStop(0, props.dark ? 'rgba(41,212,255,.28)' : 'rgba(22,119,255,.20)')
    beam.addColorStop(1, 'rgba(41,212,255,0)')
    ctx.beginPath()
    ctx.moveTo(0, 0)
    ctx.arc(0, 0, 46, -0.42, 0.42)
    ctx.closePath()
    ctx.fillStyle = beam
    ctx.fill()
    ctx.beginPath()
    ctx.moveTo(10, 0)
    ctx.lineTo(-6.5, 6)
    ctx.lineTo(-6.5, -6)
    ctx.closePath()
    ctx.fillStyle = color
    if (props.dark && !props.stale) {
      ctx.shadowColor = 'rgba(41, 212, 255, 0.9)'
      ctx.shadowBlur = 14
    }
    ctx.fill()
    ctx.restore()
  }

  if (props.stale) {
    ctx.fillStyle = props.dark ? 'rgba(4, 10, 20, 0.55)' : 'rgba(247, 249, 252, 0.55)'
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

const emit = defineEmits<{ pick: [{ x: number; y: number }] }>()

let downAt = 0
let downX = 0
let downY = 0

function onDown(e: MouseEvent) {
  dragging = true
  downAt = Date.now()
  downX = e.clientX
  downY = e.clientY
  lastX = e.clientX
  lastY = e.clientY
}
function onMove(e: MouseEvent) {
  const el = canvas.value
  if (el) {
    const rect = el.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    hover.value = screenToWorld(mx, my)
    // 只在悬停点位变化时重绘，避免鼠标一动就整幅重画
    const nextHot = hitPoint(mx, my)
    if (nextHot !== hoverPoint.value) {
      hoverPoint.value = nextHot
      draw()
    }
  }
  if (!dragging) return
  offsetX += e.clientX - lastX
  offsetY += e.clientY - lastY
  lastX = e.clientX
  lastY = e.clientY
  draw()
}
function onUp(e: MouseEvent) {
  const wasDrag = Math.abs(e.clientX - downX) + Math.abs(e.clientY - downY) > 4
  dragging = false
  // 短按且没怎么移动 = 一次点击，抛坐标给父组件（打点模式用）
  if (!wasDrag && Date.now() - downAt < 400) {
    const el = canvas.value
    if (el) {
      const rect = el.getBoundingClientRect()
      const w = screenToWorld(e.clientX - rect.left, e.clientY - rect.top)
      if (w) emit('pick', w)
    }
  }
}
function onLeave() { dragging = false; hover.value = null; hoverPoint.value = null; draw() }

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
  <div ref="wrap" class="map-wrap" :class="{ dark }">
    <canvas
      ref="canvas"
      @wheel="onWheel"
      @mousedown="onDown"
      @mousemove="onMove"
      @mouseup="onUp"
      @mouseleave="onLeave"
    />

    <div class="hud layers">
      <label><input v-model="showPoints" type="checkbox" @change="draw" />点位</label>
      <label><input v-model="showLabels" type="checkbox" @change="draw" />标签</label>
      <label><input v-model="showTrail" type="checkbox" @change="draw" />轨迹</label>
    </div>

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
.map-wrap.dark {
  background-color: #040a14;
  background-image: radial-gradient(rgba(64, 158, 255, 0.12) 1px, transparent 1px);
  border-color: rgba(64, 158, 255, 0.25);
  border-radius: 2px;
}
.map-wrap.dark .hud {
  background: rgba(8, 18, 34, 0.82);
  border-color: rgba(64, 158, 255, 0.28);
  color: #a9bbd6;
  box-shadow: none;
}
.map-wrap.dark .k.point { background: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2); }
.map-wrap.dark .k.robot { background: #29d4ff; }
.map-wrap.dark .k.trail { border-top-color: rgba(41, 212, 255, 0.55); }
.map-wrap.dark .scalebar i { border-color: #6b7c99; }
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
.legend { top: 52px; left: 12px; }
/* .hud 默认 pointer-events:none（不挡画布拖拽），图层面板必须收回点击能力 */
.layers { top: 12px; left: 12px; gap: 10px; pointer-events: auto; }
.layers label { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; user-select: none; }
.layers label:hover { color: #29d4ff; }
.layers input { accent-color: #29d4ff; margin: 0; cursor: pointer; }
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
