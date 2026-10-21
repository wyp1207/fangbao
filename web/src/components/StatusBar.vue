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

const batteryTone = computed(() => {
  const v = battery.value
  if (v === null) return ''
  if (v < 10) return 'danger'
  if (v < 20) return 'warn'
  return 'ok'
})
</script>

<template>
  <div class="strip panel">
    <div class="seg link">
      <i class="dot" :class="online ? 'on' : 'off'" />
      <div>
        <div class="label">链路</div>
        <div class="value" :class="online ? 'ok' : 'danger'">
          {{ online ? '正常' : '中断' }}
          <em class="num">{{ age >= 0 ? age.toFixed(1) + 's' : '—' }}</em>
        </div>
      </div>
    </div>

    <div class="seg"><div class="label">运行模式</div><div class="value num">{{ mode }}</div></div>

    <div class="seg">
      <div class="label">电量</div>
      <div class="value">
        <span class="num" :class="batteryTone">{{ battery !== null ? battery : '—' }}</span><small>%</small>
        <span class="bar"><i :class="batteryTone" :style="{ width: (battery ?? 0) + '%' }" /></span>
      </div>
    </div>

    <div class="seg">
      <div class="label">硬件急停</div>
      <div class="value" :class="estop ? 'danger' : estop === null ? '' : 'ok'">
        <span v-if="estop" class="estop">已按下</span>
        <span v-else>{{ estop === null ? '—' : '未按下' }}</span>
      </div>
    </div>

    <div class="seg">
      <div class="label">充电</div>
      <div class="value" :class="charging ? 'ok' : ''">
        {{ charging === null ? '—' : charging ? '充电中' : '未充电' }}
      </div>
    </div>

    <div class="seg"><div class="label">固件</div><div class="value num">{{ version }}</div></div>
    <div class="seg"><div class="label">导航</div><div class="value">{{ slam }}</div></div>

    <div v-if="stale" class="seg"><span class="tag warn">数据过期</span></div>
  </div>
</template>

<style scoped>
.strip { display: flex; align-items: stretch; padding: 12px 6px; gap: 0; }
.seg {
  display: flex; flex-direction: column; justify-content: center; gap: 4px;
  padding: 0 18px; border-left: 1px solid var(--line); min-width: 96px;
}
.seg:first-child { border-left: none; }
.seg.link { flex-direction: row; align-items: center; gap: 10px; }

.label { font-size: 12px; color: var(--text-2); }
.value { font-size: 15px; font-weight: 500; display: flex; align-items: center; gap: 6px; color: var(--text-0); }
.value em { font-style: normal; font-size: 12px; color: var(--text-2); font-weight: 400; }
.value small { font-size: 12px; color: var(--text-2); }

.bar { position: relative; width: 62px; height: 5px; border-radius: 4px; background: var(--bg-3); overflow: hidden; }
.bar i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 4px; background: var(--accent); }
.bar i.ok { background: var(--ok); }
.bar i.warn { background: var(--warn); }
.bar i.danger { background: var(--danger); }

.estop {
  color: #fff; background: var(--danger);
  padding: 1px 9px; border-radius: 6px; font-size: 13px;
}
</style>
