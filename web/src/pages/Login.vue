<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/client'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const username = ref('admin')
const password = ref('')
const error = ref('')
const totp = ref('')
const needTotp = ref(false)

async function submit() {
  error.value = ''
  try {
    await auth.login(username.value, password.value, needTotp.value ? totp.value : undefined)
    const back = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    await router.push(back || { name: 'dashboard' })
  } catch (e) {
    if (e instanceof ApiError) {
      // 开了双因子：服务端会先要动态码，这时才把输入框亮出来
      if (e.code === 'TOTP_REQUIRED' || e.code === 'TOTP_INVALID') {
        needTotp.value = true
        error.value = e.code === 'TOTP_INVALID' ? '动态码不正确' : '请输入 6 位动态码'
        return
      }
      error.value = e.message
      return
    }
    error.value = '登录失败'
  }
}
</script>

<template>
  <div class="login-page">
    <div class="card">
      <span class="c tl" /><span class="c tr" /><span class="c bl" /><span class="c br" />

      <div class="head">
        <div class="mark">◈</div>
        <div>
          <h1>防爆机器人巡检平台</h1>
          <p>JCROB PLATFORM</p>
        </div>
      </div>

      <label class="field">
        <span>账 号</span>
        <input v-model="username" autocomplete="username" @keyup.enter="submit" />
      </label>
      <label v-if="needTotp" class="field">
        <span>动态码</span>
        <input v-model="totp" inputmode="numeric" maxlength="6" placeholder="Authenticator 里的 6 位数字"
               @keyup.enter="submit" />
      </label>

      <label class="field">
        <span>密 码</span>
        <input v-model="password" type="password" autocomplete="current-password" @keyup.enter="submit" />
      </label>

      <p v-if="error" class="danger small">{{ error }}</p>

      <button class="btn primary submit" :disabled="auth.loading" @click="submit">
        {{ auth.loading ? '登录中…' : '登 录' }}
      </button>

      <p class="hint">默认账号见 <code>server/.env.example</code>；生产环境首次登录后必须改密码。</p>
    </div>

    <p class="footer">一期：驾驶舱 / 地图点位 / 任务只读 / 告警 · 无视频、无三维</p>
  </div>
</template>

<style scoped>
.login-page {
  height: 100%;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 22px;
}

.card {
  position: relative;
  width: 380px; padding: 30px 30px 24px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.72), rgba(0, 62, 118, 0.9));
  border: 1px solid rgba(111, 227, 255, 0.6);
  box-shadow: inset 0 0 30px rgba(64, 196, 255, 0.12), 0 8px 40px rgba(0, 30, 80, 0.55);
}
.card::before {
  content: "";
  position: absolute; left: 0; right: 0; top: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(160, 235, 255, 0.95), transparent);
}
.c { position: absolute; width: 14px; height: 14px; border: 0 solid #6fe3ff; }
.tl { top: 0; left: 0; border-top-width: 2px; border-left-width: 2px; }
.tr { top: 0; right: 0; border-top-width: 2px; border-right-width: 2px; }
.bl { bottom: 0; left: 0; border-bottom-width: 2px; border-left-width: 2px; }
.br { bottom: 0; right: 0; border-bottom-width: 2px; border-right-width: 2px; }

.head { display: flex; gap: 12px; align-items: center; margin-bottom: 24px; }
.mark {
  width: 40px; height: 40px; display: grid; place-items: center;
  font-size: 20px; color: #eaf7ff;
  background: linear-gradient(180deg, #2fa9ff, #005da4);
  border: 1px solid rgba(160, 230, 255, 0.85);
  box-shadow: 0 0 16px rgba(80, 200, 255, 0.7);
}
h1 { font-size: 17px; margin: 0; color: #fff; letter-spacing: 0.06em; }
.head p { margin: 4px 0 0; font-size: 10px; color: #9fd2ff; letter-spacing: 0.22em; }

.field { display: block; margin-bottom: 14px; }
.field span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 6px; letter-spacing: 0.12em; }
input {
  width: 100%; padding: 9px 12px;
  border: 1px solid rgba(111, 227, 255, 0.4);
  background: rgba(0, 45, 90, 0.6);
  color: #eaf7ff; font-size: 14px; outline: none;
  transition: all 0.15s;
}
input:focus { border-color: #7fe9ff; box-shadow: 0 0 10px rgba(80, 200, 255, 0.45); }

.submit { width: 100%; margin-top: 8px; padding: 10px; font-size: 14px; letter-spacing: 0.2em; }
.small { font-size: 12px; }
.hint { margin: 14px 0 0; font-size: 11.5px; line-height: 1.7; color: #8fc4f0; }
.footer { font-size: 12px; color: #8fc4f0; }
</style>
