<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const keys = ref<{ id: number; robot_id: number; key_id: string; enabled: boolean
  created_at: string | null; last_used_at: string | null }[]>([])
const robots = ref<{ id: number; name: string }[]>([])
const pick = ref<number | null>(null)
const issued = ref<{ key_id: string; secret: string; robot_id: number } | null>(null)
const busy = ref(false)

async function load() {
  keys.value = await api.deviceKeys()
  const list = await api.robots()
  robots.value = (list as unknown as { items?: { id: number; name: string }[] }).items
    ?? (list as unknown as { id: number; name: string }[])
  if (pick.value === null && robots.value.length) pick.value = robots.value[0].id
}

async function issue() {
  if (pick.value === null) return
  busy.value = true
  try {
    const r = await api.issueDeviceKey(Number(pick.value))
    issued.value = { key_id: r.key_id, secret: r.secret, robot_id: r.robot_id }
    await load()
    toast('已签发，密钥只显示这一次，请立刻拷给设备', 'ok', 8000)
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '签发失败', 'danger')
  } finally {
    busy.value = false
  }
}

async function revoke(id: number, keyId: string) {
  if (!window.confirm(`吊销 ${keyId}？吊销后该设备必须换新密钥才能上报。`)) return
  try {
    await api.revokeDeviceKey(id)
    await load()
    toast('已吊销', 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '吊销失败', 'danger')
  }
}

function copySecret() {
  if (!issued.value) return
  navigator.clipboard?.writeText(issued.value.secret)
  toast('密钥已复制', 'ok')
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="head">
      <div>
        <h2>设备接入凭证</h2>
        <p class="muted">
          一机一密：每台设备独立密钥 + 报文签名 + 时间窗 + 防重放。
          设备上报时带 X-Device-Key / X-Timestamp / X-Nonce / X-Signature。
        </p>
      </div>
      <div class="row">
        <select v-model.number="pick" :disabled="!auth.canWrite">
          <option v-for="r in robots" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
        <button class="btn primary" :disabled="busy || !auth.canWrite" @click="issue">
          签发 / 轮换
        </button>
      </div>
    </header>

    <div v-if="issued" class="issued">
      <div class="title">密钥只显示这一次</div>
      <code class="key">{{ issued.secret }}</code>
      <div class="row">
        <span class="muted small">key_id：{{ issued.key_id }} · 设备 ID：{{ issued.robot_id }}</span>
        <button class="btn btn-sm" @click="copySecret">复制</button>
        <button class="btn btn-sm" @click="issued = null">我已保存</button>
      </div>
      <p class="muted small">
        签名规则：<code>hmac_sha256(secret, key_id + "\n" + timestamp + "\n" + nonce + "\n" + sha256(body))</code>
      </p>
    </div>

    <table class="tbl">
      <thead>
        <tr><th>设备</th><th>key_id</th><th>状态</th><th>签发时间</th><th>最近使用</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="k in keys" :key="k.id">
          <td>#{{ k.robot_id }}</td>
          <td><code>{{ k.key_id }}</code></td>
          <td>
            <span class="badge" :class="k.enabled ? 'ok' : 'off'">
              {{ k.enabled ? '启用' : '已吊销' }}
            </span>
          </td>
          <td>{{ k.created_at ?? '—' }}</td>
          <td>{{ k.last_used_at ?? '从未使用' }}</td>
          <td>
            <button v-if="k.enabled" class="btn btn-xs danger" :disabled="!auth.canWrite"
                    @click="revoke(k.id, k.key_id)">吊销</button>
          </td>
        </tr>
        <tr v-if="!keys.length">
          <td colspan="6" class="muted">还没有凭证。选一台设备点「签发」。</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; padding: 18px 20px; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.head h2 { margin: 0 0 4px; }
.head p { max-width: 720px; margin: 0; }
.row { display: flex; align-items: center; gap: 8px; }
.issued { border: 1px solid rgba(0, 165, 255, .35); background: rgba(0, 93, 164, .10);
  border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; }
.issued .title { font-weight: 600; color: #7fd4ff; }
.key { display: block; padding: 8px 10px; background: rgba(0, 0, 0, .35); border-radius: 6px;
  font-size: 15px; letter-spacing: .5px; word-break: break-all; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { text-align: left; padding: 9px 10px; border-bottom: 1px solid rgba(255,255,255,.08); }
.badge.ok { color: #5ee1a0; }
.badge.off { color: #ff8f8f; }
.small { font-size: 12px; }
</style>
