<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import FaultBanner from '@/components/FaultBanner.vue'
import ForcePasswordChange from '@/components/ForcePasswordChange.vue'
import ToastHost from '@/components/ToastHost.vue'

const auth = useAuthStore()
onMounted(() => { void auth.fetchMe() })
</script>

<template>
  <router-view />
  <FaultBanner v-if="auth.user" />
  <ForcePasswordChange />
  <ToastHost />
</template>
