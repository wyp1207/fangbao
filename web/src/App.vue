<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useIdleSessionGuard } from '@/composables/useIdleSession'
import FaultBanner from '@/components/FaultBanner.vue'
import ForcePasswordChange from '@/components/ForcePasswordChange.vue'
import ToastHost from '@/components/ToastHost.vue'

const auth = useAuthStore()
onMounted(() => { void auth.fetchMe() })

// 长时间无人操作后主动确认会话还在不在（大屏整夜挂着最容易踩这个坑）
useIdleSessionGuard()
</script>

<template>
  <router-view />
  <FaultBanner v-if="auth.user" />
  <ForcePasswordChange />
  <ToastHost />
</template>
