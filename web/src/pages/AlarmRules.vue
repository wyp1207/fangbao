<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { useRobotStore } from '@/stores/robot'

const robot = useRobotStore()
const auth = useAuthStore()
const router = useRouter()

/** 阈值现在真的可改（系统设置里），所以这一页要读实时值，不能再写死 */
const cfg = ref<Record<string, unknown>>({})
const sensorCount = ref(0)
const calibratedCount = ref(0)

const rules = computed(() => [
  {
    metric: 'battery', label: '电量',
    warn: `${cfg.value['alarm.battery_warn'] ?? 20}%`,
    critical: `${cfg.value['alarm.battery_critical'] ?? 10}%`,
    note: '可在「系统设置 → 告警」里改，保存后立即生效',
    frozen: false,
  },
  {
    metric: 'offline', label: '通信中断',
    warn: `${cfg.value['alarm.offline_after_s'] ?? 10}s`,
    critical: '同级',
    note: '超过这个时间没收到数据就报；连续失败次数越多 age 越大',
    frozen: false,
  },
  {
    metric: 'sustain', label: '持续确认（防抖）',
    warn: cfg.value['alarm.sustain_s'] ? `${cfg.value['alarm.sustain_s']}s` : '不启用',
    critical: '—',
    note: '条件持续够久才报；同一指标 5 分钟内第 3 次会自动升级为严重',
    frozen: false,
  },
  {
    metric: 'estop', label: '硬件急停 driver_port',
    warn: '—', critical: '立即',
    note: '硬件按钮，只读；平台没有急停下发接口',
    frozen: true,
  },
  {
    metric: 'env', label: '环境类（气体/烟感/温湿度/噪声）',
    warn: sensorCount.value ? `${calibratedCount.value}/${sensorCount.value} 已标定` : '未接入',
    critical: '超限即报',
    note: '阈值在「设备管理 → 环境传感器」逐台标定；留空=不报警',
    frozen: calibratedCount.value === 0,
  },
  {
    metric: 'disk', label: '磁盘空间',
    warn: `${cfg.value['disk.warn_free_gb'] ?? 20} GB`,
    critical: `${cfg.value['disk.crit_free_gb'] ?? 8} GB`,
    note: '数据盘与数据库盘分开判；低于严重阈值进告警中心',
    frozen: false,
  },
])

onMounted(async () => {
  try {
    cfg.value = (await api.settings()).values
  } catch { /* 读不到就用默认展示 */ }
  try {
    const list = await api.sensors()
    sensorCount.value = list.length
    calibratedCount.value = list.filter((s) => s.calibrated).length
  } catch { /* 传感器读不到不影响规则展示 */ }
})

function goSettings() {
  if (!auth.canWrite) {
    toast('当前账号无修改权限', 'warn')
    return
  }
  void router.push({ name: 'settings' })
}
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>告警规则</span>
        <span class="muted">阈值在「系统设置 → 告警」里改，保存即生效；环境类在「环境传感器」里逐台标定</span>
        <span class="grow" />
        <button class="btn btn-sm primary" :disabled="!auth.canWrite" @click="goSettings">去修改阈值</button>
      </div>

      <table class="grid">
        <thead>
          <tr>
            <th style="width: 60px">序号</th>
            <th style="width: 240px">指标</th>
            <th style="width: 150px">提醒阈值</th>
            <th style="width: 150px">严重阈值</th>
            <th>说明</th>
            <th style="width: 110px">状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rules" :key="r.metric">
            <td>{{ i + 1 }}</td>
            <td>{{ r.label }}</td>
            <td class="num" :class="r.warn === '未标定' || r.warn === '未接入' ? 'warn' : ''">{{ r.warn }}</td>
            <td class="num" :class="r.critical === '未标定' ? 'warn' : ''">{{ r.critical }}</td>
            <td class="dim">{{ r.note }}</td>
            <td>
              <span class="tag" :class="r.frozen ? 'warn' : 'ok'">{{ r.frozen ? '待标定' : '生效中' }}</span>
            </td>
          </tr>
        </tbody>
      </table>

      <p class="muted small">
        未标定的指标一律不求值，也不会显示 0 或「正常」——避免把没测的东西说成安全。<br />
        同一指标 5 分钟内重复超限 3 次，会自动从「提醒」升级为「严重」，并绕过外发静默期。
      </p>

      <div class="actions">
        <button class="btn btn-sm" @click="robot.refreshAlarms()">刷新告警状态</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.small { font-size: 12px; }
.warn { color: #ffe08a; }
.num { font-variant-numeric: tabular-nums; }
.actions { display: flex; gap: 8px; margin-top: 10px; }
</style>
