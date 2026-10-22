<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type NavPoint } from '@/api'
import { useRobotStore } from '@/stores/robot'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'

const robot = useRobotStore()
const mapName = ref('')
const points = ref<NavPoint[]>([])
const loading = ref(false)
const keyword = ref('')

const mapOptions = computed(() => [
  { value: '', label: '全部地图' },
  ...robot.maps.map((m) => ({ value: m.name, label: m.name })),
])

function theta(p: NavPoint): string {
  const v = (p as unknown as { theta?: number }).theta
  return typeof v === 'number' ? v.toFixed(3) : '—'
}

const rows = computed(() =>
  points.value.filter((p) => (keyword.value ? (p.name || '').includes(keyword.value) : true)),
)

async function load() {
  loading.value = true
  try {
    const map = mapName.value || robot.currentMap || robot.maps[0]?.name || ''
    if (!map) { points.value = []; return }
    points.value = (await api.navPoints(1, map, '')).points
  } catch (e) {
    toast(e instanceof Error ? e.message : '点位读取失败', 'danger')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await robot.loadMaps()
  mapName.value = robot.currentMap || robot.maps[0]?.name || ''
  await load()
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>巡检点位</span>
        <span class="muted">只读：新增/修改点位要写机器人，未开放</span>
      </div>

      <div class="toolbar">
        <label>地图</label>
        <DarkSelect v-model="mapName" :options="mapOptions" width="180px" @update:model-value="load" />
        <label>点位名</label>
        <input class="input" v-model="keyword" placeholder="输入点位名称" />
        <button class="btn btn-sm ok" :disabled="loading" @click="load">查询</button>
        <button class="btn btn-sm warn" @click="keyword = ''">重置</button>
        <span class="grow" />
        <button class="btn btn-sm" title="到地图页在图上打点（存平台草稿）" @click="$router.push({ name: 'map', query: { lib: '1' } })">去地图打点</button>
        <button class="btn btn-sm" disabled title="点位下发要等真机联调 + 现场授权">同步到机器人</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">序号</th>
            <th>点位名称</th>
            <th style="width: 120px">X</th>
            <th style="width: 120px">Y</th>
            <th style="width: 120px">朝向</th>
            <th style="width: 160px">所属地图</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(p, i) in rows" :key="i">
            <td>{{ i + 1 }}</td>
            <td>{{ p.name || `点位 ${String(i + 1).padStart(2, '0')}` }}</td>
            <td class="num">{{ p.x.toFixed(3) }}</td>
            <td class="num">{{ p.y.toFixed(3) }}</td>
            <td class="num dim">{{ theta(p) }}</td>
            <td class="dim">{{ mapName || robot.currentMap }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="6" class="dim">{{ loading ? '读取中…' : '该地图没有点位' }}</td></tr>
        </tbody>
      </table>

      <p class="muted small">
        theta 是从机器人读回来的原始值（弧度），写回前必须先做单位实测；
        所以这一期点位只能看，不能改。
      </p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.small { font-size: 12px; line-height: 1.7; }
.num { font-variant-numeric: tabular-nums; }
</style>
