<script setup lang="ts">
/**
 * 强制改密遮罩。
 *
 * 触发条件：user.must_change_password = true（初始密码 / 管理员重置后）。
 * 不能关闭、不能点遮罩消失——只能改完密码继续。
 * 这不是"骚扰"，是等保会查的一条：初始口令必须强制修改。
 */
import { computed, ref } from 'vue'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const oldPwd = ref('')
const newPwd = ref('')
const confirmPwd = ref('')
const busy = ref(false)
const error = ref('')

const visible = computed(() => !!auth.user && auth.mustChangePassword)

const ruleOk = computed(() =>
  newPwd.value.length >= 8 &&
  /[A-Za-z]/.test(newPwd.value) &&
  /\d/.test(newPwd.value) &&
  newPwd.value !== oldPwd.value,
)
const matchOk = computed(() => newPwd.value !== '' && newPwd.value === confirmPwd.value)

async function submit() {
  error.value = ''
  if (!ruleOk.value) {
    error.value = '新密码至少 8 位，且要同时包含字母和数字，不能与原密码相同'
    return
  }
  if (!matchOk.value) {
    error.value = '两次输入的新密码不一致'
    return
  }
  busy.value = true
  try {
    await api.changePassword(oldPwd.value, newPwd.value)
    await auth.refreshMe()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : '修改失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="visible" class="force-mask">
    <div class="force-box">
      <h3>首次登录，请先修改密码</h3>
      <p class="dim small">
        当前账号 {{ auth.user?.username }} 用的是初始密码。
        改完才能继续使用平台——这是等保要求，也是为了防止初始密码被猜到。
      </p>

      <label class="fld"><span>当前密码</span>
        <input class="input" type="password" v-model="oldPwd" autofocus @keyup.enter="submit" />
      </label>
      <label class="fld"><span>新密码（≥8 位，含字母和数字）</span>
        <input class="input" type="password" v-model="newPwd" @keyup.enter="submit" />
      </label>
      <label class="fld"><span>再输一次</span>
        <input class="input" type="password" v-model="confirmPwd" @keyup.enter="submit" />
      </label>

      <p v-if="error" class="danger small">{{ error }}</p>
      <p v-if="newPwd && !ruleOk" class="warn small">规则：≥8 位、含字母和数字、不能与原密码相同</p>
      <p v-if="confirmPwd && !matchOk" class="warn small">两次输入不一致</p>

      <button class="btn primary" :disabled="busy || !ruleOk || !matchOk" @click="submit">
        {{ busy ? '提交中…' : '修改并继续' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.force-mask {
  position: fixed; inset: 0; z-index: 2147483200;
  display: grid; place-items: center;
  background: rgba(2, 10, 22, 0.82);
  backdrop-filter: blur(4px);
}
.force-box {
  width: 380px; padding: 20px 20px 18px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.98), rgba(0, 56, 110, 0.99));
  border: 1px solid rgba(255, 207, 63, 0.65);
  box-shadow: 0 0 40px rgba(0, 60, 140, 0.8);
}
.force-box h3 { margin: 0 0 8px; font-size: 16px; color: #fff; }
.small { font-size: 12px; line-height: 1.7; }
.fld { display: block; margin-bottom: 10px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 4px; }
.fld .input { width: 100%; box-sizing: border-box; }
.danger { color: #ff8a8a; }
.warn { color: #ffe08a; }
.btn.primary { width: 100%; margin-top: 6px; }
</style>
