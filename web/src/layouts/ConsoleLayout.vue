<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useRobotStore } from '@/stores/robot'

const auth = useAuthStore()
const robot = useRobotStore()
const route = useRoute()
const router = useRouter()

const nav = [
  { name: 'dashboard', label: '首页' },
  { name: 'map', label: '巡检管理' },
  { name: 'tasks', label: '任务与巡航' },
  { name: 'alarms', label: '监控中心' },
  { name: 'history', label: '数据查询' },
  { name: 'settings', label: '系统管理' },
]

const state = computed(() => {
  if (!robot.online) return { text: '通信中断', cls: 'danger' }
  if (robot.stale) return { text: '数据过期', cls: 'warn' }
  return { text: robot.robotState, cls: 'ok' }
})

const alarmCount = computed(() => robot.alarms.filter((a) => !a.acked_at).length)

// 后台页也要有实时状态：轮询在布局层启动，子页面不用各自管
onMounted(() => robot.start())
onBeforeUnmount(() => robot.stop())

async function onLogout() {
  await auth.logout()
  robot.stop()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="shell">
    <header class="hdr">
      <div class="logo">
        <span class="mark">◈</span>
        <div class="logo-text">
          <b>防爆巡检</b>
          <i>JCROB PLATFORM</i>
        </div>
      </div>

      <nav class="tabs">
        <router-link
          v-for="item in nav.slice(0, 3)" :key="item.name"
          :to="{ name: item.name }"
          class="tab" :class="{ active: route.name === item.name }"
        >
          {{ item.label }}
          <span v-if="item.name === 'alarms' && alarmCount" class="badge">{{ alarmCount }}</span>
        </router-link>
      </nav>

      <div class="mini-title"><span class="w" />智能巡检机器人管理平台<span class="w r" /></div>

      <nav class="tabs">
        <router-link
          v-for="item in nav.slice(3)" :key="item.name"
          :to="{ name: item.name }"
          class="tab" :class="{ active: route.name === item.name }"
        >{{ item.label }}</router-link>
      </nav>

      <div class="right">
        <span class="state" :class="state.cls">
          <i class="dot" :class="robot.online ? 'on' : 'off'" />{{ state.text }}
        </span>
        <span class="user">
          <span class="avatar">{{ (auth.user?.username ?? 'A').slice(0, 1).toUpperCase() }}</span>
          {{ auth.user?.username }}
        </span>
        <button class="logout" @click="onLogout">退出</button>
      </div>
    </header>

    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.shell { height: 100%; display: flex; flex-direction: column; }

.hdr {
  flex: none; height: 54px;
  display: flex; align-items: center; gap: 18px;
  padding: 0 16px;
  overflow: hidden;
  background: linear-gradient(180deg, #0a7ad0, #005da4);
  border-bottom: 1px solid rgba(111, 227, 255, 0.5);
  box-shadow: 0 2px 12px rgba(0, 40, 110, 0.5);
}
.logo { display: flex; align-items: center; gap: 9px; min-width: 190px; }
.mark {
  width: 30px; height: 30px; display: grid; place-items: center;
  color: #eaf7ff; font-size: 17px;
  background: linear-gradient(180deg, #2fa9ff, #005da4);
  border: 1px solid rgba(160, 230, 255, 0.8);
  box-shadow: 0 0 12px rgba(80, 200, 255, 0.7);
}
.logo-text { line-height: 1.15; }
.logo-text b { display: block; font-size: 15px; color: #fff; letter-spacing: 0.08em; }
.logo-text i { font-style: normal; font-size: 9.5px; color: #9fd2ff; letter-spacing: 0.18em; }

.tabs { display: flex; gap: 6px; }
.mini-title {
  flex: 1; display: flex; align-items: center; justify-content: center; gap: 10px;
  font-size: 17px; font-weight: 800; letter-spacing: 0.16em;
  background: linear-gradient(180deg, #ffffff 35%, #9fe4ff 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
  white-space: nowrap;
}
.mini-title .w {
  width: 40px; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(160, 235, 255, 0.8));
}
.tab {
  position: relative;
  padding: 6px 20px;
  color: #cfe8ff; font-size: 14px;
  background: linear-gradient(180deg, rgba(20, 130, 220, 0.6), rgba(0, 70, 140, 0.7));
  border: 1px solid rgba(111, 227, 255, 0.45);
  clip-path: polygon(10px 0, 100% 0, calc(100% - 10px) 100%, 0 100%);
  transition: all 0.15s;
}
.tab:hover { color: #fff; border-color: #6fe3ff; }
.tab.active {
  color: #082f66; font-weight: 700;
  background: linear-gradient(180deg, #b9ecff, #4fc3ff);
  box-shadow: 0 0 14px rgba(120, 220, 255, 0.8);
}
.badge {
  margin-left: 5px; padding: 0 6px; border-radius: 9px;
  background: #ff5a5a; color: #fff; font-size: 11px; line-height: 16px;
  display: inline-block;
}

.right { display: flex; align-items: center; gap: 14px; justify-content: flex-end; }
.state {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 11px; font-size: 12.5px;
  border: 1px solid rgba(111, 227, 255, 0.5);
  background: rgba(0, 60, 120, 0.55);
  color: #cfe8ff;
}
.state.ok { color: #9dffc4; border-color: rgba(56, 224, 123, 0.6); }
.state.warn { color: #ffe08a; border-color: rgba(255, 207, 63, 0.6); }
.state.danger { color: #ffb3b3; border-color: rgba(255, 90, 90, 0.6); }

.user { display: inline-flex; align-items: center; gap: 7px; font-size: 13px; }
.avatar {
  width: 24px; height: 24px; border-radius: 50%;
  display: grid; place-items: center;
  background: linear-gradient(180deg, #7fd8ff, #2b9bff);
  color: #062f66; font-weight: 700; font-size: 12px;
}
.logout {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(160, 220, 255, 0.5);
  color: #eaf7ff; font-size: 12px; padding: 4px 10px; cursor: pointer;
}
.logout:hover { background: rgba(255, 255, 255, 0.2); }

.content { flex: 1; min-height: 0; overflow: auto; padding: 12px 14px 16px; }

/* ---------- 窄屏 ---------- */
@media (max-width: 1440px) {
  .mini-title { font-size: 15px; letter-spacing: 0.1em; }
  .mini-title .w { width: 22px; }
  .tab { padding: 5px 13px; font-size: 13px; }
  .logo-text i { display: none; }
}
@media (max-width: 1180px) {
  .state { display: none; }
  .tab { padding: 5px 10px; font-size: 12.5px; }
  .hdr { gap: 10px; }
}
@media (max-width: 980px) {
  .mini-title { display: none; }
  .logo { min-width: 0; }
}
@media (max-width: 820px) {
  .tabs .tab:nth-child(n + 3) { display: none; }
  .user { display: none; }
  .logo-text b { font-size: 13px; }
}
</style>
