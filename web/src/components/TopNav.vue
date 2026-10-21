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

const openKey = ref<string | null>(null)
const root = ref<HTMLElement | null>(null)

const groups = computed(() => NAV.slice(props.start, props.end))

function currentLabel(): string {
  return String(route.name ?? '')
}

function toggle(g: NavGroup) {
  if (!g.items?.length) {
    if (g.route) void router.push({ name: g.route })
    return
  }
  // 点击只负责「打开」：鼠标移上去已经打开了，再点一下不该又关掉
  openKey.value = g.key
}

function hover(g: NavGroup) {
  if (g.items?.length) openKey.value = g.key
}

function leaveRoot() {
  openKey.value = null
}

function go(name: string) {
  openKey.value = null
  void router.push({ name })
}

function onDocClick(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) openKey.value = null
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))

defineExpose({ currentLabel })
</script>

<template>
  <nav ref="root" class="nav" @mouseleave="leaveRoot">
    <div
      v-for="g in groups" :key="g.key"
      class="nav-item"
      :class="{ active: isActive(g, route.name), open: openKey === g.key }"
      @mouseenter="hover(g)"
    >
      <button class="nav-tab" @click="toggle(g)">
        {{ g.label }}
        <i v-if="g.items?.length" class="caret">▾</i>
      </button>

      <transition name="drop">
        <ul v-if="openKey === g.key && g.items?.length" class="drop">
          <li
            v-for="it in g.items" :key="it.name"
            :class="{ on: route.name === it.name }"
            @click="go(it.name)"
          >
            <span class="dot-mk" />
            {{ it.label }}
            <em v-if="!it.real" class="pending">未接入</em>
          </li>
        </ul>
      </transition>
    </div>
  </nav>
</template>

<style scoped>
.nav { display: flex; gap: 6px; align-items: center; min-width: 0; overflow-x: auto; scrollbar-width: none; }
.nav::-webkit-scrollbar { display: none; }

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

.drop {
  position: absolute; left: 0; top: calc(100% + 13px);
  z-index: 60;
  min-width: 168px;
  margin: 0; padding: 5px 0;
  list-style: none;
  background: linear-gradient(180deg, rgba(0, 84, 160, 0.98), rgba(0, 48, 96, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.5);
  box-shadow: 0 10px 26px rgba(0, 25, 60, 0.6);
}
.drop::before {
  content: ""; position: absolute; left: 0; right: 0; top: 0; height: 2px;
  background: linear-gradient(90deg, transparent, #9fefff, transparent);
}
.drop li {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 14px;
  font-size: 13px; color: #cfe8ff;
  cursor: pointer;
  white-space: nowrap;
}
.drop li:hover { background: rgba(41, 212, 255, 0.2); color: #fff; }
.drop li.on {
  color: #062f66; font-weight: 700;
  background: linear-gradient(180deg, #b9ecff, #4fc3ff);
}
.dot-mk {
  width: 5px; height: 5px; flex: none;
  background: #6fe3ff; transform: rotate(45deg);
}
.drop li.on .dot-mk { background: #0a5ecb; }
.pending {
  margin-left: auto;
  font-style: normal; font-size: 10.5px;
  color: #ffe08a;
  border: 1px solid rgba(255, 207, 63, 0.5);
  padding: 0 4px;
}

.drop-enter-active, .drop-leave-active { transition: all 0.14s ease; }
.drop-enter-from, .drop-leave-to { opacity: 0; transform: translateY(-6px); }
</style>

@media (max-width: 1700px) {
  .nav { gap: 4px; }
  .nav-tab { padding: 5px 12px; font-size: 13px; }
}
@media (max-width: 1500px) {
  .nav-tab { padding: 4px 9px; font-size: 12.5px; }
  .caret { display: none; }
}
@media (max-width: 1280px) {
  .nav-tab { padding: 3px 7px; font-size: 12px; }
}
