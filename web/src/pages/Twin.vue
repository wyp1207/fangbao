<script setup lang="ts">
/**
 * 三维数字孪生视图（程序化 3D）
 *
 * 为什么这么做：客户参考图是"静态渲染图"，真做场站白模要建模+标定，3 天出不来，
 * 且每换一个场地就要重做。我们的做法是把已有的 SLAM 栅格地图直接拉成 3D：
 * 坐标天然对齐（同一米制坐标系），机器人位姿、点位、告警、轨迹全是真数据驱动。
 * 将来客户给了 GLB 白模，只要换 modelGroup，业务对象一个不用动。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import { api } from '@/api'
import { useRobotStore } from '@/stores/robot'
import { toast } from '@/composables/useToast'

const robot = useRobotStore()
const box = ref<HTMLDivElement | null>(null)
const fps = ref(0)
const wallsOn = ref(true)
const pointsOn = ref(true)
const alarmsOn = ref(true)
const height = ref(2.4)
const threshold = ref(60)
const loading = ref(true)
const err = ref('')
const info = ref({ map: '', points: 0, walls: 0, pose: '' })

let renderer: THREE.WebGLRenderer | null = null
let labelRenderer: CSS2DRenderer | null = null
let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let controls: OrbitControls | null = null
let wallMesh: THREE.InstancedMesh | null = null
let pointGroup: THREE.Group | null = null
let alarmGroup: THREE.Group | null = null
let robotGroup: THREE.Group | null = null
let trail: THREE.Line | null = null
let raf = 0
let alive = true

const target = new THREE.Vector3()
const lerpPos = new THREE.Vector3()
const lerpYaw = { v: 0 }
const trailPts: THREE.Vector3[] = []
let wallBase: Float32Array | null = null
let wallEdges: THREE.InstancedMesh | null = null
let gridData: { data: Uint8ClampedArray; w: number; h: number } | null = null
let wallCount = 0
let meta = { res: 0.05, ox: -10, oy: -8, w: 900, h: 600 }

// ---------- 坐标换算：像素 → SLAM 米（注意 PNG 行号向下，SLAM y 向上） ----------
function pxToWorld(col: number, row: number): [number, number] {
  const x = meta.ox + (col + 0.5) * meta.res
  const y = meta.oy + (meta.h - row - 0.5) * meta.res
  return [x, y]
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('地图图片加载失败'))
    img.src = url
  })
}

async function build() {
  if (!box.value) return
  try {
    loading.value = true
    const maps = await api.libraryMaps()
    const rows = (maps as unknown as { items?: any[] }).items ?? (maps as unknown as any[])
    const m = rows.find((x: any) => x.is_active) ?? rows[0]
    if (!m) throw new Error('没有地图，先去地图管理导入')
    meta = {
      res: Number(m.resolution) || 0.05,
      ox: Number(m.origin_x) || 0,
      oy: Number(m.origin_y) || 0,
      w: Number(m.width) || 900,
      h: Number(m.height) || 600,
    }
    info.value.map = `${m.name}（${meta.w}×${meta.h} @ ${meta.res}m/px）`

    const pts = await api.libraryPoints(m.id)
    const pointRows = (pts as unknown as { items?: any[] }).items ?? (pts as unknown as any[])
    info.value.points = pointRows.length

    const img = await loadImage(api.libraryImageUrl(m.id))
    const canvas = document.createElement('canvas')
    canvas.width = img.width
    canvas.height = img.height
    const ctx = canvas.getContext('2d')!
    ctx.drawImage(img, 0, 0)
    const data = ctx.getImageData(0, 0, img.width, img.height).data
    gridData = { data, w: img.width, h: img.height }

    // ---------- 场景 ----------
    scene = new THREE.Scene()
    scene.background = new THREE.Color(0x050810)
    scene.fog = new THREE.FogExp2(0x050810, 0.012)

    const worldW = meta.w * meta.res
    const worldH = meta.h * meta.res
    const cx = meta.ox + worldW / 2
    const cy = meta.oy + worldH / 2

    camera = new THREE.PerspectiveCamera(50, box.value.clientWidth / box.value.clientHeight, 0.1, 500)
    camera.position.set(cx, Math.max(worldW, worldH) * 0.95, cy + Math.max(worldW, worldH) * 0.9)

    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5))
    renderer.setSize(box.value.clientWidth, box.value.clientHeight)
    renderer.shadowMap.enabled = false
    box.value.appendChild(renderer.domElement)

    labelRenderer = new CSS2DRenderer()
    labelRenderer.setSize(box.value.clientWidth, box.value.clientHeight)
    labelRenderer.domElement.style.position = 'absolute'
    labelRenderer.domElement.style.top = '0'
    labelRenderer.domElement.style.pointerEvents = 'none'
    box.value.appendChild(labelRenderer.domElement)

    controls = new OrbitControls(camera, renderer.domElement)
    controls.target.set(cx, 0, cy)
    controls.enableDamping = true
    controls.maxPolarAngle = Math.PI / 2.05
    controls.update()

    scene.add(new THREE.HemisphereLight(0x1a3a5a, 0x050810, 0.9))
    const dir = new THREE.DirectionalLight(0xffffff, 0.7)
    dir.position.set(cx + 20, 30, cy - 10)
    scene.add(dir)

    // 地面 + 网格
    const tex = new THREE.Texture(img)
    tex.needsUpdate = true
    tex.flipY = false
    const groundMat = new THREE.MeshBasicMaterial({
      map: tex, transparent: true, opacity: 0.45,
      color: 0x8fb6d6, depthWrite: false,
    })
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(worldW, worldH), groundMat)
    ground.rotation.x = -Math.PI / 2
    ground.position.set(cx, -0.01, cy)
    scene.add(ground)

    const grid = new THREE.GridHelper(Math.max(worldW, worldH), Math.round(Math.max(worldW, worldH)), 0x0a4a6a, 0x072434)
    grid.position.set(cx, 0.005, cy)
    ;(grid.material as THREE.Material).transparent = true
    ;(grid.material as THREE.Material).opacity = 0.55
    scene.add(grid)

    buildWalls(data, img.width, img.height)
    buildPoints(pointRows)
    buildRobot()
    buildTrail()
    updateAlarms(robot.alarms)
    loop()
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function buildWalls(data: Uint8ClampedArray, w: number, h: number) {
  if (!scene) return
  // 1) 占据判定：阈值可调（豆包：脏栅格是程序化 3D 第一杀手）
  const mask = new Uint8Array(w * h)
  for (let i = 0; i < w * h; i++) {
    const idx = i * 4
    const lum = data[idx] * 0.299 + data[idx + 1] * 0.587 + data[idx + 2] * 0.114
    if (lum < threshold.value) mask[i] = 1
  }
  // 2) 3x3 多数滤波：去掉人影/噪点造成的锯齿墙
  const clean = new Uint8Array(w * h)
  for (let row = 1; row < h - 1; row++) {
    for (let col = 1; col < w - 1; col++) {
      let n = 0
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) n += mask[(row + dr) * w + (col + dc)]
      }
      if (n >= 5) clean[row * w + col] = 1
    }
  }
  // 3) 去孤立点：邻居 < 2 的格子不建墙
  const keep: [number, number][] = []
  for (let row = 1; row < h - 1; row++) {
    for (let col = 1; col < w - 1; col++) {
      if (!clean[row * w + col]) continue
      const n = clean[row * w + col - 1] + clean[row * w + col + 1]
        + clean[(row - 1) * w + col] + clean[(row + 1) * w + col]
      if (n >= 2) keep.push([col, row])
    }
  }

  const step = 2
  const cells: [number, number][] = []
  for (const [col, row] of keep) {
    if (col % step === 0 && row % step === 0) cells.push([col, row])
  }
  if (cells.length > 16000) {
    for (let i = cells.length - 1; i > 0; i -= 2) cells.splice(i, 1)
  }

  // 重建前先清掉旧的墙
  if (wallMesh) {
    scene.remove(wallMesh)
    wallMesh.geometry.dispose()
    ;(wallMesh.material as THREE.Material).dispose()
    wallMesh = null
  }
  if (wallEdges) {
    scene.remove(wallEdges)
    wallEdges.geometry.dispose()
    ;(wallEdges.material as THREE.Material).dispose()
    wallEdges = null
  }

  const boxGeo = new THREE.BoxGeometry(meta.res * step, 1, meta.res * step)
  const mat = new THREE.MeshStandardMaterial({
    color: 0x1d3d59, emissive: 0x0c2940, emissiveIntensity: 0.65,
    roughness: 0.75, metalness: 0.2, transparent: true, opacity: 0.72,
  })
  wallCount = cells.length
  info.value.walls = cells.length
  wallMesh = new THREE.InstancedMesh(boxGeo, mat, cells.length)
  wallBase = new Float32Array(cells.length * 2)
  const dummy = new THREE.Object3D()
  cells.forEach(([col, row], i) => {
    const [x, y] = pxToWorld(col, row)
    wallBase![i * 2] = x
    wallBase![i * 2 + 1] = y
    dummy.position.set(x, height.value / 2, y)
    dummy.scale.set(1, height.value, 1)
    dummy.updateMatrix()
    wallMesh!.setMatrixAt(i, dummy.matrix)
  })
  wallMesh.instanceMatrix.needsUpdate = true
  wallMesh.visible = wallsOn.value
  scene.add(wallMesh)

  const edgeGeo = new THREE.EdgesGeometry(boxGeo)
  const edgeMat = new THREE.LineBasicMaterial({ color: 0x3ee0ff, transparent: true, opacity: 0.5 })
  wallEdges = new THREE.InstancedMesh(edgeGeo as unknown as THREE.BufferGeometry, edgeMat, cells.length)
  cells.forEach((_, i) => {
    const m4 = new THREE.Matrix4()
    wallMesh!.getMatrixAt(i, m4)
    wallEdges!.setMatrixAt(i, m4)
  })
  wallEdges.instanceMatrix.needsUpdate = true
  wallEdges.visible = wallsOn.value
  scene.add(wallEdges)
}

function rebuildWalls() {
  if (gridData) buildWalls(gridData.data, gridData.w, gridData.h)
}

function label(text: string, cls = ''): HTMLDivElement {
  const el = document.createElement('div')
  el.className = `tw-label ${cls}`
  el.textContent = text
  return el
}

function buildPoints(list: any[]) {
  if (!scene) return
  pointGroup = new THREE.Group()
  for (const p of list) {
    const x = Number(p.x)
    const y = Number(p.y)
    const g = new THREE.Group()
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.18, 0.26, 24),
      new THREE.MeshBasicMaterial({ color: 0x37d6ff, side: THREE.DoubleSide, transparent: true, opacity: 0.9 }),
    )
    ring.rotation.x = -Math.PI / 2
    ring.position.y = 0.02
    g.add(ring)
    const pole = new THREE.Mesh(
      new THREE.CylinderGeometry(0.012, 0.012, 0.9, 6),
      new THREE.MeshBasicMaterial({ color: 0x37d6ff, transparent: true, opacity: 0.7 }),
    )
    pole.position.y = 0.45
    g.add(pole)
    const lbl = new CSS2DObject(label(p.name))
    lbl.position.y = 1.15
    g.add(lbl)
    g.position.set(x, 0, y)
    pointGroup.add(g)
  }
  scene.add(pointGroup)
}

function buildRobot() {
  if (!scene) return
  robotGroup = new THREE.Group()
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(0.9, 0.45, 1.15),
    new THREE.MeshStandardMaterial({ color: 0xff7a18, emissive: 0xff5a00, emissiveIntensity: 0.5, metalness: 0.3, roughness: 0.4 }),
  )
  body.position.y = 0.55
  robotGroup.add(body)
  // 朝向箭头（+x 为车头）
  const nose = new THREE.Mesh(
    new THREE.ConeGeometry(0.16, 0.4, 12),
    new THREE.MeshBasicMaterial({ color: 0xffd166 }),
  )
  nose.rotation.z = -Math.PI / 2
  nose.position.set(0.72, 0.55, 0)
  robotGroup.add(nose)
  const beacon = new THREE.Mesh(
    new THREE.CylinderGeometry(0.03, 0.03, 3.2, 8),
    new THREE.MeshBasicMaterial({ color: 0xff9a3c, transparent: true, opacity: 0.5 }),
  )
  beacon.position.y = 1.6
  robotGroup.add(beacon)
  const lbl = new CSS2DObject(label('机器人', 'robot'))
  lbl.position.y = 3.5
  robotGroup.add(lbl)
  const glow = new THREE.Mesh(
    new THREE.CylinderGeometry(0.75, 0.75, 0.02, 28),
    new THREE.MeshBasicMaterial({ color: 0xff7a18, transparent: true, opacity: 0.35 }),
  )
  glow.position.y = 0.01
  robotGroup.add(glow)
  robotGroup.visible = false
  scene.add(robotGroup)
}

function buildTrail() {
  if (!scene) return
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(1500 * 3), 3))
  trail = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0xff9d3c, transparent: true, opacity: 0.75 }))
  trail.frustumCulled = false
  scene.add(trail)
}

function updateAlarms(list: { id: number; message: string; level: string; metric: string }[]) {
  if (!scene) return
  if (alarmGroup) {
    scene.remove(alarmGroup)
    alarmGroup.traverse((o) => {
      const mesh = o as THREE.Mesh
      mesh.geometry?.dispose?.()
    })
  }
  alarmGroup = new THREE.Group()
  const pose = robot.pose as { x?: number; y?: number } | null
  if (pose?.x == null) {
    scene.add(alarmGroup)
    return
  }
  const recent = (list ?? []).slice(0, 6)
  recent.forEach((a, i) => {
    const angle = (i / Math.max(1, recent.length)) * Math.PI * 2
    const ax = Number(pose.x) + Math.cos(angle) * (1.2 + i * 0.4)
    const ay = Number(pose.y) + Math.sin(angle) * (1.2 + i * 0.4)
    const color = a.level === 'critical' ? 0xff3b30 : 0xffb020
    const col = new THREE.Mesh(
      new THREE.CylinderGeometry(0.09, 0.09, 2.4, 10, 1, true),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.55, side: THREE.DoubleSide }),
    )
    col.position.set(ax, 1.2, ay)
    alarmGroup!.add(col)
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.3, 0.42, 28),
      new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, transparent: true, opacity: 0.8 }),
    )
    ring.rotation.x = -Math.PI / 2
    ring.position.set(ax, 0.03, ay)
    alarmGroup!.add(ring)
    const lbl = new CSS2DObject(label(a.message.slice(0, 16), a.level === 'critical' ? 'danger' : 'warn'))
    lbl.position.set(ax, 2.6, ay)
    alarmGroup!.add(lbl)
  })
  scene.add(alarmGroup)
}

let lastTick = performance.now()
let frames = 0
function loop() {
  if (!alive) return
  raf = requestAnimationFrame(loop)
  const now = performance.now()
  frames++
  if (now - lastTick > 500) {
    fps.value = Math.round((frames * 1000) / (now - lastTick))
    frames = 0
    lastTick = now
  }
  controls?.update()

  // 位姿：1Hz 数据 + 插值，避免"瞬移"（GLM 评审的关键建议）
  const pose = robot.pose as { x?: number; y?: number; theta_rad?: number } | null
  if (pose?.x != null && robotGroup) {
    robotGroup.visible = true
    target.set(Number(pose.x), 0, Number(pose.y))
    lerpPos.lerp(target, 0.18)
    robotGroup.position.copy(lerpPos)
    const yaw = Number(pose.theta_rad ?? 0)
    // 平滑角度（处理 ±π 跳变）
    let d = yaw - lerpYaw.v
    while (d > Math.PI) d -= Math.PI * 2
    while (d < -Math.PI) d += Math.PI * 2
    lerpYaw.v += d * 0.2
    robotGroup.rotation.y = -lerpYaw.v
    info.value.pose = `${Number(pose.x).toFixed(2)}, ${Number(pose.y).toFixed(2)}`

    if (trail) {
      const last = trailPts[trailPts.length - 1]
      if (!last || last.distanceTo(lerpPos) > 0.15) {
        trailPts.push(lerpPos.clone())
        if (trailPts.length > 1500) trailPts.shift()
        const arr = (trail.geometry.getAttribute('position') as THREE.BufferAttribute).array as Float32Array
        trailPts.forEach((p, i) => {
          arr[i * 3] = p.x
          arr[i * 3 + 1] = 0.05
          arr[i * 3 + 2] = p.z
        })
        trail.geometry.setDrawRange(0, trailPts.length)
        ;(trail.geometry.getAttribute('position') as THREE.BufferAttribute).needsUpdate = true
      }
    }
  }

  if (alarmGroup) {
    const t = now / 1000
    alarmGroup.children.forEach((o, i) => {
      if ((o as THREE.Mesh).geometry?.type === 'CylinderGeometry') {
        ;(o as THREE.Mesh).scale.x = 1 + 0.25 * Math.sin(t * 3 + i)
        ;(o as THREE.Mesh).scale.z = 1 + 0.25 * Math.sin(t * 3 + i)
      }
    })
  }

  if (renderer && scene && camera) renderer.render(scene, camera)
  if (labelRenderer && scene && camera) labelRenderer.render(scene, camera)
}

function applyHeight() {
  if (!wallMesh || !wallBase) return
  const dummy = new THREE.Object3D()
  for (let i = 0; i < wallCount; i++) {
    const x = wallBase[i * 2]
    const y = wallBase[i * 2 + 1]
    dummy.position.set(x, height.value / 2, y)
    dummy.scale.set(1, height.value, 1)
    dummy.updateMatrix()
    wallMesh.setMatrixAt(i, dummy.matrix)
  }
  wallMesh.instanceMatrix.needsUpdate = true
}

function resetCamera() {
  if (!camera || !controls || !scene) return
  const worldW = meta.w * meta.res
  const worldH = meta.h * meta.res
  const cx = meta.ox + worldW / 2
  const cy = meta.oy + worldH / 2
  camera.position.set(cx, Math.max(worldW, worldH) * 0.95, cy + Math.max(worldW, worldH) * 0.9)
  controls.target.set(cx, 0, cy)
  controls.update()
}

function onResize() {
  if (!box.value || !renderer || !camera || !labelRenderer) return
  const w = box.value.clientWidth
  const h = box.value.clientHeight
  camera.aspect = w / h
  camera.updateProjectionMatrix()
  renderer.setSize(w, h)
  labelRenderer.setSize(w, h)
}

onMounted(async () => {
  robot.setDevice(robot.deviceId)
  robot.startWs()
  await build()
  updateAlarms(robot.alarms)
  window.addEventListener('resize', onResize)
  toast('拖动旋转、滚轮缩放；机器人位姿每秒刷新并做插值', 'ok', 3500)
})

onBeforeUnmount(() => {
  alive = false
  robot.stopWs()
  cancelAnimationFrame(raf)
  window.removeEventListener('resize', onResize)
  controls?.dispose()
  renderer?.dispose()
  if (renderer?.domElement.parentElement) renderer.domElement.remove()
  if (labelRenderer?.domElement.parentElement) labelRenderer.domElement.remove()
})
</script>

<template>
  <div class="twin">
    <div ref="box" class="stage">
      <div v-if="loading" class="hint">正在把栅格地图拉成 3D…</div>
      <div v-if="err" class="hint err">{{ err }}</div>
      <div class="hud">
        <span>地图：{{ info.map || '—' }}</span>
        <span>点位：{{ info.points }} · 墙体：{{ info.walls }}</span>
        <span>位姿：{{ info.pose || '—' }}</span>
        <span>FPS：{{ fps }}</span>
        <span>{{ robot.wsConnected ? 'WS 200ms' : '轮询 1s' }}</span>
      </div>
      <div class="ctrl">
        <label><input v-model="wallsOn" type="checkbox" @change="(wallMesh && (wallMesh.visible = wallsOn)) || (wallEdges && (wallEdges.visible = wallsOn))" /> 墙体</label>
        <label><input v-model="pointsOn" type="checkbox" @change="pointGroup && (pointGroup.visible = pointsOn)" /> 点位</label>
        <label><input v-model="alarmsOn" type="checkbox" @change="alarmGroup && (alarmGroup.visible = alarmsOn)" /> 告警</label>
        <label class="range">墙高 {{ height.toFixed(1) }}m
          <input v-model.number="height" type="range" min="0.5" max="5" step="0.1" @input="applyHeight" />
        </label>
        <label class="range">阈值 {{ threshold }}
          <input v-model.number="threshold" type="range" min="30" max="120" step="5" @change="rebuildWalls" />
        </label>
        <button class="btn btn-xs" @click="resetCamera">复位视角</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.twin { position: absolute; inset: 0; }
.stage { position: relative; width: 100%; height: 100%; background: #050810; overflow: hidden; }
.hud {
  position: absolute; left: 14px; top: 12px; display: flex; gap: 14px; align-items: center;
  padding: 7px 12px; border-radius: 8px; background: rgba(5, 12, 20, .72);
  border: 1px solid rgba(0, 168, 255, .28); color: #8fd8ff; font-size: 12px; letter-spacing: .4px;
}
.ctrl {
  position: absolute; left: 14px; bottom: 14px; display: flex; gap: 14px; align-items: center;
  padding: 8px 12px; border-radius: 8px; background: rgba(5, 12, 20, .72);
  border: 1px solid rgba(0, 168, 255, .28); color: #9fd6ee; font-size: 12px;
}
.ctrl label { display: flex; align-items: center; gap: 5px; cursor: pointer; }
.ctrl .range { gap: 8px; }
.ctrl input[type='range'] { width: 110px; }
.hint {
  position: absolute; inset: 0; display: grid; place-items: center; color: #7fd4ff; font-size: 14px;
  background: rgba(5, 8, 16, .6); pointer-events: none;
}
.hint.err { color: #ff8f8f; }
:deep(.tw-label) {
  color: #bfe9ff; font-size: 11px; padding: 1px 5px; border-radius: 4px;
  background: rgba(3, 18, 30, .72); border: 1px solid rgba(0, 168, 255, .35);
  white-space: nowrap; transform: translateY(-4px);
}
:deep(.tw-label.robot) { color: #ffd9b0; border-color: rgba(255, 140, 40, .7); background: rgba(60, 28, 4, .8); }
:deep(.tw-label.danger) { color: #ffd0cc; border-color: rgba(255, 70, 60, .6); background: rgba(60, 8, 6, .75); }
:deep(.tw-label.warn) { color: #ffe6b8; border-color: rgba(255, 176, 32, .6); background: rgba(50, 34, 4, .75); }
</style>
