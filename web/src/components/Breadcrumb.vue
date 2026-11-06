<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAV } from '@/config/nav'

const route = useRoute()
const router = useRouter()

/**
 * 面包屑：首页 / 分组 / 当前页
 * 只在 NAV 里能对上的二级页面显示；驾驶舱、登录、手机页不显示。
 */
const trail = computed(() => {
  const name = String(route.name ?? '')
  for (const g of NAV) {
    const item = g.items?.find((i) => i.name === name)
    if (item) {
      return [
        { label: '首页', to: '/dashboard' },
        { label: g.label, to: g.route ? `/${g.route}` : '' },
        { label: item.label, to: '' },
      ]
    }
  }
  return []
})

function go(to: string) {
  if (to) void router.push(to)
}
</script>

<template>
  <nav v-if="trail.length" class="bc" aria-label="面包屑">
    <template v-for="(t, i) in trail" :key="t.label">
      <span v-if="i" class="sep">/</span>
      <button v-if="t.to" class="link" type="button" @click="go(t.to)">{{ t.label }}</button>
      <span v-else class="cur">{{ t.label }}</span>
    </template>
  </nav>
</template>

<style scoped>
.bc {
  flex: none;
  display: flex; align-items: center; gap: 6px;
  height: 20px; margin: 0 0 4px 2px;
  font-size: 12px; color: #9fd2ff; letter-spacing: .3px;
}
.bc .sep { color: rgba(159, 210, 255, .45); }
.bc .link {
  background: none; border: 0; padding: 0; cursor: pointer;
  color: #9fd2ff; font-size: 12px;
}
.bc .link:hover { color: #fff; text-decoration: underline; }
.bc .cur { color: #eaf7ff; font-weight: 600; }
</style>
