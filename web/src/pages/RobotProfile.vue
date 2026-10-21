<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type RobotRow } from '@/api'

const robots = ref<RobotRow[]>([])

/** 待接入的机器人：型号已定，适配器还没写，等现场对接 */
const pending = [
  {
    brand: '宇树 Unitree',
    model: 'G1 人形机器人',
    api: 'Unitree SDK2（DDS）/ 官方 App 网关',
    note: '人形，双足；巡检点位与导航协议与 JCROB 完全不同，需要单独写适配器',
  },
  {
    brand: '云深处 DEEP Robotics',
    model: 'X30 四足机器狗',
    api: '官方 HTTP/WS 网关（型号确认后核对）',
    note: '四足，越野能力强；先接状态与视频，再看能否接导航任务',
  },
]

onMounted(async () => {
  try {
    robots.value = await api.robots()
  } catch {
    robots.value = []
  }
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>机器人</span>
        <span class="muted">一个平台接多种本体，靠适配器隔离差异</span>
      </div>

      <table class="grid">
        <thead>
          <tr><th style="width: 70px">ID</th><th style="width: 180px">名称</th><th style="width: 200px">类型</th><th style="width: 110px">状态</th><th>接入方式</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in robots" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.name }}</td>
            <td>轮式防爆巡检机器人</td>
            <td><span class="tag" :class="r.mode === 'mock' ? 'warn' : 'ok'">{{ r.mode }}</span></td>
            <td class="dim">JCROB HTTP 3546 · {{ r.ip }}:{{ r.port }}</td>
          </tr>
          <tr v-for="p in pending" :key="p.model">
            <td class="dim">—</td>
            <td>{{ p.model }}</td>
            <td>{{ p.brand }}</td>
            <td><span class="tag warn">待接入</span></td>
            <td class="dim">{{ p.api }}</td>
          </tr>
        </tbody>
      </table>

      <p class="muted small">
        每台本体对应一个适配器（状态/地图/任务/控制的实现各不相同），平台侧只认统一的数据结构。
        JCROB 的适配器已经写好；宇树 G1 和云深处 X30 要拿到各自的 SDK 文档和一台能连的机器才能落。
      </p>
    </section>

    <section class="panel">
      <div class="panel-title"><span>差异点（接入前要确认）</span></div>
      <table class="grid">
        <thead><tr><th>能力</th><th style="width: 220px">JCROB（已接）</th><th style="width: 220px">宇树 G1</th><th style="width: 220px">云深处 X30</th></tr></thead>
        <tbody>
          <tr><td>位姿</td><td>HTTP /status</td><td class="dim">待核</td><td class="dim">待核</td></tr>
          <tr><td>地图</td><td>PNG 切片 + 点位</td><td class="dim">待核</td><td class="dim">待核</td></tr>
          <tr><td>任务</td><td>任务列表 + 动作序列</td><td class="dim">待核</td><td class="dim">待核</td></tr>
          <tr><td>视频</td><td>无（需外接）</td><td class="dim">待核</td><td class="dim">待核</td></tr>
          <tr><td>急停</td><td>硬件按钮只读</td><td class="dim">待核</td><td class="dim">待核</td></tr>
        </tbody>
      </table>
      <p class="muted small">
        这张表就是接入工作量的清单：每一格「待核」都要拿文档和真机各验一次，不能按想象填。
      </p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.small { font-size: 12px; line-height: 1.8; }
</style>
