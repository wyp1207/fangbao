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

const state = computed(() => {
  if (!robot.online) return { text: '通信中断', cls: 'danger' }
  if (robot.stale) return { text: '数据过期', cls: 'warn' }
  return { text: robot.robotState, cls: 'ok' }
})

const alarmCount = computed(() => robot.alarms.filter((a) => !a.acked_at).length)

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
        <div class="mark">巡检</div>
        <div class="brand-text">
          <div class="title">防爆机器人巡检平台</div>
          <div class="sub">JCROB · 单机</div>
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
          <span v-if="item.name === 'alarms' && alarmCount" class="badge">{{ alarmCount }}</span>
        </router-link>
      </nav>

      <div class="right">
        <span class="state" :class="state.cls">
          <i class="dot" :class="robot.online ? 'on' : 'off'" />
          {{ state.text }}
        </span>
        <div class="user">
          <b>{{ auth.user?.username }}</b>
          <em>{{ auth.user?.role }}</em>
        </div>
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
  height: 60px; flex: none;
  display: flex; align-items: center; gap: 28px;
  padding: 0 24px;
  background: #fff;
  border-bottom: 1px solid var(--line);
  box-shadow: 0 1px 6px rgba(15, 35, 60, 0.04);
  position: relative; z-index: 2;
}

.brand { display: flex; align-items: center; gap: 10px; min-width: 220px; }
.mark {
  width: 30px; height: 30px; display: grid; place-items: center;
  font-size: 12px; font-weight: 600; color: #fff;
  border-radius: 8px;
  background: linear-gradient(135deg, #4d9bff, var(--accent));
}
.title { font-size: 15px; font-weight: 600; }
.sub { font-size: 11px; color: var(--text-2); margin-top: 1px; }

.nav { display: flex; gap: 4px; flex: 1; height: 100%; align-items: flex-end; }
.nav-item {
  position: relative;
  padding: 0 14px 16px;
  font-size: 14px;
  color: var(--text-1);
  transition: color 0.15s;
}
.nav-item:hover { color: var(--accent); }
.nav-item.active { color: var(--accent); font-weight: 500; }
.nav-item.active::after {
  content: ""; position: absolute; left: 14px; right: 14px; bottom: -1px; height: 2px;
  background: var(--accent); border-radius: 2px 2px 0 0;
}
.badge {
  margin-left: 5px; padding: 0 6px; border-radius: 9px;
  background: var(--danger); color: #fff; font-size: 11px; line-height: 16px;
}

.right { display: flex; align-items: center; gap: 16px; }
.state {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 5px 12px; border-radius: 999px; font-size: 13px;
  background: var(--bg-2); border: 1px solid var(--line);
  color: var(--text-1);
}
.state.ok { color: var(--ok); background: var(--ok-soft); border-color: transparent; }
.state.warn { color: var(--warn); background: var(--warn-soft); border-color: transparent; }
.state.danger { color: var(--danger); background: var(--danger-soft); border-color: transparent; }

.user { display: flex; flex-direction: column; line-height: 1.3; font-size: 13px; }
.user b { font-weight: 500; }
.user em { font-style: normal; color: var(--text-2); font-size: 11px; }

.content { flex: 1; min-height: 0; overflow: auto; padding: 18px 24px 24px; }
</style>
