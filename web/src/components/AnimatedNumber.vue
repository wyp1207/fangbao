<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ value: number | null; decimals?: number; suffix?: string }>(), {
  decimals: 0,
  suffix: '',
})

const shown = ref<number | null>(props.value)
let raf = 0

function tween(from: number, to: number) {
  cancelAnimationFrame(raf)
  const start = performance.now()
  const dur = 600
  const step = (now: number) => {
    const t = Math.min(1, (now - start) / dur)
    const eased = 1 - Math.pow(1 - t, 3)
    shown.value = from + (to - from) * eased
    if (t < 1) raf = requestAnimationFrame(step)
  }
  raf = requestAnimationFrame(step)
}

watch(
  () => props.value,
  (next, prev) => {
    if (next === null) { shown.value = null; return }
    tween(typeof prev === 'number' ? prev : 0, next)
  },
)

onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <span class="anim-num">{{ shown === null ? '—' : shown.toFixed(decimals) }}<small v-if="suffix">{{ suffix }}</small></span>
</template>

<style scoped>
.anim-num { font-variant-numeric: tabular-nums; }
.anim-num small { font-size: 12px; margin-left: 2px; opacity: 0.75; }
</style>
