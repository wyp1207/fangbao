<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useRobotStore } from '@/stores/robot'

const auth = useAuthStore()
const robot = useRobotStore()
const route = useRoute()
const router = useRouter()

const nav = [
  { name: 'dashboard', label: '驾驶舱' },
  { name: 'map', label: '地图与点位' },
  { name: 'tasks', label: '任务与巡航' },
  { name: 'alarms', label: '告警中心' },
  { name: 'history', label: '数据查询' },
  { name: 'settings', label: '系统设置' },
]

const stateTag = computed(() => {
  if (!robot.online) return { text: '通信中断', cls: 'danger' }
  if (robot.stale) return { text: '数据过期', cls: 'warn' }
  return { text: robot.robotState, cls: 'ok' }
})

async function onLogout() {
  await auth.logout()
  robot.stop()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="logo">◈</span>
        <div>
          <div class="title">防爆机器人巡检平台</div>
          <div class="sub muted">单机 · 二维作业管控</div>
        </div>
      </div>

      <nav class="nav">
        <router-link
          v-for="item in nav"
          :key="item.name"
          :to="{ name: item.name }"
          class="nav-item"
          :class="{ active: route.name === item.name }"
        >
          {{ item.label }}
        </router-link>
      </nav>

      <div class="right">
        <span class="tag" :class="stateTag.cls">{{ stateTag.text }}</span>
        <span class="muted">{{ auth.user?.username }}（{{ auth.user?.role }}）</span>
        <button class="btn" @click="onLogout">退出</button>
      </div>
    </header>

    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.shell { height: 100%; display: flex; flex-direction: column; }
.topbar {
  height: 60px;
  display: flex; align-items: center; gap: 24px;
  padding: 0 20px;
  background: linear-gradient(180deg, #0c1a2b, #0a1523);
  border-bottom: 1px solid var(--line);
}
.brand { display: flex; align-items: center; gap: 10px; min-width: 240px; }
.logo { font-size: 22px; color: var(--accent); }
.title { font-size: 15px; font-weight: 600; letter-spacing: .04em; }
.sub { font-size: 11px; }
.nav { display: flex; gap: 4px; flex: 1; }
.nav-item {
  padding: 8px 14px; border-radius: 8px; color: var(--text-1); font-size: 13px;
}
.nav-item:hover { background: var(--bg-2); color: var(--text-0); }
.nav-item.active { background: #12314f; color: #fff; box-shadow: inset 0 -2px 0 var(--accent); }
.right { display: flex; align-items: center; gap: 12px; font-size: 12px; }
.content { flex: 1; overflow: auto; padding: 16px; }
</style>
