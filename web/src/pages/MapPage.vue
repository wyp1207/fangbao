<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import MapCanvas from '@/components/MapCanvas.vue'
import { api, type MapMeta, type NavPoint } from '@/api'
import { useRobotStore } from '@/stores/robot'

const robot = useRobotStore()
const maps = ref<MapMeta[]>([])
const selected = ref('')
const points = ref<NavPoint[]>([])
const selectedPoint = ref<NavPoint | null>(null)
const error = ref('')

const meta = computed(() => maps.value.find((m) => m.name === selected.value) ?? null)
const imageUrl = computed(() => (selected.value ? api.mapPng(1, selected.value) : ''))

async function load(name: string) {
  error.value = ''
  try {
    const raw = await api.navPoints(1, name, '')
    points.value = raw.points
  } catch (e) {
    error.value = e instanceof Error ? e.message : '点位加载失败'
  }
}

async function choose(name: string) {
  selected.value = name
  await load(name)
}

onMounted(async () => {
  robot.start()
  maps.value = await api.maps()
  if (maps.value.length) await choose(maps.value[0].name)
})
</script>

<template>
  <div class="page">
    <aside class="panel side">
      <div class="panel-title">地图列表</div>
      <button
        v-for="m in maps"
        :key="m.name"
        class="map-item"
        :class="{ active: m.name === selected }"
        @click="choose(m.name)"
      >
        <span>{{ m.name }}</span>
        <span class="muted small">{{ m.slam_type }} · {{ m.resolution?.toFixed(3) }} m/px</span>
      </button>
      <p v-if="!maps.length" class="muted small">还没有地图。真机 /navigation/saved_maps 有数据后自动出现。</p>

      <div class="panel-title" style="margin-top: 18px">点位（{{ points.length }}）</div>
      <ul class="points">
        <li v-for="(p, i) in points" :key="i" @click="selectedPoint = p">
          <span class="mono">{{ i + 1 }}</span>
          <span>{{ p.name || `点位 ${String(i + 1).padStart(2, '0')}` }}</span>
          <span class="muted mono">{{ p.x.toFixed(1) }}, {{ p.y.toFixed(1) }}</span>
        </li>
      </ul>
      <p class="muted small">
        theta 按弧度读取；写回前必须完成单位实测，本期上传按钮禁用。
      </p>
    </aside>

    <section class="panel main">
      <div class="panel-title">
        <span>{{ selected || '未选地图' }}</span>
        <span class="muted small" v-if="meta">
          origin [{{ meta.origin?.[0]?.toFixed(2) }}, {{ meta.origin?.[1]?.toFixed(2) }}]
          · {{ meta.width }}×{{ meta.height }} px
        </span>
      </div>
      <div class="map-box">
        <MapCanvas
          :map-meta="meta"
          :image-url="imageUrl"
          :points="points"
          :pose="robot.pose"
          :stale="robot.stale || !robot.online"
        />
      </div>
      <p v-if="error" class="danger small">{{ error }}</p>
      <div class="actions">
        <button class="btn" disabled>新增点位（待真机单位实测）</button>
        <button class="btn" disabled>同步 nav_points（写操作未开放）</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { display: grid; grid-template-columns: 280px 1fr; gap: 12px; height: 100%; }
.side { overflow: auto; }
.main { display: flex; flex-direction: column; min-height: 0; }
.map-box { flex: 1; min-height: 0; }
.map-item {
  width: 100%; display: flex; justify-content: space-between; align-items: center;
  background: var(--bg-2); border: 1px solid var(--line); color: var(--text-0);
  border-radius: 8px; padding: 8px 10px; margin-bottom: 6px; cursor: pointer;
}
.map-item.active { border-color: var(--accent); }
.points { list-style: none; padding: 0; margin: 0; }
.points li {
  display: grid; grid-template-columns: 28px 1fr auto; gap: 8px;
  padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 12px;
}
.points li:hover { background: var(--bg-2); }
.actions { display: flex; gap: 8px; margin-top: 10px; }
.small { font-size: 12px; }
.mono { font-variant-numeric: tabular-nums; }
</style>
