<script setup lang="ts">
import { computed } from 'vue'
import type { StatusSnapshot } from '@/api'

const props = defineProps<{ snapshot: StatusSnapshot | null; online: boolean; stale: boolean }>()

const mode = computed(() => props.snapshot?.status?.status ?? 'UNKNOWN')
const battery = computed(() => props.snapshot?.info?.battery ?? null)
const estop = computed(() => props.snapshot?.info?.driver_port ?? null)
const charging = computed(() => props.snapshot?.info?.charge ?? null)
const version = computed(() => props.snapshot?.info?.info?.version ?? '待确认')
const slam = computed(() => props.snapshot?.info?.slam_type ?? '待确认')
const age = computed(() => props.snapshot?.age_s ?? -1)
</script>

<template>
  <div class="bar">
    <div class="chip">
      <span class="dot" :class="online ? 'on' : 'off'" />
      <span>{{ online ? '链路正常' : '通信中断' }}</span>
      <span class="muted mono">{{ age >= 0 ? age.toFixed(1) + 's' : '—' }}</span>
    </div>
    <div class="chip">
      <span class="label">模式</span><span class="mono">{{ mode }}</span>
    </div>
    <div class="chip">
      <span class="label">电量</span>
      <span class="mono" :class="battery !== null && battery < 20 ? 'warn' : ''">
        {{ battery !== null ? battery + '%' : '—' }}
      </span>
    </div>
    <div class="chip">
      <span class="label">硬件急停</span>
      <span :class="estop ? 'danger' : 'ok'">{{ estop === null ? '—' : estop ? '已按下' : '未按下' }}</span>
    </div>
    <div class="chip">
      <span class="label">充电</span>
      <span :class="charging ? 'ok' : ''">{{ charging === null ? '—' : charging ? '充电中' : '未充电' }}</span>
    </div>
    <div class="chip">
      <span class="label">固件</span><span class="mono">{{ version }}</span>
    </div>
    <div class="chip">
      <span class="label">导航</span><span class="mono">{{ slam }}</span>
    </div>
    <div v-if="stale" class="chip warn">数据过期</div>
  </div>
</template>

<style scoped>
.bar { display: flex; gap: 10px; flex-wrap: wrap; }
.chip {
  display: flex; align-items: center; gap: 8px;
  background: var(--bg-1);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 13px;
}
.chip.warn { border-color: var(--warn); color: var(--warn); }
.label { color: var(--text-2); font-size: 12px; }
.mono { font-variant-numeric: tabular-nums; }
</style>
