<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useRobotStore } from '@/stores/robot'
import { toast } from '@/composables/useToast'

const auth = useAuthStore()
const robot = useRobotStore()
const router = useRouter()

const open = ref(false)
const pos = ref({ left: 0, top: 0, right: 0 })
const root = ref<HTMLElement | null>(null)
const menuEl = ref<HTMLElement | null>(null)

const pwdOpen = ref(false)
const oldPwd = ref('')
const newPwd = ref('')
const pwdBusy = ref(false)

const username = computed(() => auth.user?.username ?? '未登录')
const initial = computed(() => username.value.slice(0, 1).toUpperCase())
const ROLE_TEXT: Record<string, string> = { admin: '管理员', operator: '操作员', viewer: '只读' }
const roleText = computed(() => ROLE_TEXT[auth.user?.role ?? ''] ?? '未知角色')
const isAdmin = computed(() => auth.user?.role === 'admin')

function place() {
  const el = root.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const MENU_W = 190
  // 贴右边时改成右对齐，别把菜单推出屏幕
  let left = r.left
  if (left + MENU_W > window.innerWidth - 8) {
    left = Math.max(8, window.innerWidth - MENU_W - 8)
  }
  pos.value = { left, top: r.bottom + 8, right: 0 }
}

function toggle() {
  place()
  open.value = !open.value
}

function close() {
  open.value = false
}

function go(name: string) {
  close()
  void router.push({ name })
}

async function logout() {
  close()
  await auth.logout()
  robot.stop()
  void router.push({ name: 'login' })
}

function switchAccount() {
  close()
  void logout()
}

function openPwd() {
  close()
  oldPwd.value = ''
  newPwd.value = ''
  pwdOpen.value = true
}

async function submitPwd() {
  if (newPwd.value.length < 6) {
    toast('新密码至少 6 位', 'warn')
    return
  }
  pwdBusy.value = true
  try {
    await api.changePassword(oldPwd.value, newPwd.value)
    toast('密码已修改，下次登录用新密码', 'ok', 3200)
    pwdOpen.value = false
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '修改失败', 'danger')
  } finally {
    pwdBusy.value = false
  }
}

function onDocClick(e: MouseEvent) {
  const t = e.target as Node
  if (root.value?.contains(t) || menuEl.value?.contains(t)) return
  close()
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') { close(); pwdOpen.value = false }
}

onMounted(() => {
  document.addEventListener('click', onDocClick, true)
  window.addEventListener('keydown', onKey)
  window.addEventListener('resize', close)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick, true)
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('resize', close)
})
</script>

<template>
  <div ref="root" class="um">
    <button class="trigger" type="button" @click="toggle" :title="`当前账号：${username}`">
      <span class="avatar">{{ initial }}</span>
      <span class="uname">{{ username }}</span>
      <i class="caret">▾</i>
    </button>

    <Teleport to="body">
      <ul
        v-if="open" ref="menuEl" class="um-menu"
        :style="{ left: pos.left + 'px', top: pos.top + 'px' }"
      >
        <li class="head">
          <span class="avatar big">{{ initial }}</span>
          <span class="meta">
            <b>{{ username }}</b>
            <em>{{ roleText }}</em>
          </span>
        </li>
        <li v-if="isAdmin" @click="go('users')">用户管理</li>
        <li @click="go('settings')">系统设置</li>
        <li @click="openPwd">修改密码</li>
        <li class="divider" />
        <li @click="switchAccount">切换账户</li>
        <li class="danger" @click="logout">退出登录</li>
      </ul>
    </Teleport>

    <div v-if="pwdOpen" class="mask" @click.self="pwdOpen = false">
      <div class="dlg">
        <div class="panel-title"><span>修改密码 · {{ username }}</span></div>
        <label class="fld"><span>原密码</span><input class="input" type="password" v-model="oldPwd" /></label>
        <label class="fld"><span>新密码（至少 6 位）</span><input class="input" type="password" v-model="newPwd" /></label>
        <div class="actions">
          <button class="btn btn-sm" @click="pwdOpen = false">取消</button>
          <button class="btn btn-sm primary" :disabled="pwdBusy" @click="submitPwd">确认修改</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.um { display: inline-flex; }
.trigger {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 3px 8px 3px 4px;
  background: rgba(0, 60, 120, 0.45);
  border: 1px solid rgba(111, 227, 255, 0.35);
  cursor: pointer; color: #eaf7ff; font-size: 13px;
}
.trigger:hover { border-color: #7fe9ff; box-shadow: 0 0 10px rgba(80, 200, 255, 0.4); }
.avatar {
  width: 26px; height: 26px; border-radius: 50%;
  display: grid; place-items: center;
  background: linear-gradient(180deg, #7fd8ff, #2b9bff);
  color: #062f66; font-weight: 700; font-size: 12px;
}
.avatar.big { width: 34px; height: 34px; font-size: 15px; }
.caret { font-style: normal; font-size: 10px; color: #9fd2ff; }
.uname { max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.mask {
  position: fixed; inset: 0; z-index: 2147483001;
  display: grid; place-items: center;
  background: rgba(2, 14, 30, 0.66);
}
.dlg {
  width: 380px; padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
  box-shadow: 0 0 30px rgba(0, 60, 140, 0.7);
}
.fld { display: block; margin-bottom: 12px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }

@media (max-width: 1500px) {
  .uname { display: none; }
}
</style>

<style>
/* Teleport 到 body 的菜单用全局样式 */
.um-menu {
  position: fixed;
  z-index: 2147483000;
  min-width: 186px;
  margin: 0; padding: 5px 0;
  list-style: none;
  background: linear-gradient(180deg, #00568f, #00355f);
  border: 1px solid rgba(111, 227, 255, 0.55);
  box-shadow: 0 12px 30px rgba(0, 20, 50, 0.75);
}
.um-menu::before {
  content: ""; position: absolute; left: 0; right: 0; top: 0; height: 2px;
  background: linear-gradient(90deg, transparent, #9fefff, transparent);
}
.um-menu li {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 14px;
  font-size: 13px; color: #cfe8ff;
  cursor: pointer; white-space: nowrap;
}
.um-menu li:hover { background: rgba(41, 212, 255, 0.2); color: #fff; }
.um-menu li.head {
  cursor: default; padding: 10px 14px;
  border-bottom: 1px solid rgba(111, 227, 255, 0.2);
}
.um-menu li.head:hover { background: transparent; }
.um-menu .meta { display: flex; flex-direction: column; line-height: 1.3; }
.um-menu .meta b { font-size: 13px; color: #fff; }
.um-menu .meta em { font-style: normal; font-size: 11px; color: #9fd2ff; }
.um-menu li.divider {
  padding: 0; height: 1px; margin: 4px 0;
  background: rgba(111, 227, 255, 0.2);
  cursor: default;
}
.um-menu li.divider:hover { background: rgba(111, 227, 255, 0.2); }
.um-menu li.danger { color: #ffb3b3; }
.um-menu li.danger:hover { background: rgba(255, 90, 90, 0.22); color: #fff; }
</style>
