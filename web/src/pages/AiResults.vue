<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api'
import DarkSelect from '@/components/DarkSelect.vue'

interface Result {
  id: number
  algorithm: string
  algorithm_name: string
  camera_id: number | null
  value: number | null
  text: string | null
  confidence: number
  image: string | null
  ts: string | null
  alarm_id: number | null
}

const rows = ref<Result[]>([])
const algorithms = ref<{ code: string; name: string }[]>([])
const algo = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await api.aiResults({ algorithm: algo.value || undefined })
    rows.value = res.items as unknown as Result[]
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    algorithms.value = await api.aiAlgorithms()
  } catch { /* 无算法也不影响看结果 */ }
  await load()
})

function pct(c: number): string {
  return `${Math.round(c * 100)}%`
}
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>AI 识别结果</span>
        <span class="muted small">
          算法盒/算法服务推结果（POST /api/v1/ai/results，带 X-Api-Key）→ 落库存原图 →
          超置信度阈值自动生成告警
        </span>
        <span class="grow" />
        <DarkSelect
          v-model="algo" width="150px" :options="[{ value: '', label: '全部算法' }, ...algorithms.map((a) => ({ value: a.code, label: a.name }))]"
          @update:model-value="load"
        />
        <button class="btn btn-sm ok" :disabled="loading" @click="load">刷新</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 70px">ID</th>
            <th style="width: 130px">算法</th>
            <th style="width: 80px">摄像头</th>
            <th style="width: 150px">时间</th>
            <th style="width: 90px">置信度</th>
            <th>结果</th>
            <th style="width: 90px">原图</th>
            <th style="width: 90px">告警</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.algorithm_name }}</td>
            <td class="dim">{{ r.camera_id ?? '—' }}</td>
            <td class="num dim">{{ (r.ts ?? '').replace('T', ' ') }}</td>
            <td>
              <span class="tag" :class="r.confidence >= 0.8 ? 'ok' : r.confidence >= 0.6 ? 'warn' : ''">
                {{ pct(r.confidence) }}
              </span>
            </td>
            <td class="dim small">{{ r.text || (r.value !== null ? r.value : '—') }}</td>
            <td>
              <a v-if="r.image" :href="r.image" target="_blank" class="link">查看</a>
              <span v-else class="dim">—</span>
            </td>
            <td>
              <span v-if="r.alarm_id" class="tag danger">#{{ r.alarm_id }}</span>
              <span v-else class="dim small">未触发</span>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="8" class="dim">
              {{ loading ? '读取中…' : '还没有识别结果。算法盒接上后用 X-Api-Key 推 /api/v1/ai/results 即可。' }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.small { font-size: 12px; }
.num { font-variant-numeric: tabular-nums; }
.link { color: #7fe9ff; text-decoration: underline; font-size: 12px; }
</style>
