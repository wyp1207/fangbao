<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { usePlatformStore } from '@/stores/platform'
import { useIdleSessionGuard } from '@/composables/useIdleSession'
import FaultBanner from '@/components/FaultBanner.vue'
import ForcePasswordChange from '@/components/ForcePasswordChange.vue'
import ToastHost from '@/components/ToastHost.vue'

const auth = useAuthStore()
const platform = usePlatformStore()
onMounted(() => { void auth.fetchMe() })
// 设置接口要登录才能读：等登录态就绪再拉，否则 401 会静默用默认值
watch(() => auth.user, (u) => { if (u) void platform.load() }, { immediate: true })

// 长时间无人操作后主动确认会话还在不在（大屏整夜挂着最容易踩这个坑）
useIdleSessionGuard()
</script>

<template>
  <router-view />
  <FaultBanner v-if="auth.user && platform.bannerOnFault" />
  <ForcePasswordChange />
  <ToastHost />
</template>
