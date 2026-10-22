<script setup lang="ts">
/**
 * 手机处理工单：现场安全员收到推送 → 打开链接 → 核实（拍照/填结论）→ 点完成。
 *
 * 为什么是 H5 不是 App/小程序：现场用微信/浏览器打开即可，
 * 不用装、不用审核、不用维护两套代码；拍照用 input capture 调系统相机。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const id = Number(route.params.id)
const order = ref<any>(null)
const photos = ref<string[]>([])
const note = ref('')
const uploading = ref(false)
const busy = ref(false)

const canAct = computed(() => ['admin', 'safety', 'operator'].includes(auth.user?.role ?? ''))
const levelText: Record<string, string> = { critical: '紧急', warn: '一般', info: '提示' }

async function load() {
  order.value = await api.workOrder(id)
  photos.value = order.value?.photos ?? []
}

async function upload(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploading.value = true
  try {
    const res = await api.uploadWorkOrderPhoto(id, file)
    photos.value = [...photos.value, res.url]
    toast('照片已上传', 'ok')
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '上传失败', 'danger')
  } finally {
    uploading.value = false
    input.value = ''
  }
}

async function accept() {
  busy.value = true
  try {
    await api.transitionWorkOrder(id, { status: 'processing' })
    toast('已接单，去现场核实', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '操作失败', 'danger')
  } finally { busy.value = false }
}

async function finish() {
  if (!note.value.trim()) return toast('请填写核实结论', 'warn')
  if (!photos.value.length) return toast('至少拍一张现场照片', 'warn')
  busy.value = true
  try {
    // 现场直接销号：先到 processing，再 review，再 closed（后端状态机不允许跳步）
    if (order.value.status === 'assigned') await api.transitionWorkOrder(id, { status: 'processing' })
    if (order.value.status === 'processing') await api.transitionWorkOrder(id, { status: 'review' })
    await api.transitionWorkOrder(id, { status: 'closed', resolution: note.value.trim() })
    toast('已完成，处置记录已归档', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '提交失败', 'danger')
  } finally { busy.value = false }
}

onMounted(async () => {
  if (!auth.isLoggedIn) {
    await router.push({ name: 'login', query: { redirect: route.fullPath } })
    return
  }
  await load()
})
</script>

<template>
  <div class="m">
    <header class="mh">
      <h1>{{ order?.title || '工单' }}</h1>
      <p>
        <span class="tag" :class="order?.level === 'critical' ? 'danger' : 'warn'">
          {{ levelText[order?.level] || order?.level }}
        </span>
        <span class="dim"> {{ order?.code || '' }} · {{ order?.status_label || '' }}</span>
      </p>
    </header>

    <section v-if="order" class="card">
      <p class="desc">{{ order.description || '（无描述）' }}</p>
      <p class="meta">期限：{{ (order.due_at || '—').replace('T', ' ') }}　责任人：#{{ order.assignee_id || '未派' }}</p>

      <div class="thumbs">
        <img v-for="(u, i) in photos" :key="i" :src="u" alt="现场照片" />
      </div>

      <label class="fld">
        <span>现场拍照（核实证据，必拍）</span>
        <input type="file" accept="image/*" capture="environment" class="filein" @change="upload" />
        <em v-if="uploading" class="hint">上传中…</em>
      </label>

      <label class="fld">
        <span>核实结论（必填）</span>
        <textarea class="input" rows="3" v-model="note" placeholder="现场情况、已做的处理" />
      </label>

      <div class="acts">
        <button v-if="order.status === 'assigned'" class="big" :disabled="busy || !canAct" @click="accept">接单</button>
        <button class="big ok" :disabled="busy || !canAct || order.status === 'closed'" @click="finish">
          {{ order.status === 'closed' ? '已完成' : '核实完成' }}
        </button>
      </div>
      <p v-if="!canAct" class="hint">当前账号只读，无法处置</p>
    </section>

    <p v-else class="hint">读取中…</p>
  </div>
</template>

<style scoped>
.m { min-height: 100vh; padding: 12px 12px 40px; background: #04203c; color: #eaf7ff; font-size: 15px; }
.mh h1 { font-size: 17px; margin: 0 0 6px; }
.mh p { margin: 0 0 10px; }
.dim { color: #9fd2ff; font-size: 12.5px; }
.card { padding: 12px; background: rgba(0, 60, 110, .6); border: 1px solid rgba(111, 227, 255, .3); border-radius: 6px; }
.desc { margin: 0 0 6px; line-height: 1.6; }
.meta { color: #9fd2ff; font-size: 12.5px; margin: 0 0 10px; }
.thumbs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.thumbs img { width: 92px; height: 92px; object-fit: cover; border-radius: 4px; border: 1px solid rgba(111,227,255,.4); }
.fld { display: block; margin-bottom: 12px; }
.fld > span { display: block; font-size: 12.5px; color: #9fd2ff; margin-bottom: 4px; }
.input { width: 100%; box-sizing: border-box; font-size: 15px; padding: 10px; }
.filein { width: 100%; font-size: 13px; color: #cfe9ff; }
.hint { font-size: 12px; color: #9fd2ff; font-style: normal; }
.acts { display: grid; grid-template-columns: 1fr 2fr; gap: 8px; }
.big { padding: 15px 0; font-size: 16px; font-weight: 600; border: none; border-radius: 6px; color: #04203c; background: #cfe0ee; }
.big.ok { background: linear-gradient(180deg, #8ef0c0, #35d67a); }
</style>
