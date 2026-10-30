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
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { api } from '@/api'
import { useRobotStore } from '@/stores/robot'
import { toast } from '@/composables/useToast'

const props = defineProps<{ compact?: boolean }>()
const robot = useRobotStore()
const box = ref<HTMLDivElement | null>(null)
const fps = ref(0)
const wallsOn = ref(true)
const pointsOn = ref(true)
const alarmsOn = ref(true)
const height = ref(2.4)
const threshold = ref(90)
const layerOn = ref(true)
const fxOn = ref(true)
const cadMode = ref(true)  // CAD 线框风：黑底 + 细白线 + 等轴测（对齐客户给的 CAD 图）
const fxLabel = ref('光效')
// ---- 轨迹回放 ----
const playHours = ref(24)
const playPoints = ref<{ ts: string; x: number; y: number; theta: number }[]>([])
const playIndex = ref(0)
const playing = ref(false)
const playSpeed = ref(4)
const playTime = ref('')
const playDistance = ref(0)
// 点哪去哪
const gotoHint = ref('')
const planPts = ref<{ x: number; y: number }[]>([])
let targetMark: THREE.Group | null = null
let planLineRef: THREE.Line | null = null
let playTimer = 0
const loading = ref(true)
const err = ref('')
const info = ref({ map: '', points: 0, walls: 0, pose: '' })

let renderer: THREE.WebGLRenderer | null = null
let labelRenderer: CSS2DRenderer | null = null
let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let controls: OrbitControls | null = null
let wallMesh: THREE.InstancedMesh | null = null
let composer: EffectComposer | null = null
let bloomPass: UnrealBloomPass | null = null
let playGroup: THREE.Group | null = null
let playLine: THREE.Line | null = null
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
let heights: Float32Array | null = null
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
    const deviceId = Number(robot.deviceId) || 1
    // 和 2D 地图用同一张图：机器人当前地图优先，平台地图库只作回退。
    // 之前 3D 只读地图库 active（可能是纯白占位图），导致 3D 没墙、点位也对不上。
    let mapName = robot.currentMap || ''
    let m: any = null
    let imageUrl = ''
    let pointRows: any[] = []
    const robotMaps = (await api.maps(deviceId).catch(() => [])) as unknown as any[]
    const mapRows = Array.isArray(robotMaps) ? robotMaps : ((robotMaps as any).items ?? [])
    m = mapRows.find((x: any) => x.name === mapName) ?? mapRows[0] ?? null
    if (m) {
      mapName = m.name
      meta = {
        res: Number(m.resolution) || 0.05,
        ox: Number(m.origin?.[0] ?? 0),
        oy: Number(m.origin?.[1] ?? 0),
        w: Number(m.width) || 900,
        h: Number(m.height) || 600,
      }
      imageUrl = api.mapPng(deviceId, mapName)
      const nav = await api.navPoints(deviceId, mapName, '').catch(() => ({ points: [] as any[] }))
      pointRows = (nav as any).points ?? []
    } else {
      // 回退：平台地图库（没有机器人地图时）
      const maps = await api.libraryMaps()
      const rows = (maps as unknown as { items?: any[] }).items ?? (maps as unknown as any[])
      m = rows.find((x: any) => x.is_active) ?? rows[0]
      if (!m) throw new Error('没有地图：机器人没上报地图，平台地图库也是空的')
      mapName = m.name
      meta = {
        res: Number(m.resolution) || 0.05,
        ox: Number(m.origin_x) || 0,
        oy: Number(m.origin_y) || 0,
        w: Number(m.width) || 900,
        h: Number(m.height) || 600,
      }
      imageUrl = api.libraryImageUrl(m.id)
      const pts = await api.libraryPoints(m.id)
      pointRows = (pts as unknown as { items?: any[] }).items ?? (pts as unknown as any[])
    }
    info.value.map = `${mapName}（${meta.w}×${meta.h} @ ${meta.res}m/px）`
    info.value.points = pointRows.length

    const img = await loadImage(imageUrl)
    const canvas = document.createElement('canvas')
    canvas.width = img.width
    canvas.height = img.height
    const ctx = canvas.getContext('2d')!
    ctx.drawImage(img, 0, 0)
    const data = ctx.getImageData(0, 0, img.width, img.height).data
    gridData = { data, w: img.width, h: img.height }

    // ---------- 场景 ----------
    scene = new THREE.Scene()
    scene.background = new THREE.Color(0x000000)
    scene.fog = new THREE.FogExp2(0x050810, 0.012)

    const worldW = meta.w * meta.res
    const worldH = meta.h * meta.res
    const cx = meta.ox + worldW / 2
    const cy = meta.oy + worldH / 2

    camera = new THREE.PerspectiveCamera(50, box.value.clientWidth / box.value.clientHeight, 0.1, 500)
    camera.position.set(cx, Math.max(worldW, worldH) * 0.95, cy + Math.max(worldW, worldH) * 0.9)

    renderer = new THREE.WebGLRenderer({
      antialias: !props.compact,
      powerPreference: 'high-performance',
    })
    // 首页小窗默认不开抗锯齿、像素比压到 1：拖拽要跟手，画质够看
    renderer.setPixelRatio(props.compact ? 1 : Math.min(window.devicePixelRatio, 1.5))
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
    ground.userData.isGround = true
    ground.rotation.x = -Math.PI / 2
    ground.position.set(cx, -0.01, cy)
    ground.visible = !cadMode.value
    scene.add(ground)

    const grid = new THREE.GridHelper(Math.max(worldW, worldH), Math.round(Math.max(worldW, worldH)), cadMode.value ? 0x1d2a33 : 0x0a4a6a, cadMode.value ? 0x11181d : 0x072434)
    grid.position.set(cx, 0.005, cy)
    ;(grid.material as THREE.Material).transparent = true
    ;(grid.material as THREE.Material).opacity = 0.55
    scene.add(grid)
    // CAD 风的坐标轴标记（原点 X/Y），对齐客户 CAD 图左下角的 X 标记
    const axes = new THREE.AxesHelper(5)
    axes.position.set(meta.ox, 0.02, meta.oy)
    axes.name = 'axes'
    axes.visible = cadMode.value
    scene.add(axes)

    // 后处理：Bloom（半分辨率）+ 扫描线；低端机可一键关
    composer = new EffectComposer(renderer)
    composer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5))
    composer.setSize(box.value.clientWidth, box.value.clientHeight)
    composer.addPass(new RenderPass(scene, camera))
    bloomPass = new UnrealBloomPass(
      new THREE.Vector2(box.value.clientWidth / 2, box.value.clientHeight / 2), 0.6, 0.4, 0.7)
    composer.addPass(bloomPass)
    const scan = new ShaderPass({
      uniforms: { tDiffuse: { value: null }, time: { value: 0 } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }',
      fragmentShader: `uniform sampler2D tDiffuse; uniform float time; varying vec2 vUv;
        void main(){ vec4 c = texture2D(tDiffuse, vUv);
          c.rgb += 0.028 * sin(vUv.y * 900.0 + time * 2.0);
          gl_FragColor = c; }`,
    })
    composer.addPass(scan)
    composer.addPass(new OutputPass())

    buildWalls(data, img.width, img.height)
    buildPoints(pointRows)
    buildRobot()
    buildTrail()
    updateAlarms(robot.alarms)
    setCadMode(cadMode.value)   // 初始应用一次 CAD 模式（隐藏轨迹/贴图）
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
      if (n >= 1) clean[row * w + col] = 1
    }
  }
  // 3) 去孤立点：邻居为 0 的格子不建墙（1px 墙线要保留，所以阈值从 2 降到 1）
  const keep: [number, number][] = []
  for (let row = 1; row < h - 1; row++) {
    for (let col = 1; col < w - 1; col++) {
      if (!clean[row * w + col]) continue
      const n = clean[row * w + col - 1] + clean[row * w + col + 1]
        + clean[(row - 1) * w + col] + clean[(row + 1) * w + col]
      if (n >= 1) keep.push([col, row])
    }
  }

  const step = 2
  const cells: [number, number][] = []
  for (const [col, row] of keep) {
    if (col % step === 0 && row % step === 0) cells.push([col, row])
  }
  // 局部密度：5x5 内占据格越多越"厚"，给不同高度（建筑高、围墙中、栏杆矮）
  const density = (col: number, row: number): number => {
    let n = 0
    for (let dr = -2; dr <= 2; dr += 1) {
      for (let dc = -2; dc <= 2; dc += 1) {
        const c = col + dc
        const r = row + dr
        if (c >= 0 && r >= 0 && c < w && r < h && clean[r * w + c]) n += 1
      }
    }
    return n
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
  heights = new Float32Array(cells.length)
  wallCount = cells.length
  info.value.walls = cells.length
  wallMesh = new THREE.InstancedMesh(boxGeo, mat, cells.length)
  wallBase = new Float32Array(cells.length * 2)
  const dummy = new THREE.Object3D()
  cells.forEach(([col, row], i) => {
    const [x, y] = pxToWorld(col, row)
    wallBase![i * 2] = x
    wallBase![i * 2 + 1] = y
    const n = density(col, row)
    // 5x5 里 25 格：<=7 稀疏（栏杆/设备边），8-16 墙，>16 实心块/建筑
    const ratio = layerOn.value ? (n <= 7 ? 0.35 : n <= 16 ? 0.75 : 1.0) : 1.0
    const h = height.value * ratio
    heights![i] = h
    dummy.position.set(x, h / 2, y)
    dummy.scale.set(1, h, 1)
    dummy.updateMatrix()
    wallMesh!.setMatrixAt(i, dummy.matrix)
  })
  wallMesh.instanceMatrix.needsUpdate = true
  mat.visible = !cadMode.value          // CAD 模式只要线框，不要面
  wallMesh.visible = wallsOn.value
  scene.add(wallMesh)

  const edgeGeo = new THREE.EdgesGeometry(boxGeo)
  const edgeMat = new THREE.LineBasicMaterial({
    color: cadMode.value ? 0xdfe9ef : 0x3ee0ff,
    transparent: true,
    opacity: cadMode.value ? 0.95 : 0.5,
  })
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
    ring.visible = !cadMode.value
    g.add(ring)
    const pole = new THREE.Mesh(
      new THREE.CylinderGeometry(0.012, 0.012, 0.9, 6),
      new THREE.MeshBasicMaterial({ color: 0x37d6ff, transparent: true, opacity: 0.7 }),
    )
    pole.position.y = 0.45
    pole.visible = !cadMode.value
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
  const recent = (list ?? []).slice(0, props.compact ? 2 : 6)
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
    if (!props.compact) {
      const lbl = new CSS2DObject(label(a.message.slice(0, 16), a.level === 'critical' ? 'danger' : 'warn'))
      lbl.position.set(ax, 2.6, ay)
      alarmGroup!.add(lbl)
    }
  })
  scene.add(alarmGroup)
}

let lastTick = performance.now()
let frames = 0
let lowFpsSamples = 0
let fxAutoDisabled = false
function loop() {
  if (!alive) return
  raf = requestAnimationFrame(loop)
  const now = performance.now()
  frames++
  if (now - lastTick > 500) {
    fps.value = Math.round((frames * 1000) / (now - lastTick))
    frames = 0
    lastTick = now
    // 低端机保护：连续偏低就自动关光效（可手动再开）
    if (fxOn.value && !fxAutoDisabled && fps.value > 0 && fps.value < 20) {
      lowFpsSamples += 1
      if (lowFpsSamples >= 6) {
        fxOn.value = false
        fxAutoDisabled = true
        toast('检测到帧率偏低，已自动关闭光效（可在底部重新打开）', 'warn', 5000)
      }
    } else if (fps.value >= 20) {
      lowFpsSamples = 0
    }
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

  if (playing.value && playPoints.value.length > 1) {
    // 每帧推进：playSpeed 个采样点/秒（采样约 1 点/秒）
    const step = playSpeed.value / 60
    playIndex.value += step
    if (playIndex.value >= playPoints.value.length - 1) {
      playIndex.value = playPoints.value.length - 1
      playing.value = false
    }
    applyPlayIndex()
  }

  if (fxOn.value && composer) {
    const scan = composer.passes.find((p) => (p as ShaderPass).uniforms?.time)
    if (scan) (scan as ShaderPass).uniforms.time.value = now / 1000
    composer.render()
  } else if (renderer && scene && camera) {
    renderer.render(scene, camera)
  }
  if (labelRenderer && scene && camera) labelRenderer.render(scene, camera)
}

async function loadPlayback() {
  try {
    const r = await api.telemetryPoses(Number(robot.deviceId), playHours.value, 1200)
    playPoints.value = r.points || []
    playDistance.value = r.distance_m || 0
    playIndex.value = 0
    playing.value = false
    drawPlayback()
    if (!playPoints.value.length) toast('这段时间没有历史位姿（车端未上报或已被清理）', 'warn', 4000)
    else toast(`已加载 ${playPoints.value.length} 个历史点，共 ${r.distance_m} 米`, 'ok', 3000)
  } catch (e) {
    toast(e instanceof Error ? e.message : '加载轨迹失败', 'danger')
  }
}

function drawPlayback() {
  if (!scene) return
  if (playGroup) {
    scene.remove(playGroup)
    playGroup.traverse((o) => (o as THREE.Mesh).geometry?.dispose?.())
  }
  playGroup = new THREE.Group()

  // 历史轨迹线（青色，与实时橙色轨迹区分）
  if (playPoints.value.length > 1) {
    const arr = new Float32Array(playPoints.value.length * 3)
    playPoints.value.forEach((p, i) => {
      arr[i * 3] = p.x
      arr[i * 3 + 1] = 0.08
      arr[i * 3 + 2] = p.y
    })
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(arr, 3))
    playLine = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0x28e0c8, transparent: true, opacity: 0.85 }))
    playLine.frustumCulled = false
    playGroup.add(playLine)
  }

  // 回放标记（线框方块，和实时机器人区分）
  const ghost = new THREE.Mesh(
    new THREE.BoxGeometry(0.9, 0.45, 1.15),
    new THREE.MeshBasicMaterial({ color: 0x28e0c8, wireframe: true, transparent: true, opacity: 0.95 }),
  )
  ghost.name = 'ghost'
  const g = new THREE.Group()
  g.name = 'ghostGroup'
  g.add(ghost)
  const nose = new THREE.Mesh(
    new THREE.ConeGeometry(0.14, 0.36, 10),
    new THREE.MeshBasicMaterial({ color: 0x9ffff2 }),
  )
  nose.rotation.z = -Math.PI / 2
  nose.position.set(0.68, 0, 0)
  g.add(nose)
  playGroup.add(g)
  scene.add(playGroup)
  applyPlayIndex()
}

function applyPlayIndex() {
  if (!playGroup) return
  const g = playGroup.getObjectByName('ghostGroup') as THREE.Group | undefined
  const pts = playPoints.value
  if (!g || !pts.length) return
  const p = pts[Math.floor(Math.min(playIndex.value, pts.length - 1))]
  g.position.set(p.x, 0.25, p.y)
  g.rotation.y = -p.theta
  playTime.value = p.ts.replace('T', ' ')
}

function togglePlay() {
  playing.value = !playing.value
  if (playing.value && !playPoints.value.length) void loadPlayback()
  if (playing.value && playIndex.value >= playPoints.value.length - 1) playIndex.value = 0
}

function screenToGround(ev: MouseEvent): { x: number; y: number } | null {
  if (!renderer || !camera) return null
  const rect = renderer.domElement.getBoundingClientRect()
  const ndc = new THREE.Vector2(
    ((ev.clientX - rect.left) / rect.width) * 2 - 1,
    -((ev.clientY - rect.top) / rect.height) * 2 + 1,
  )
  const ray = new THREE.Raycaster()
  ray.setFromCamera(ndc, camera)
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
  const hit = new THREE.Vector3()
  if (!ray.ray.intersectPlane(plane, hit)) return null
  return { x: hit.x, y: hit.z }
}

// 点哪去哪：只有"点一下"才算，拖拽旋转/平移不能弹确认框
let downAt: { x: number; y: number } | null = null

function onStageDown(ev: PointerEvent) {
  downAt = { x: ev.clientX, y: ev.clientY }
}

async function onStageClick(ev: MouseEvent) {
  if (!downAt) return
  const moved = Math.hypot(ev.clientX - downAt.x, ev.clientY - downAt.y)
  downAt = null
  if (moved > 6) return            // 拖拽，不当作点击
  const p = screenToGround(ev)
  if (!p) return
  const pose = robot.pose as { x?: number; y?: number } | null
  const dist = pose?.x != null ? Math.hypot(p.x - Number(pose.x), p.y - Number(pose.y)) : null
  gotoHint.value = `目标 ${p.x.toFixed(2)}, ${p.y.toFixed(2)}` + (dist ? `（${dist.toFixed(1)}m）` : '')
  showTarget(p.x, p.y, pose)
  if (!window.confirm(`让机器人去 ${p.x.toFixed(2)}, ${p.y.toFixed(2)}？` +
                      (dist ? `\n距离约 ${dist.toFixed(1)} 米` : ''))) return
  try {
    await api.robotGoto(Number(robot.deviceId), { x: p.x, y: p.y, yaw: 0 })
    toast('已下发，机器人开始前往', 'ok', 4000)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    if (msg.includes('确认') || msg.includes('NEED_CONFIRM')) {
      if (window.confirm(`距离较远（${dist?.toFixed(1) ?? '?'}m），确认派车？`)) {
        try {
          await api.robotGoto(Number(robot.deviceId), { x: p.x, y: p.y, yaw: 0, confirmed: true })
          toast('已下发（已二次确认）', 'ok', 4000)
          return
        } catch (e2) {
          toast(e2 instanceof Error ? e2.message : '下发失败', 'danger')
          return
        }
      }
    } else {
      toast(msg, 'danger', 6000)
    }
  }
}

function showTarget(x: number, y: number, pose: { x?: number; y?: number } | null) {
  if (!scene) return
  if (targetMark) {
    scene.remove(targetMark)
    targetMark.traverse((o) => (o as THREE.Mesh).geometry?.dispose?.())
  }
  targetMark = new THREE.Group()
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(0.35, 0.5, 28),
    new THREE.MeshBasicMaterial({ color: 0xffd166, side: THREE.DoubleSide, transparent: true, opacity: 0.95 }),
  )
  ring.rotation.x = -Math.PI / 2
  ring.position.set(x, 0.05, y)
  targetMark.add(ring)
  const pole = new THREE.Mesh(
    new THREE.CylinderGeometry(0.02, 0.02, 2.2, 8),
    new THREE.MeshBasicMaterial({ color: 0xffd166, transparent: true, opacity: 0.65 }),
  )
  pole.position.set(x, 1.1, y)
  targetMark.add(pole)
  if (pose?.x != null && pose?.y != null) {
    const geo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(Number(pose.x), 0.1, Number(pose.y)),
      new THREE.Vector3(x, 0.1, y),
    ])
    const line = new THREE.Line(geo, new THREE.LineDashedMaterial({
      color: 0xffd166, dashSize: 0.35, gapSize: 0.25, transparent: true, opacity: 0.9,
    }))
    line.computeLineDistances()
    targetMark.add(line)
  }
  scene.add(targetMark)
}

async function loadPlan() {
  try {
    const runs = await api.taskRuns({ status: 'running', limit: 1 })
    const rows = (runs as unknown as { items?: any[] }).items ?? (runs as unknown as any[])
    const run = rows[0]
    if (!run) return
    const detail = await api.taskRun(run.id)
    const steps = (detail as unknown as { steps?: any[] }).steps ?? []
    const maps = await api.libraryMaps()
    const mapRows = (maps as unknown as { items?: any[] }).items ?? (maps as unknown as any[])
    const mid = mapRows.find((m: any) => m.is_active)?.id ?? mapRows[0]?.id
    if (!mid) return
    const pts = await api.libraryPoints(mid)
    const ptRows = (pts as unknown as { items?: any[] }).items ?? (pts as unknown as any[])
    const byId = new Map<number, any>(ptRows.map((p: any) => [p.id, p]))
    planPts.value = steps
      .map((s) => byId.get(s.point_id))
      .filter(Boolean)
      .map((p: any) => ({ x: Number(p.x), y: Number(p.y) }))
    drawPlan()
  } catch { /* 没有运行中任务就不画 */ }
}

function drawPlan() {
  if (!scene) return
  if (planLineRef) {
    scene.remove(planLineRef)
    planLineRef.geometry.dispose()
    ;(planLineRef.material as THREE.Material).dispose()
    planLineRef = null
  }
  if (planPts.value.length < 2) return
  const arr: THREE.Vector3[] = planPts.value.map((p) => new THREE.Vector3(p.x, 0.12, p.y))
  const geo = new THREE.BufferGeometry().setFromPoints(arr)
  planLineRef = new THREE.Line(geo, new THREE.LineDashedMaterial({
    color: 0x66d9ff, dashSize: 0.5, gapSize: 0.3, transparent: true, opacity: 0.9,
  }))
  planLineRef.computeLineDistances()
  planLineRef.frustumCulled = false
  scene.add(planLineRef)
}

function applyHeight() {
  if (!wallMesh || !wallBase) return
  const dummy = new THREE.Object3D()
  for (let i = 0; i < wallCount; i++) {
    const x = wallBase[i * 2]
    const y = wallBase[i * 2 + 1]
    const ratio = heights && heights[i] ? heights[i] / 2.4 : 1
    const h = height.value * Math.min(1, Math.max(0.3, ratio))
    dummy.position.set(x, h / 2, y)
    dummy.scale.set(1, h, 1)
    dummy.updateMatrix()
    wallMesh.setMatrixAt(i, dummy.matrix)
  }
  wallMesh.instanceMatrix.needsUpdate = true
}

function isometricCamera() {
  if (!camera || !controls) return
  const worldW = meta.w * meta.res
  const worldH = meta.h * meta.res
  const cx = meta.ox + worldW / 2
  const cy = meta.oy + worldH / 2
  const d = Math.max(worldW, worldH)
  camera.position.set(cx + d * 0.75, d * 0.72, cy + d * 0.75)
  controls.target.set(cx, 0, cy)
  controls.update()
}

function setCadMode(on: boolean) {
  cadMode.value = on
  if (!scene) return
  scene.background = new THREE.Color(on ? 0x000000 : 0x050810)
  scene.fog = on ? null : new THREE.FogExp2(0x050810, 0.012)
  if (wallMesh) (wallMesh.material as THREE.Material).visible = !on
  if (wallEdges) {
    const m = wallEdges.material as THREE.LineBasicMaterial
    m.color.set(on ? 0xdfe9ef : 0x3ee0ff)
    m.opacity = on ? 0.95 : 0.5
  }
  const ground = scene.children.find((o) => o.userData.isGround) as THREE.Mesh | undefined
  if (ground) ground.visible = !on
  const axes = scene.getObjectByName('axes')
  if (axes) axes.visible = on
  // CAD 模式下隐藏轨迹/回放，保持工程图干净
  if (playGroup) playGroup.visible = !on
  if (trail) trail.visible = !on
  pointGroup?.traverse((o) => {
    const mesh = o as THREE.Mesh
    if (mesh.geometry?.type === 'RingGeometry' || mesh.geometry?.type === 'CylinderGeometry') {
      mesh.visible = !on
    }
  })
  if (on) isometricCamera()
  else resetCamera()
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
  composer?.setSize(w, h)
  labelRenderer.setSize(w, h)
}

onMounted(async () => {
  robot.setDevice(robot.deviceId)
  robot.startWs()
  if (!props.compact) void loadPlayback()
  void loadPlan()
  await build()
  // 必须在 build() 之后绑：renderer 是 build 里才创建的，之前绑会静默失败
  if (renderer) {
    renderer.domElement.addEventListener('pointerdown', onStageDown)
    renderer.domElement.addEventListener('click', onStageClick)
  }
  updateAlarms(robot.alarms)
  window.addEventListener('resize', onResize)
  toast('拖动旋转、滚轮缩放；机器人位姿每秒刷新并做插值', 'ok', 3500)
})

onBeforeUnmount(() => {
  alive = false
  robot.stopWs()
  cancelAnimationFrame(raf)
  window.removeEventListener('resize', onResize)
  renderer?.domElement.removeEventListener('pointerdown', onStageDown)
  renderer?.domElement.removeEventListener('click', onStageClick)
  window.clearInterval(playTimer)
  controls?.dispose()
  renderer?.dispose()
  if (renderer?.domElement.parentElement) renderer.domElement.remove()
  if (labelRenderer?.domElement.parentElement) labelRenderer.domElement.remove()
})
</script>

<template>
  <div class="twin" :class="{ compact: props.compact }">
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
      <div v-if="!props.compact" class="ctrl">
        <label><input v-model="wallsOn" type="checkbox" @change="(wallMesh && (wallMesh.visible = wallsOn)) || (wallEdges && (wallEdges.visible = wallsOn))" /> 墙体</label>
        <label><input v-model="pointsOn" type="checkbox" @change="pointGroup && (pointGroup.visible = pointsOn)" /> 点位</label>
        <label><input v-model="alarmsOn" type="checkbox" @change="alarmGroup && (alarmGroup.visible = alarmsOn)" /> 告警</label>
        <label class="range">墙高 {{ height.toFixed(1) }}m
          <input v-model.number="height" type="range" min="0.5" max="5" step="0.1" @input="applyHeight" />
        </label>
        <label class="range">阈值 {{ threshold }}
          <input v-model.number="threshold" type="range" min="40" max="170" step="5" @change="rebuildWalls" />
        </label>
        <label><input v-model="cadMode" type="checkbox" @change="setCadMode(cadMode)" /> CAD 线框</label>
        <label><input v-model="layerOn" type="checkbox" @change="rebuildWalls" /> 高度分层</label>
        <label><input v-model="fxOn" type="checkbox" /> 光效</label>
        <button class="btn btn-xs" @click="resetCamera">复位视角</button>
      </div>

      <div v-if="!props.compact" class="play">
        <span class="tag">轨迹回放</span>
        <select v-model.number="playHours" @change="loadPlayback">
          <option :value="1">最近 1 小时</option>
          <option :value="6">最近 6 小时</option>
          <option :value="24">最近 24 小时</option>
          <option :value="72">最近 3 天</option>
        </select>
        <button class="btn btn-xs primary" @click="togglePlay">{{ playing ? '暂停' : '播放' }}</button>
        <input class="slider" type="range" min="0" :max="Math.max(0, playPoints.length - 1)"
               step="1" v-model.number="playIndex" @input="applyPlayIndex" />
        <span class="mono">{{ playTime || '—' }}</span>
        <span class="mono">{{ playPoints.length }} 点 / {{ playDistance }} m</span>
        <select v-model.number="playSpeed">
          <option :value="1">1×</option>
          <option :value="4">4×</option>
          <option :value="10">10×</option>
          <option :value="30">30×</option>
        </select>
        <button class="btn btn-xs" @click="loadPlayback">刷新</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.twin { position: absolute; inset: 0; }
.twin.compact { position: relative; height: 100%; }
.twin.compact .hud { font-size: 10px; padding: 4px 8px; gap: 8px; }
.stage { position: relative; width: 100%; height: 100%; background: #050810; overflow: hidden; }
.hud {
  position: absolute; left: 14px; top: 12px; display: flex; gap: 14px; align-items: center;
  padding: 7px 12px; border-radius: 8px; background: rgba(5, 12, 20, .72);
  border: 1px solid rgba(0, 168, 255, .28); color: #8fd8ff; font-size: 12px; letter-spacing: .4px;
  pointer-events: none;   /* HUD 不挡拖拽旋转 */
}
.ctrl {
  position: absolute; left: 14px; bottom: 14px; display: flex; gap: 14px; align-items: center;
  padding: 8px 12px; border-radius: 8px; background: rgba(5, 12, 20, .72);
  border: 1px solid rgba(0, 168, 255, .28); color: #9fd6ee; font-size: 12px;
}
.ctrl label { display: flex; align-items: center; gap: 5px; cursor: pointer; }
.play {
  position: absolute; left: 14px; right: 14px; bottom: 58px;
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  padding: 8px 12px; border-radius: 8px; background: rgba(5, 12, 20, .78);
  border: 1px solid rgba(40, 224, 200, .35); color: #a9e8dd; font-size: 12px;
}
.play .tag { color: #28e0c8; }
.play select, .play .btn { font-size: 12px; }
.play .slider { flex: 1; min-width: 180px; accent-color: #28e0c8; }
.play .mono { font-family: ui-monospace, Consolas, monospace; opacity: .9; }
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
