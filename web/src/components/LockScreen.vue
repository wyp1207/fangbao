<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { useLockStore } from '@/stores/lock'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

const lock = useLockStore()
const auth = useAuthStore()
const router = useRouter()
const input = ref<HTMLInputElement | null>(null)

watch(() => lock.locked, async (v) => {
  if (v) {
    await nextTick()
    input.value?.focus()
  }
})

onMounted(() => {
  if (lock.locked) input.value?.focus()
})

async function logout() {
  try { await auth.logout() } catch { /* ignore */ }
  lock.locked = false
  void router.push('/login')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="lock.locked" class="ls-mask">
      <div class="ls-box">
        <div class="ls-icon">🔒</div>
        <h3>屏幕已锁定</h3>
        <p class="ls-dim">已空闲 {{ lock.idleMinutes }} 分钟，输入当前账号密码解锁</p>
        <input
          ref="input" v-model="lock.password" class="ls-input" type="password"
          placeholder="密码" autocomplete="off" @keyup.enter="lock.unlock()"
        />
        <p v-if="lock.error" class="ls-err">{{ lock.error }}</p>
        <div class="ls-actions">
          <button class="ls-btn" @click="logout">退出登录</button>
          <button class="ls-btn primary" :disabled="lock.busy" @click="lock.unlock()">
            {{ lock.busy ? '验证中…' : '解锁' }}
          </button>
        </div>
        <p class="ls-dim small">锁定期间无法操作大屏；忘记密码请让管理员在「用户管理」里重置</p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.ls-mask {
  position: fixed; inset: 0; z-index: 9999;
  display: grid; place-items: center;
  background: rgba(2, 10, 20, .92);
  backdrop-filter: blur(6px);
}
.ls-box {
  width: 360px; padding: 28px 28px 20px; border-radius: 12px; text-align: center;
  background: linear-gradient(180deg, #0b2747, #071a30);
  border: 1px solid rgba(0, 168, 255, .45);
  box-shadow: 0 0 32px rgba(0, 150, 255, .28);
  color: #dfefff;
}
.ls-icon { font-size: 34px; }
.ls-box h3 { margin: 8px 0 4px; font-size: 19px; letter-spacing: 2px; }
.ls-dim { color: #8fb6d4; font-size: 12px; margin: 4px 0 12px; }
.ls-dim.small { font-size: 11px; margin-top: 14px; }
.ls-input {
  width: 100%; box-sizing: border-box; padding: 9px 12px; border-radius: 6px;
  border: 1px solid rgba(0, 168, 255, .45); background: rgba(0, 20, 36, .9);
  color: #e6f6ff; font-size: 14px; outline: none;
}
.ls-input:focus { border-color: #35c8ff; box-shadow: 0 0 0 2px rgba(53, 200, 255, .18); }
.ls-err { color: #ff8f8f; font-size: 12px; margin: 8px 0 0; }
.ls-actions { display: flex; gap: 10px; margin-top: 14px; }
.ls-btn {
  flex: 1; padding: 8px 0; border-radius: 6px; cursor: pointer; font-size: 13px;
  background: rgba(0, 60, 100, .5); color: #a9d8f5; border: 1px solid rgba(0, 168, 255, .35);
}
.ls-btn.primary { background: #0076c8; color: #fff; border-color: #35c8ff; }
.ls-btn:disabled { opacity: .6; cursor: default; }
</style>
