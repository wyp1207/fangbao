<script setup lang="ts">
/**
 * 手机打卡页（H5）：现场巡检员用。
 *
 * 为什么单开一个路由而不是复用桌面页：
 * 现场是竖屏、戴手套、光线差；桌面表格在手机上没法用。
 * 这里一屏一个点位：大按钮、结论二选一、扫码框、备注。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api'
import { ApiError } from '@/api/client'
import { toast } from '@/composables/useToast'

interface Item {
  id: number
  seq: number
  point_name: string
  code: string | null
  checks: string[]
  result: string
  note: string | null
  scanned_at: string | null
  photos: string[]
}

const route = useRoute()
const taskId = Number(route.params.id)
const task = ref<{ id: number; title: string; status: string; status_label: string } | null>(null)
const items = ref<Item[]>([])
const cur = ref<Item | null>(null)
const code = ref('')
const note = ref('')
const checksDone = ref<string[]>([])
const busy = ref(false)

const done = computed(() => items.value.filter((i) => i.result !== 'pending').length)
const progress = computed(() =>
  items.value.length ? Math.round((done.value / items.value.length) * 100) : 0,
)

async function load() {
  const t = (await api.inspectionTask(taskId)) as unknown as {
    id: number; title: string; status: string; status_label: string; items: Item[]
  }
  task.value = t
  items.value = t.items ?? []
  cur.value = items.value.find((i) => i.result === 'pending') ?? items.value[0] ?? null
  syncForm()
}

function syncForm() {
  code.value = ''
  note.value = cur.value?.note ?? ''
  checksDone.value = cur.value?.result === 'pending' ? [] : [...(cur.value?.checks ?? [])]
}

function open(i: Item) {
  cur.value = i
  syncForm()
}

async function submit(result: 'ok' | 'abnormal' | 'skipped') {
  if (!cur.value) return
  busy.value = true
  try {
    await api.checkInspectionItem(taskId, cur.value.id, {
      result,
      code: code.value.trim() || null,
      note: note.value || null,
      checks_done: checksDone.value,
      photos: [],
    })
    toast(result === 'ok' ? '已记录：正常' : result === 'abnormal' ? '已记录：异常' : '已跳过', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '提交失败', 'danger')
  } finally {
    busy.value = false
  }
}

async function finish() {
  try {
    await api.finishInspectionTask(taskId)
    toast('任务已完成', 'ok')
    await load()
  } catch (e) {
    toast(e instanceof ApiError ? e.message : '还有点位没打点', 'danger')
  }
}

onMounted(load)
</script>

<template>
  <div class="m">
    <header class="mh">
      <h1>{{ task?.title ?? '巡检任务' }}</h1>
      <div class="bar"><i :style="{ width: progress + '%' }" /></div>
      <p>{{ done }}/{{ items.length }} 已打点 · {{ task?.status_label }}</p>
    </header>

    <ol class="points">
      <li v-for="i in items" :key="i.id"
          :class="{ active: cur?.id === i.id, ok: i.result === 'ok', bad: i.result === 'abnormal' }"
          @click="open(i)">
        <b>{{ i.seq }}</b>
        <span class="nm">{{ i.point_name }}</span>
        <span class="st">
          {{ i.result === 'ok' ? '正常' : i.result === 'abnormal' ? '异常' : i.result === 'skipped' ? '跳过' : '未做' }}
        </span>
      </li>
    </ol>

    <section v-if="cur" class="card">
      <h2>{{ cur.point_name }}</h2>
      <p class="hint">
        检查项：{{ cur.checks.length ? cur.checks.join(' / ') : '按现场标准检查' }}
      </p>

      <label class="fld">
        <span>扫码编号{{ cur.code ? `（点位码 ${cur.code}）` : '' }}</span>
        <input class="input" v-model="code" :placeholder="cur.code ? '扫或输入点位码' : '无码点位可留空'" />
      </label>

      <div v-if="cur.checks.length" class="checks">
        <label v-for="c in cur.checks" :key="c" class="chk">
          <input type="checkbox" :value="c" v-model="checksDone" /> {{ c }}
        </label>
      </div>

      <label class="fld">
        <span>备注 / 异常描述</span>
        <textarea class="input" rows="3" v-model="note" placeholder="发现渗漏、异响、温度偏高……" />
      </label>

      <div class="acts">
        <button class="big ok" :disabled="busy" @click="submit('ok')">正常</button>
        <button class="big bad" :disabled="busy" @click="submit('abnormal')">异常</button>
        <button class="big skip" :disabled="busy" @click="submit('skipped')">跳过</button>
      </div>
    </section>

    <button class="finish" :disabled="busy || done < items.length" @click="finish">
      完成本次巡检（{{ done }}/{{ items.length }}）
    </button>
  </div>
</template>

<style scoped>
.m { min-height: 100vh; padding: 12px 12px 90px; background: #04203c; color: #eaf7ff; font-size: 15px; }
.mh { margin-bottom: 10px; }
.mh h1 { font-size: 17px; margin: 0 0 6px; }
.mh p { margin: 6px 0 0; font-size: 12.5px; color: #9fd2ff; }
.bar { height: 6px; background: rgba(0, 40, 80, 0.8); border-radius: 3px; overflow: hidden; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, #29d4ff, #6ff0c0); }
.points { list-style: none; padding: 0; margin: 0 0 12px; display: flex; flex-direction: column; gap: 6px; }
.points li {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px;
  background: rgba(0, 60, 110, 0.6); border: 1px solid rgba(111, 227, 255, 0.25); border-radius: 6px;
}
.points li.active { border-color: #7fe9ff; background: rgba(41, 212, 255, 0.16); }
.points li.ok .st { color: #6ff0c0; }
.points li.bad .st { color: #ff8a8a; }
.points .nm { flex: 1; }
.points .st { font-size: 12.5px; color: #9fd2ff; }
.card { padding: 12px; background: rgba(0, 60, 110, 0.6); border: 1px solid rgba(111, 227, 255, 0.3); border-radius: 6px; }
.card h2 { font-size: 16px; margin: 0 0 4px; }
.hint { font-size: 12.5px; color: #9fd2ff; margin: 0 0 10px; }
.fld { display: block; margin-bottom: 10px; }
.fld > span { display: block; font-size: 12.5px; color: #9fd2ff; margin-bottom: 4px; }
.fld .input { width: 100%; box-sizing: border-box; font-size: 15px; padding: 10px; }
.checks { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 10px; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 14px; }
.acts { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
.big { padding: 16px 0; font-size: 16px; font-weight: 600; border: none; border-radius: 6px; color: #04203c; }
.big.ok { background: linear-gradient(180deg, #8ef0c0, #35d67a); }
.big.bad { background: linear-gradient(180deg, #ffb0b0, #e34b4b); color: #fff; }
.big.skip { background: linear-gradient(180deg, #cfe0ee, #8fa8bd); }
.finish {
  position: fixed; left: 12px; right: 12px; bottom: 12px; padding: 14px;
  font-size: 15px; border: none; border-radius: 8px; color: #04203c;
  background: linear-gradient(180deg, #b9ecff, #4fc3ff);
}
.finish:disabled { opacity: 0.45; }
</style>
