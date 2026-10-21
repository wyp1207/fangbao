<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const caps = ref<Record<string, unknown> | null>(null)
const health = ref<Awaited<ReturnType<typeof api.deepHealth>> | null>(null)
const message = ref('')

async function loadCaps() {
  try {
    caps.value = await api.capabilities(1)
  } catch (e) {
    message.value = e instanceof Error ? e.message : '能力读取失败'
  }
}

async function loadHealth() {
  try {
    health.value = await api.deepHealth()
  } catch (e) {
    message.value = e instanceof Error ? e.message : '探针失败'
  }
}

async function probe() {
  message.value = ''
  try {
    caps.value = await api.probe(1)
    message.value = '能力探测完成'
  } catch (e) {
    message.value = e instanceof Error ? e.message : '探测失败'
  }
}

onMounted(async () => {
  await loadCaps()
  await loadHealth()
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>能力矩阵</span>
        <button class="btn" :disabled="!auth.canWrite" @click="probe">重新探测</button>
      </div>
      <p class="muted small">
        不按固件版本写死能力：启动时逐接口探测，缺什么就隐藏/置灰。不支持时接口返回
        <code>JCROB_NOT_SUPPORTED</code>，页面显示“当前固件不支持”，不弹成功。
      </p>
      <pre v-if="caps" class="json">{{ JSON.stringify(caps, null, 2) }}</pre>
      <p v-else class="muted small">还没有探测结果。</p>
    </section>

    <section class="panel">
      <div class="panel-title">
        <span>运行状态</span>
        <button class="btn" @click="loadHealth">刷新</button>
      </div>
      <div v-if="health" class="health">
        <div class="kv"><span>链路在线</span><b :class="health.cache.online ? 'ok' : 'danger'">{{ health.cache.online ? '是' : '否' }}</b></div>
        <div class="kv"><span>数据年龄</span><b>{{ health.cache.age_s.toFixed(1) }} s</b></div>
        <div class="kv"><span>连续失败</span><b>{{ health.cache.consecutive_failures }}</b></div>
        <div class="kv"><span>事件循环延迟</span><b>{{ health.loop_lag_ms }} ms</b></div>
        <div class="kv" v-for="s in health.services" :key="s.name">
          <span>后台循环 {{ s.name }}</span>
          <b :class="s.running ? 'ok' : 'danger'">{{ s.running ? '运行中' : '已停止' }}（重启 {{ s.restarts }} 次）</b>
        </div>
        <p v-if="health.cache.last_error" class="danger small">最近错误：{{ health.cache.last_error }}</p>
      </div>
    </section>

    <section class="panel">
      <div class="panel-title">关于</div>
      <p class="muted small">
        一期范围：驾驶舱、地图与点位、任务只读、告警、历史、审计、基础 RBAC。
        视频 / 云台 / 测温 / 三维场站 / BMS / AI 识别 / 多机器人 / 7×24 录像 均为二期或不排期。
      </p>
      <p class="muted small">
        部署：Docker Compose 三容器（jc-server / jc-mysql / jc-nginx），nginx 宿主端口 8099。
      </p>
      <p v-if="message" class="small">{{ message }}</p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.json {
  background: var(--bg-2); border: 1px solid var(--line); border-radius: 8px;
  padding: 12px; font-size: 12px; max-height: 320px; overflow: auto;
}
.health { display: flex; flex-direction: column; gap: 4px; }
.kv { display: flex; justify-content: space-between; font-size: 13px; padding: 3px 0; }
.kv span { color: var(--text-2); }
.small { font-size: 12px; line-height: 1.6; }
</style>
