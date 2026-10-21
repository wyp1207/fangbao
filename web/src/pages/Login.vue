<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/client'

const auth = useAuthStore()
const router = useRouter()
const username = ref('admin')
const password = ref('')
const error = ref('')

async function submit() {
  error.value = ''
  try {
    await auth.login(username.value, password.value)
    await router.push({ name: 'dashboard' })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : '登录失败'
  }
}
</script>

<template>
  <div class="login-page">
    <div class="card">
      <div class="head">
        <div class="mark">巡检</div>
        <div>
          <h1>防爆机器人巡检平台</h1>
          <p class="sub">JCROB · 单机 · 二维作业管控</p>
        </div>
      </div>

      <label class="field">
        <span>账号</span>
        <input v-model="username" autocomplete="username" @keyup.enter="submit" />
      </label>
      <label class="field">
        <span>密码</span>
        <input v-model="password" type="password" autocomplete="current-password" @keyup.enter="submit" />
      </label>

      <p v-if="error" class="danger small">{{ error }}</p>

      <button class="btn primary submit" :disabled="auth.loading" @click="submit">
        {{ auth.loading ? '登录中…' : '登 录' }}
      </button>

      <p class="hint">默认账号见 <code>server/.env.example</code>；生产环境首次登录后必须改密码。</p>
    </div>

    <p class="footer muted">一期：驾驶舱 / 地图点位 / 任务只读 / 告警 · 无视频、无三维</p>
  </div>
</template>

<style scoped>
.login-page {
  height: 100%;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 26px;
  background: linear-gradient(180deg, #f7f9fc, #eef2f7);
}

.card {
  width: 380px; padding: 32px 32px 26px;
  background: #fff;
  border-radius: 16px;
  border: 1px solid var(--line);
  box-shadow: 0 12px 40px rgba(15, 35, 60, 0.09);
}

.head { display: flex; gap: 13px; align-items: center; margin-bottom: 26px; }
.mark {
  width: 42px; height: 42px; display: grid; place-items: center;
  font-size: 13px; font-weight: 600; color: #fff;
  border-radius: 11px;
  background: linear-gradient(135deg, #4d9bff, var(--accent));
  box-shadow: 0 6px 16px rgba(22, 119, 255, 0.28);
}
h1 { font-size: 17px; margin: 0; }
.sub { margin: 5px 0 0; font-size: 12px; color: var(--text-2); }

.field { display: block; margin-bottom: 15px; }
.field span { display: block; font-size: 12.5px; color: var(--text-2); margin-bottom: 7px; }
input {
  width: 100%; padding: 10px 13px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-strong);
  background: var(--bg-2);
  color: var(--text-0); font-size: 14px; outline: none;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}
input:focus {
  background: #fff;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.submit { width: 100%; margin-top: 10px; padding: 11px; font-size: 14px; letter-spacing: 0.16em; }
.small { font-size: 12px; }
.hint { margin: 16px 0 0; font-size: 12px; line-height: 1.7; color: var(--text-2); }
.footer { font-size: 12px; }
</style>
