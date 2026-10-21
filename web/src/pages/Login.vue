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
    <div class="card panel">
      <div class="head">
        <div class="logo">◈</div>
        <div>
          <h1>防爆机器人巡检平台</h1>
          <p class="muted">单机 · 二维作业管控 · 一期</p>
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

      <button class="btn wide" :disabled="auth.loading" @click="submit">
        {{ auth.loading ? '登录中…' : '登录' }}
      </button>

      <p class="muted small">
        默认账号见 server/.env.example；生产环境首次登录后必须改密码。
      </p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100%; display: grid; place-items: center;
  background: radial-gradient(900px 500px at 50% 20%, #10243a 0%, #070d16 70%);
}
.card { width: 360px; padding: 28px; }
.head { display: flex; gap: 12px; align-items: center; margin-bottom: 22px; }
.logo { font-size: 30px; color: var(--accent); }
h1 { font-size: 17px; margin: 0; }
p { margin: 4px 0 0; }
.field { display: block; margin-bottom: 14px; }
.field span { display: block; font-size: 12px; color: var(--text-1); margin-bottom: 6px; }
input {
  width: 100%; padding: 9px 12px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--bg-2); color: var(--text-0);
  outline: none;
}
input:focus { border-color: var(--accent); }
.wide { width: 100%; margin-top: 6px; }
.small { font-size: 12px; margin-top: 14px; }
</style>
