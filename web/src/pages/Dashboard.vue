<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import StatusBar from '@/components/StatusBar.vue'
import MapCanvas from '@/components/MapCanvas.vue'
import { useRobotStore } from '@/stores/robot'
import { api, type MapMeta, type NavPoint } from '@/api'

const robot = useRobotStore()
const mapMeta = ref<MapMeta | null>(null)
const points = ref<NavPoint[]>([])
const mapError = ref('')
const trail = ref<{ x: number; y: number }[]>([])

const imageUrl = computed(() =>
  robot.currentMap ? api.mapPng(1, robot.currentMap) : '',
)

const pose = computed(() => robot.pose)

async function loadMap() {
  try {
    await robot.loadMaps()
    const meta = robot.maps.find((m) => m.name === robot.currentMap) ?? robot.maps[0] ?? null
    mapMeta.value = meta
    if (meta) {
      const raw = await api.navPoints(1, meta.name, '')
      points.value = raw.points
    }
  } catch (e) {
    mapError.value = e instanceof Error ? e.message : '地图加载失败'
  }
}

let trailTimer = 0

onMounted(async () => {
  robot.start()
  await loadMap()
  trailTimer = window.setInterval(() => {
    const p = robot.pose
    if (!p || typeof p.x !== 'number' || typeof p.y !== 'number') return
    trail.value.push({ x: p.x, y: p.y })
    if (trail.value.length > 200) trail.value.shift()
  }, 1000)
})

onBeforeUnmount(() => {
  robot.stop()
  if (trailTimer) window.clearInterval(trailTimer)
})
</script>

<template>
  <div class="dash">
    <div class="top">
      <StatusBar :snapshot="robot.snapshot" :online="robot.online" :stale="robot.stale" />
    </div>

    <div class="cols">
      <aside class="left">
        <section class="panel">
          <div class="panel-title">当前任务</div>
          <div class="kpi">{{ robot.robotState }}</div>
          <p class="muted small">
            进度字段单位未标定（PDF 未说明 0–1 还是 0–100），本期不显示百分比。
          </p>
        </section>

        <section class="panel">
          <div class="panel-title">位姿</div>
          <div class="kv"><span>X</span><b>{{ pose?.x?.toFixed(2) ?? '—' }} m</b></div>
          <div class="kv"><span>Y</span><b>{{ pose?.y?.toFixed(2) ?? '—' }} m</b></div>
          <div class="kv"><span>朝向</span><b>{{ pose?.angle_deg?.toFixed(1) ?? '—' }}°</b></div>
        </section>

        <section class="panel">
          <div class="panel-title">自检 / 能力</div>
          <p class="muted small">能力探测结果见「系统设置 → 能力矩阵」。</p>
        </section>
      </aside>

      <section class="center panel">
        <div class="panel-title">
          <span>地图 · {{ robot.currentMap || '未连接' }}</span>
          <span class="muted small">{{ robot.maps.length }} 张地图</span>
        </div>
        <div class="map-box">
          <MapCanvas
            :map-meta="mapMeta"
            :image-url="imageUrl"
            :points="points"
            :pose="pose"
            :stale="robot.stale || !robot.online"
            :trail="trail"
          />
        </div>
        <p v-if="mapError" class="danger small">{{ mapError }}</p>
      </section>

      <aside class="right">
        <section class="panel">
          <div class="panel-title">环境数据</div>
          <p class="muted small">
            未接入。环境量走机器人 WebSocket（`/bw_env_sensors/EnvSensorData`），
            真机联调拿到实际频率后再接，现在不显示假数据。
          </p>
        </section>

        <section class="panel">
          <div class="panel-title">最近告警</div>
          <p class="muted small">暂无告警。阈值未标定前不产生环境类告警。</p>
        </section>

        <section class="panel">
          <div class="panel-title">数据新鲜度</div>
          <div class="kv"><span>链路</span><b :class="robot.online ? 'ok' : 'danger'">{{ robot.online ? '正常' : '中断' }}</b></div>
          <div class="kv"><span>最近更新</span><b>{{ robot.snapshot ? robot.snapshot.age_s.toFixed(1) + ' s 前' : '—' }}</b></div>
          <div class="kv"><span>轮询次数</span><b>{{ robot.snapshot?.poll_count ?? 0 }}</b></div>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.dash { display: flex; flex-direction: column; gap: 12px; height: 100%; }
.cols { flex: 1; display: grid; grid-template-columns: 260px 1fr 280px; gap: 12px; min-height: 0; }
.left, .right { display: flex; flex-direction: column; gap: 12px; }
.center { display: flex; flex-direction: column; min-height: 0; }
.map-box { flex: 1; min-height: 0; }
.kv { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
.kv span { color: var(--text-2); }
.small { font-size: 12px; line-height: 1.6; }
</style>
