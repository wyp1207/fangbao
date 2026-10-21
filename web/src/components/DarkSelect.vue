<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

export interface Option {
  value: string
  label: string
}

const props = withDefaults(defineProps<{
  modelValue: string
  options: Option[]
  placeholder?: string
  width?: string
}>(), { placeholder: '全部', width: '120px' })

const emit = defineEmits<{ 'update:modelValue': [string] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const current = computed(
  () => props.options.find((o) => o.value === props.modelValue)?.label ?? props.placeholder,
)

function pick(value: string) {
  emit('update:modelValue', value)
  open.value = false
}

function onDocClick(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div ref="root" class="dasel" :style="{ width }">
    <button class="trigger" :class="{ open }" @click="open = !open">
      <span>{{ current }}</span>
      <i class="caret">▾</i>
    </button>

    <ul v-if="open" class="menu">
      <li
        v-for="o in options"
        :key="o.value"
        :class="{ active: o.value === modelValue }"
        @click="pick(o.value)"
      >{{ o.label }}</li>
    </ul>
  </div>
</template>

<style scoped>
.dasel { position: relative; display: inline-block; }

.trigger {
  width: 100%;
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 5px 10px;
  font-size: 12.5px;
  color: #eaf7ff;
  background: linear-gradient(180deg, rgba(0, 110, 200, 0.55), rgba(0, 60, 120, 0.7));
  border: 1px solid rgba(111, 227, 255, 0.4);
  cursor: pointer;
  transition: all 0.15s;
}
.trigger:hover, .trigger.open {
  border-color: #7fe9ff;
  box-shadow: 0 0 10px rgba(80, 200, 255, 0.4);
}
.caret { font-style: normal; font-size: 10px; color: #7fe9ff; transition: transform 0.15s; }
.trigger.open .caret { transform: rotate(180deg); }

.menu {
  position: absolute; left: 0; right: 0; top: calc(100% + 4px);
  z-index: 50;
  margin: 0; padding: 4px 0;
  list-style: none;
  max-height: 220px; overflow: auto;
  background: linear-gradient(180deg, rgba(0, 80, 155, 0.98), rgba(0, 48, 96, 0.98));
  border: 1px solid rgba(111, 227, 255, 0.5);
  box-shadow: 0 8px 24px rgba(0, 25, 60, 0.6);
}
.menu li {
  padding: 6px 12px;
  font-size: 12.5px;
  color: #cfe8ff;
  cursor: pointer;
  white-space: nowrap;
}
.menu li:hover { background: rgba(41, 212, 255, 0.18); color: #fff; }
.menu li.active {
  color: #062f66;
  font-weight: 700;
  background: linear-gradient(180deg, #b9ecff, #4fc3ff);
}
</style>
