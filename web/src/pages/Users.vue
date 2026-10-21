<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type UserRow } from '@/api'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import DarkSelect from '@/components/DarkSelect.vue'
import { toast } from '@/composables/useToast'

const auth = useAuthStore()
const rows = ref<UserRow[]>([])
const loading = ref(false)
const error = ref('')

const roleOptions = [
  { value: 'admin', label: '管理员' },
  { value: 'operator', label: '操作员' },
  { value: 'viewer', label: '只读' },
]
const roleText: Record<string, string> = { admin: '管理员', operator: '操作员', viewer: '只读' }
const roleTone: Record<string, string> = { admin: 'danger', operator: 'ok', viewer: '' }

const isAdmin = computed(() => auth.user?.role === 'admin')

const editing = ref<UserRow | null>(null)
const resetting = ref<UserRow | null>(null)
const newPassword = ref('')

const creating = ref(false)
const form = ref({ username: '', password: '', role: 'operator' })

async function reload() {
  loading.value = true
  error.value = ''
  try {
    rows.value = await api.users()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : '用户列表读取失败'
  } finally {
    loading.value = false
  }
}

async function changeRole(u: UserRow, role: string) {
  try {
    await api.updateUser(u.id, { role })
    toast(`已把 ${u.username} 改为${roleText[role]}`, 'ok')
    await reload()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '修改失败', 'danger')
  }
}

async function toggleActive(u: UserRow) {
  try {
    await api.updateUser(u.id, { is_active: !u.is_active })
    toast(`${u.username} 已${u.is_active ? '停用' : '启用'}`, 'ok')
    await reload()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '操作失败', 'danger')
  }
}

async function remove(u: UserRow) {
  if (!window.confirm(`确定删除账号 ${u.username}？该操作不可恢复。`)) return
  try {
    await api.deleteUser(u.id)
    toast(`已删除 ${u.username}`, 'ok')
    await reload()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '删除失败', 'danger')
  }
}

function openCreate() {
  form.value = { username: '', password: '', role: 'operator' }
  creating.value = true
}

async function submitCreate() {
  if (!form.value.username || form.value.password.length < 6) {
    toast('账号至少 2 位，密码至少 6 位', 'warn')
    return
  }
  try {
    await api.createUser(form.value)
    toast(`已创建账号 ${form.value.username}`, 'ok')
    creating.value = false
    await reload()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '创建失败', 'danger')
  }
}

async function submitReset() {
  if (!resetting.value || newPassword.value.length < 6) {
    toast('密码至少 6 位', 'warn')
    return
  }
  try {
    await api.resetPassword(resetting.value.id, newPassword.value)
    toast(`已重置 ${resetting.value.username} 的密码`, 'ok')
    resetting.value = null
    newPassword.value = ''
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '重置失败', 'danger')
  }
}

onMounted(reload)
</script>

<template>
  <div class="page">
    <section v-if="!isAdmin" class="panel">
      <div class="panel-title"><span>用户管理</span></div>
      <p class="warn small">只有管理员可以管理账号。当前账号角色：{{ roleText[auth.user?.role ?? ''] ?? '未知' }}。</p>
    </section>

    <template v-else>
      <section class="panel">
        <div class="panel-title">
          <span>账号列表</span>
          <span class="muted">密码只存哈希，页面上永远不显示</span>
        </div>

        <div class="toolbar">
          <span class="grow" />
          <button class="btn btn-sm" :disabled="loading" @click="reload">刷新</button>
          <button class="btn btn-sm primary" @click="openCreate">新建账号</button>
        </div>

        <table class="grid">
          <thead>
            <tr>
              <th style="width: 60px">序号</th>
              <th>用户名</th>
              <th style="width: 150px">角色</th>
              <th style="width: 100px">状态</th>
              <th style="width: 170px">创建时间</th>
              <th style="width: 170px">最后登录</th>
              <th style="width: 200px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(u, i) in rows" :key="u.id">
              <td>{{ i + 1 }}</td>
              <td>{{ u.username }}</td>
              <td>
                <DarkSelect
                  :model-value="u.role" :options="roleOptions" width="130px"
                  @update:model-value="(v: string) => changeRole(u, v)"
                />
              </td>
              <td>
                <span class="tag" :class="u.is_active ? 'ok' : 'danger'">{{ u.is_active ? '启用' : '停用' }}</span>
              </td>
              <td class="num dim">{{ (u.created_at ?? '—').replace('T', ' ').slice(0, 19) }}</td>
              <td class="num dim">{{ (u.last_login_at ?? '—').replace('T', ' ').slice(0, 19) }}</td>
              <td>
                <div class="row-actions">
                  <button class="act" title="重置密码" @click="resetting = u; newPassword = ''">⚿</button>
                  <button class="act" :title="u.is_active ? '停用' : '启用'" :disabled="u.id === auth.user?.id" @click="toggleActive(u)">
                    {{ u.is_active ? '⏸' : '▶' }}
                  </button>
                  <button class="act danger" title="删除账号" :disabled="u.id === auth.user?.id" @click="remove(u)">🗑</button>
                </div>
              </td>
            </tr>
            <tr v-if="!rows.length">
              <td colspan="7" class="dim">{{ loading ? '读取中…' : '暂无账号' }}</td>
            </tr>
          </tbody>
        </table>

        <p v-if="error" class="danger small">{{ error }}</p>
        <p class="muted small">
          不能停用或删除自己的账号；删除最后一个管理员会被后端拒绝（<code>LAST_ADMIN</code>）。
        </p>
      </section>
    </template>

    <!-- 新建 -->
    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal">
        <div class="panel-title"><span>新建账号</span></div>
        <label class="fld"><span>用户名</span><input class="input" v-model="form.username" placeholder="2–64 位" /></label>
        <label class="fld"><span>初始密码</span><input class="input" v-model="form.password" type="password" placeholder="至少 6 位" /></label>
        <label class="fld"><span>角色</span>
          <DarkSelect v-model="form.role" :options="roleOptions" width="180px" />
        </label>
        <div class="modal-actions">
          <button class="btn btn-sm" @click="creating = false">取消</button>
          <button class="btn btn-sm primary" @click="submitCreate">创建</button>
        </div>
      </div>
    </div>

    <!-- 重置密码 -->
    <div v-if="resetting" class="modal-mask" @click.self="resetting = null">
      <div class="modal">
        <div class="panel-title"><span>重置密码 · {{ resetting.username }}</span></div>
        <label class="fld"><span>新密码</span><input class="input" v-model="newPassword" type="password" placeholder="至少 6 位" /></label>
        <div class="modal-actions">
          <button class="btn btn-sm" @click="resetting = null">取消</button>
          <button class="btn btn-sm primary" @click="submitReset">确认重置</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.page > .panel { flex: 1; min-height: 0; }
.small { font-size: 12px; line-height: 1.7; }
.danger-text { color: #ff8a8a; }
.modal-mask {
  position: fixed; inset: 0; z-index: 120;
  display: grid; place-items: center;
  background: rgba(2, 14, 30, 0.66);
}
.modal {
  width: 420px;
  padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.96), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.6);
  box-shadow: 0 0 30px rgba(0, 60, 140, 0.7);
}
.fld { display: block; margin-bottom: 12px; }
.fld > span { display: block; font-size: 12px; color: #9fd2ff; margin-bottom: 5px; }
.fld .input { width: 100%; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
</style>
