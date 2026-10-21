<script setup lang="ts">
defineProps<{ title: string; hint?: string }>()
</script>

<template>
  <div class="video-box">
    <div class="head">
      <span class="tag-title">{{ title }}</span>
      <span class="badge">未接入</span>
    </div>

    <div class="screen">
      <span class="corner tl" /><span class="corner tr" />
      <span class="corner bl" /><span class="corner br" />
      <div class="cross" />
      <div class="circle" />
      <span class="scan" />
      <div class="center">
        <div class="icon">▷</div>
        <p>视频通道未接入</p>
        <em>{{ hint ?? '真实视频流接入后在此播放' }}</em>
      </div>
      <div class="meta">
        <span class="rec" /> NO SIGNAL
      </div>
    </div>
  </div>
</template>

<style scoped>
.video-box {
  display: flex; flex-direction: column; gap: 6px;
  height: 100%; min-height: 0;
}

.head { display: flex; align-items: center; gap: 8px; }
.tag-title {
  padding: 2px 14px 2px 8px;
  font-size: 12.5px; font-weight: 700; color: #fff;
  background: linear-gradient(180deg, #2fa9ff, #0d6ec9);
  clip-path: polygon(0 0, 100% 0, calc(100% - 10px) 100%, 0 100%);
  box-shadow: 0 0 8px rgba(43, 155, 255, 0.5);
}
.badge {
  font-size: 11px; color: #ffe08a;
  border: 1px solid rgba(255, 207, 63, 0.6);
  background: rgba(255, 207, 63, 0.12);
  padding: 0 6px;
}

.screen {
  position: relative; flex: 1; min-height: 0;
  border: 1px solid rgba(111, 227, 255, 0.45);
  background:
    radial-gradient(circle at 50% 45%, rgba(20, 90, 170, 0.55), rgba(2, 16, 34, 0.95) 70%);
  overflow: hidden;
}
/* 取景框十字与圆环 */
.cross::before, .cross::after {
  content: ""; position: absolute; background: rgba(111, 227, 255, 0.22);
}
.cross::before { left: 50%; top: 12%; bottom: 12%; width: 1px; }
.cross::after { top: 50%; left: 12%; right: 12%; height: 1px; }
.circle {
  position: absolute; left: 50%; top: 50%;
  width: 120px; height: 120px; margin: -60px 0 0 -60px;
  border: 1px dashed rgba(111, 227, 255, 0.28);
  border-radius: 50%;
  animation: spin 18s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.scan {
  position: absolute; left: 0; right: 0; height: 32%;
  background: linear-gradient(180deg, transparent, rgba(111, 227, 255, 0.18), transparent);
  animation: sweep 4.5s linear infinite;
}
@keyframes sweep { 0% { top: -35%; } 100% { top: 100%; } }

.corner { position: absolute; width: 14px; height: 14px; border: 0 solid #6fe3ff; opacity: 0.9; }
.tl { top: 6px; left: 6px; border-top-width: 2px; border-left-width: 2px; }
.tr { top: 6px; right: 6px; border-top-width: 2px; border-right-width: 2px; }
.bl { bottom: 6px; left: 6px; border-bottom-width: 2px; border-left-width: 2px; }
.br { bottom: 6px; right: 6px; border-bottom-width: 2px; border-right-width: 2px; }

.center {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
  color: #9fd2ff;
}
.center .icon {
  width: 40px; height: 40px; display: grid; place-items: center;
  border: 1px solid rgba(111, 227, 255, 0.6); border-radius: 50%;
  color: #7fe9ff; font-size: 16px;
  box-shadow: 0 0 14px rgba(80, 200, 255, 0.4);
}
.center p { margin: 6px 0 0; font-size: 12.5px; color: #cfe8ff; }
.center em { font-style: normal; font-size: 10.5px; color: #6f9ec9; }

.meta {
  position: absolute; left: 10px; bottom: 8px;
  display: flex; align-items: center; gap: 6px;
  font-size: 10.5px; color: #ff8a8a; letter-spacing: 0.14em;
}
.rec {
  width: 7px; height: 7px; border-radius: 50%;
  background: #ff5a5a; box-shadow: 0 0 8px rgba(255, 90, 90, 0.9);
  animation: blink 1.4s ease-in-out infinite;
}
@keyframes blink { 50% { opacity: 0.25; } }
</style>
