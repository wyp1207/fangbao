<script setup lang="ts">
defineProps<{ title: string; right?: string; bodyClass?: string }>()
</script>

<template>
  <section class="t-panel">
    <span class="c tl" /><span class="c tr" /><span class="c bl" /><span class="c br" />

    <header class="t-head">
      <span class="tag">{{ title }}</span>
      <span class="dash" />
      <em v-if="right">{{ right }}</em>
    </header>

    <div class="t-body" :class="bodyClass">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.t-panel {
  position: relative;
  display: flex; flex-direction: column; min-height: 0;
  overflow: hidden;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.72), rgba(0, 66, 124, 0.88));
  border: 1px solid rgba(64, 196, 255, 0.55);
  box-shadow:
    inset 0 0 24px rgba(64, 196, 255, 0.12),
    0 0 12px rgba(0, 80, 180, 0.35);
}

/* 四角加粗亮边 */
.c { position: absolute; width: 12px; height: 12px; border: 0 solid #6fe3ff; }
.tl { top: 0; left: 0; border-top-width: 2px; border-left-width: 2px; }
.tr { top: 0; right: 0; border-top-width: 2px; border-right-width: 2px; }
.bl { bottom: 0; left: 0; border-bottom-width: 2px; border-left-width: 2px; }
.br { bottom: 0; right: 0; border-bottom-width: 2px; border-right-width: 2px; }

.t-head {
  flex: none; height: 32px;
  display: flex; align-items: center; gap: 8px;
  padding: 0 10px;
  background: linear-gradient(90deg, rgba(20, 140, 230, 0.6), rgba(10, 60, 140, 0.15) 70%, transparent);
  border-bottom: 1px solid rgba(64, 196, 255, 0.35);
}
/* 斜切标题标签，参考图里就是这种带缺口的牌子 */
.tag {
  position: relative;
  padding: 3px 20px 3px 10px;
  font-size: 14px; font-weight: 700; color: #fff;
  letter-spacing: 0.06em;
  background: linear-gradient(180deg, #2fa9ff, #005da4);
  clip-path: polygon(0 0, 100% 0, calc(100% - 12px) 100%, 0 100%);
  box-shadow: 0 0 10px rgba(43, 155, 255, 0.6);
  text-shadow: 0 1px 2px rgba(0, 30, 70, 0.5);
}
.dash {
  flex: 1; height: 6px;
  background:
    repeating-linear-gradient(90deg, rgba(111, 227, 255, 0.75) 0 6px, transparent 6px 12px);
  opacity: 0.55;
}
em { font-style: normal; font-size: 12px; color: #a9d8ff; }

.t-body { flex: 1; min-height: 0; padding: 10px 12px; overflow: auto; }
/* 地图面板：body 改成纵向 flex，画布才能拿到确定高度 */
.map-panel .t-body { padding: 8px; display: flex; flex-direction: column; overflow: hidden; }
</style>
