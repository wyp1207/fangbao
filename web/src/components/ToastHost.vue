<script setup lang="ts">
import { useToast } from '@/composables/useToast'

const { items } = useToast()
</script>

<template>
  <div class="toast-host">
    <transition-group name="toast">
      <div v-for="t in items" :key="t.id" class="toast" :class="t.tone">
        <i />{{ t.text }}
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed; right: 18px; top: 16px; z-index: 200;
  display: flex; flex-direction: column; gap: 8px;
  pointer-events: none;
}
.toast {
  display: flex; align-items: center; gap: 8px;
  min-width: 180px; max-width: 360px;
  padding: 8px 14px;
  font-size: 12.5px; color: #eaf7ff;
  background: linear-gradient(180deg, rgba(0, 96, 170, 0.96), rgba(0, 56, 110, 0.96));
  border: 1px solid rgba(111, 227, 255, 0.55);
  box-shadow: 0 0 16px rgba(0, 90, 190, 0.5);
}
.toast i {
  width: 6px; height: 6px; border-radius: 50%; background: #7fe9ff;
  box-shadow: 0 0 8px #7fe9ff;
}
.toast.ok { border-color: rgba(56, 224, 123, 0.6); }
.toast.ok i { background: #38e07b; box-shadow: 0 0 8px #38e07b; }
.toast.warn { border-color: rgba(255, 207, 63, 0.6); }
.toast.warn i { background: #ffcf3f; box-shadow: 0 0 8px #ffcf3f; }
.toast.danger { border-color: rgba(255, 90, 90, 0.6); }
.toast.danger i { background: #ff5a5a; box-shadow: 0 0 8px #ff5a5a; }

.toast-enter-active, .toast-leave-active { transition: all 0.22s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(16px); }
</style>
