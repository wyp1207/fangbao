<script setup lang="ts">
/**
 * 全站能力异常提示条。
 *
 * 为什么需要：go2rtc 挂了 / 机器人失联时，视频和状态页只会"一直转圈"，
 * 领导看到的是"系统坏了"。这里明确说是哪个环节不可用、去哪看。
 *
 * 只提示"已经确认不可用"的项，不做猜测；可手动关闭，但下次刷新还会出现。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const dismissed = ref(false)
const checks = ref<{ name: string; ok: boolean; detail: string }[]>([])
const loaded = ref(false)

const problems = computed(() => checks.value.filter((c) => !c.ok))
const visible = computed(() => loaded.value && !dismissed.value && problems.value.length > 0)

async function load() {
  if (!auth.user) return
  try {
    const h = await api.deepHealth()
    const list: { name: string; ok: boolean; detail: string }[] = []

    const age = h.cache.age_s
    // 刚启动还没取到第一帧时不算故障，别一开服就弹黄条
    const starting = age < 0 || h.cache.poll_count === 0
    if (!starting) {
      list.push({
        name: '机器人数据链路',
        ok: h.cache.online,
        detail: h.cache.online ? '' : `已 ${Math.round(age)}s 未收到数据${h.cache.last_error ? '：' + h.cache.last_error : ''}`,
      })
    }
    for (const s of h.services ?? []) {
      if (s.name === 'uvicorn' || s.name === 'server') continue
      list.push({ name: s.name, ok: s.running, detail: s.running ? '' : (s.last_error || '进程未运行') })
    }
    checks.value = list
    loaded.value = true
  } catch {
    // 健康接口本身失败就说明后端不通，交给登录态处理，不重复提示
  }
}

let timer = 0
onMounted(() => {
  void load()
  timer = window.setInterval(load, 20000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div v-if="visible" class="banner">
    <span class="dot" />
    <b>{{ problems.length }} 项能力不可用</b>
    <span class="detail">
      <template v-for="(p, i) in problems" :key="p.name">
        <template v-if="i > 0"> · </template>{{ p.name }}<template v-if="p.detail">（{{ p.detail }}）</template>
      </template>
    </span>
    <span class="grow" />
    <router-link class="link" to="/settings">去系统设置看探测结果</router-link>
    <button class="close" title="本次关闭，20 秒后如仍异常会再提示" @click="dismissed = true">×</button>
  </div>
</template>

<style scoped>
.banner {
  position: fixed; left: 50%; bottom: 34px; transform: translateX(-50%);
  z-index: 2147482800;
  display: flex; align-items: center; gap: 10px;
  max-width: min(1100px, 94vw);
  padding: 7px 12px;
  font-size: 12.5px; color: #ffe9b8;
  background: linear-gradient(180deg, rgba(120, 78, 0, 0.96), rgba(78, 48, 0, 0.96));
  border: 1px solid rgba(255, 207, 63, 0.7);
  border-radius: 4px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
}
.dot { width: 7px; height: 7px; border-radius: 50%; background: #ffcf3f; box-shadow: 0 0 8px #ffcf3f; flex: none; }
.banner b { color: #fff3d0; white-space: nowrap; }
.detail { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #ffdf9e; }
.grow { flex: 1; }
.link { color: #ffe9b8; text-decoration: underline; white-space: nowrap; }
.close {
  background: none; border: none; color: #ffe9b8; font-size: 16px; line-height: 1;
  cursor: pointer; padding: 0 2px;
}
</style>
