<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAV, isActive, type NavGroup } from '@/config/nav'

const props = withDefaults(defineProps<{ start?: number; end?: number }>(), {
  start: 0,
  end: Number.MAX_SAFE_INTEGER,
})

const route = useRoute()
const router = useRouter()

const groups = computed(() => NAV.slice(props.start, props.end))

const openKey = ref<string | null>(null)
const pos = ref({ left: 0, top: 0 })
const root = ref<HTMLElement | null>(null)
const dropEl = ref<HTMLElement | null>(null)

const openGroup = computed(() => groups.value.find((g) => g.key === openKey.value) ?? null)

function place(el: HTMLElement) {
  const r = el.getBoundingClientRect()
  pos.value = { left: r.left, top: r.bottom + 6 }
}

function toggle(g: NavGroup, ev: MouseEvent) {
  if (!g.items?.length) {
    if (g.route) void router.push({ name: g.route })
    return
  }
  const el = ev.currentTarget as HTMLElement
  openKey.value = openKey.value === g.key ? null : g.key
  if (openKey.value) place(el)
}

function hover(g: NavGroup, ev: MouseEvent) {
  if (!g.items?.length) return
  const el = ev.currentTarget as HTMLElement
  if (openKey.value !== g.key) place(el)
  openKey.value = g.key
}

function go(name: string) {
  openKey.value = null
  void router.push({ name })
}

function onDocClick(e: MouseEvent) {
  const t = e.target as Node
  if (root.value?.contains(t) || dropEl.value?.contains(t)) return
  openKey.value = null
}

let closeTimer: number | undefined

/** 延时关闭：给鼠标从标签挪到下拉留出时间（两者在 DOM 上不相邻） */
function scheduleClose() {
  window.clearTimeout(closeTimer)
  closeTimer = window.setTimeout(() => { openKey.value = null }, 220)
}

function cancelClose() {
  window.clearTimeout(closeTimer)
}

function close() {
  window.clearTimeout(closeTimer)
  openKey.value = null
}

onMounted(() => {
  // 捕获阶段监听：先于业务组件处理，点空白处一定关
  document.addEventListener("click", onDocClick, true)
  window.addEventListener("resize", close)
  window.addEventListener("scroll", close, true)
})
onBeforeUnmount(() => {
  document.removeEventListener("click", onDocClick, true)
  window.removeEventListener("resize", close)
  window.removeEventListener("scroll", close, true)
})
</script>

<template>
  <nav ref="root" class="nav" @mouseenter="cancelClose" @mouseleave="scheduleClose">
    <div
      v-for="g in groups" :key="g.key"
      class="nav-item"
      :class="{ active: isActive(g, route.name), open: openKey === g.key }"
      @mouseenter="hover(g, $event)"
      @click="toggle(g, $event)"
    >
      <button class="nav-tab" type="button">
        {{ g.label }}
        <i v-if="g.items?.length" class="caret">▾</i>
      </button>
    </div>

    <!-- 下拉挂到 body：不受父级 overflow / z-index 影响 -->
    <Teleport to="body">
      <ul
        v-if="openGroup?.items?.length"
        ref="dropEl"
        class="nav-drop"
        :style="{ left: pos.left + 'px', top: pos.top + 'px' }"
        @mouseenter="cancelClose"
        @mouseleave="scheduleClose"
      >
        <li
          v-for="it in openGroup.items" :key="it.name"
          :class="{ on: route.name === it.name }"
          @click.stop="go(it.name)"
        >
          <span class="dot-mk" />
          {{ it.label }}
          <em v-if="!it.real" class="pending">未接入</em>
        </li>
      </ul>
    </Teleport>
  </nav>
</template>

<style scoped>
.nav { display: flex; gap: 6px; align-items: center; min-width: 0; }
.nav-item { position: relative; }

.nav-tab {
  display: inline-flex; align-items: center; gap: 5px;
  white-space: nowrap;
  min-width: 104px;
  justify-content: center;
  padding: 6px 14px;
  font-size: 14px;
  color: #cfe8ff;
  cursor: pointer;
  background: linear-gradient(180deg, rgba(20, 130, 220, 0.6), rgba(0, 70, 140, 0.7));
  border: 1px solid rgba(111, 227, 255, 0.45);
  clip-path: polygon(10px 0, 100% 0, calc(100% - 10px) 100%, 0 100%);
  transition: all 0.15s;
}
.nav-tab:hover { color: #fff; border-color: #6fe3ff; }
.nav-item.active > .nav-tab {
  color: #082f66; font-weight: 700;
  background: linear-gradient(180deg, #b9ecff, #4fc3ff);
  box-shadow: 0 0 14px rgba(120, 220, 255, 0.8);
}
.nav-item.open > .nav-tab {
  border-color: #9fefff;
  box-shadow: 0 0 14px rgba(120, 220, 255, 0.6);
}
.caret { font-style: normal; font-size: 10px; opacity: 0.8; }
</style>

<style>
/* Teleport 出来的节点不在组件作用域内，只能写全局样式 */
.nav-drop {
  position: fixed;
  z-index: 2147483000;
  min-width: 168px;
  margin: 0; padding: 5px 0;
  list-style: none;
  background: linear-gradient(180deg, rgba(0, 84, 160, 0.98), rgba(0, 48, 96, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.55);
  box-shadow: 0 12px 30px rgba(0, 20, 50, 0.75);
}
.nav-drop::before {
  content: ""; position: absolute; left: 0; right: 0; top: 0; height: 2px;
  background: linear-gradient(90deg, transparent, #9fefff, transparent);
}
.nav-drop li {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 14px;
  font-size: 13px; color: #cfe8ff;
  cursor: pointer;
  white-space: nowrap;
}
.nav-drop li:hover { background: rgba(41, 212, 255, 0.2); color: #fff; }
.nav-drop li.on {
  color: #062f66; font-weight: 700;
  background: linear-gradient(180deg, #b9ecff, #4fc3ff);
}
.nav-drop .dot-mk { width: 5px; height: 5px; flex: none; background: #6fe3ff; transform: rotate(45deg); }
.nav-drop li.on .dot-mk { background: #0a5ecb; }
.nav-drop .pending {
  margin-left: auto; font-style: normal; font-size: 10.5px; color: #ffe08a;
  border: 1px solid rgba(255, 207, 63, 0.5); padding: 0 4px;
}
</style>
