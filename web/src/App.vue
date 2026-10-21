<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import ToastHost from '@/components/ToastHost.vue'

const auth = useAuthStore()
onMounted(() => { void auth.fetchMe() })
</script>

<template>
  <router-view />
  <ToastHost />
</template>
