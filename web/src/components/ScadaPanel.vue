<script setup lang="ts">
defineProps<{ title: string; right?: string; bodyClass?: string }>()
</script>

<template>
  <section class="s-panel">
    <span class="corner tl" /><span class="corner tr" />
    <span class="corner bl" /><span class="corner br" />

    <header class="s-panel-head">
      <span class="bar" />
      <h2>{{ title }}</h2>
      <span class="rule" />
      <em v-if="right">{{ right }}</em>
    </header>

    <div class="s-panel-body" :class="bodyClass">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.s-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: linear-gradient(180deg, rgba(17, 38, 74, 0.55), rgba(13, 29, 54, 0.72));
  border: 1px solid rgba(64, 158, 255, 0.28);
  border-radius: 2px;
  overflow: hidden;
  box-shadow: 0 0 0 1px rgba(41, 212, 255, 0.04), 0 4px 24px rgba(0, 0, 0, 0.4);
}
.s-panel::before {
  content: "";
  position: absolute; left: 0; right: 0; top: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(41, 212, 255, 0.55), transparent);
}

.corner {
  position: absolute; width: 14px; height: 14px;
  border: 0 solid #29d4ff;
  filter: drop-shadow(0 0 4px rgba(41, 212, 255, 0.6));
}
.tl { top: -1px; left: -1px; border-top-width: 2px; border-left-width: 2px; }
.tr { top: -1px; right: -1px; border-top-width: 2px; border-right-width: 2px; }
.bl { bottom: -1px; left: -1px; border-bottom-width: 2px; border-left-width: 2px; }
.br { bottom: -1px; right: -1px; border-bottom-width: 2px; border-right-width: 2px; }

.s-panel-head {
  flex: none;
  height: 38px;
  display: flex; align-items: center; gap: 9px;
  padding: 0 14px;
  border-bottom: 1px solid rgba(64, 128, 200, 0.18);
}
.bar {
  width: 4px; height: 14px; border-radius: 1px;
  background: linear-gradient(180deg, #29d4ff, #3b82f6);
  box-shadow: 0 0 8px rgba(41, 212, 255, 0.55);
}
h2 { font-size: 15px; font-weight: 600; margin: 0; color: #eaf4ff; letter-spacing: 0.04em; }
.rule {
  flex: 1; height: 1px;
  background: linear-gradient(90deg, rgba(41, 212, 255, 0.45), transparent);
}
em { font-style: normal; font-size: 12px; color: #6b7c99; }

.s-panel-body { flex: 1; min-height: 0; padding: 12px 14px; overflow: auto; }
</style>
