<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  right?: string
  bodyClass?: string
  tone?: 'blue' | 'cyan' | 'gold' | 'violet'
  /** 传了路由名，右侧文案就变成可点链接 */
  rightTo?: string
}>(), { tone: 'blue' })
</script>

<template>
  <section class="t-panel">
    <span class="c tl" /><span class="c tr" /><span class="c bl" /><span class="c br" />
    <span class="flow" />

    <header class="t-head">
      <span class="tag" :class="tone">{{ title }}</span>
      <span class="dash" />
      <router-link v-if="rightTo" class="right-link" :to="{ name: rightTo }">{{ right }}</router-link>
      <em v-else-if="right">{{ right }}</em>
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
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.62), rgba(0, 60, 118, 0.88));
  border: 1px solid rgba(64, 196, 255, 0.55);
  box-shadow: inset 0 0 24px rgba(64, 196, 255, 0.1), 0 0 12px rgba(0, 80, 180, 0.35);
}

/* 边框流光：沿顶部缓慢扫过的一条亮带 */
.flow {
  position: absolute; top: 0; left: -30%; width: 30%; height: 2px;
  background: linear-gradient(90deg, transparent, #b8f4ff, transparent);
  animation: flow 4.5s linear infinite;
  pointer-events: none;
}
@keyframes flow { 0% { left: -35%; } 100% { left: 105%; } }

.c { position: absolute; width: 12px; height: 12px; border: 0 solid #6fe3ff; }
.tl { top: 0; left: 0; border-top-width: 2px; border-left-width: 2px; }
.tr { top: 0; right: 0; border-top-width: 2px; border-right-width: 2px; }
.bl { bottom: 0; left: 0; border-bottom-width: 2px; border-left-width: 2px; }
.br { bottom: 0; right: 0; border-bottom-width: 2px; border-right-width: 2px; }

.t-head {
  flex: none; height: 32px;
  display: flex; align-items: center; gap: 8px;
  padding: 0 10px;
  background: linear-gradient(90deg, rgba(20, 140, 230, 0.55), rgba(0, 60, 130, 0.15) 70%, transparent);
  border-bottom: 1px solid rgba(64, 196, 255, 0.35);
}
.tag {
  position: relative;
  padding: 3px 20px 3px 10px;
  font-size: 14px; font-weight: 700; color: #fff;
  letter-spacing: 0.06em;
  clip-path: polygon(0 0, 100% 0, calc(100% - 12px) 100%, 0 100%);
  text-shadow: 0 1px 2px rgba(0, 30, 70, 0.6);
}
/* 不同模块用不同色相，避免通篇一个蓝 */
.tag.blue { background: linear-gradient(180deg, #2fa9ff, #0d6ec9); box-shadow: 0 0 10px rgba(43, 155, 255, 0.6); }
.tag.cyan { background: linear-gradient(180deg, #3ff0e0, #0c8f9e); box-shadow: 0 0 10px rgba(63, 240, 224, 0.55); }
.tag.gold { background: linear-gradient(180deg, #ffd76a, #c8860d); color: #3d2500; box-shadow: 0 0 10px rgba(255, 207, 63, 0.55); }
.tag.violet { background: linear-gradient(180deg, #a98bff, #5b3fd0); box-shadow: 0 0 10px rgba(150, 120, 255, 0.55); }

.dash {
  flex: 1; height: 6px;
  background: repeating-linear-gradient(90deg, rgba(111, 227, 255, 0.75) 0 6px, transparent 6px 12px);
  opacity: 0.5;
}
em { font-style: normal; font-size: 12px; color: #a9d8ff; }
.right-link { font-size: 12px; color: #7fe9ff; text-decoration: none; white-space: nowrap; }
.right-link:hover { color: #fff; text-shadow: 0 0 8px rgba(120, 230, 255, 0.9); }

.t-body { flex: 1; min-height: 0; padding: 10px 12px; overflow: auto; }
/* 地图面板：body 纵向 flex，画布才能拿到确定高度 */
.map-panel .t-body { padding: 8px; display: flex; flex-direction: column; overflow: hidden; }
/* 需要纵向堆叠多个块的面板 */
.stack-panel .t-body { display: flex; flex-direction: column; gap: 4px; overflow: hidden; }
</style>
