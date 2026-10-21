<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PLACEHOLDERS } from '@/config/placeholders'

const route = useRoute()
const router = useRouter()

const spec = computed(() => PLACEHOLDERS[String(route.name)] ?? {
  label: '未命名模块',
  purpose: '',
  needs: [],
})
</script>

<template>
  <div class="page">
    <section class="panel">
      <div class="panel-title">
        <span>{{ spec.label }}</span>
        <span class="tag warn">未接入</span>
      </div>

      <p class="purpose">{{ spec.purpose }}</p>

      <div class="block">
        <h4>做这块需要什么</h4>
        <ul class="needs">
          <li v-for="n in spec.needs" :key="n">{{ n }}</li>
        </ul>
      </div>

      <div class="block">
        <h4>为什么现在不画</h4>
        <p class="muted small">
          这一期没有对应的数据源。把界面先画出来、填上假数字，验收时可以糊弄过去，
          但真机上第一次演示就会穿帮——所以这里只写清楚缺什么，等数据到位再补界面。
        </p>
      </div>

      <p v-if="spec.reference" class="muted small">{{ spec.reference }}</p>

      <div class="actions">
        <button class="btn btn-sm" @click="router.back()">返回上一页</button>
        <button class="btn btn-sm primary" @click="router.push({ name: 'dashboard' })">回到驾驶舱</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { height: 100%; display: flex; flex-direction: column; }
.panel { flex: 1; min-height: 0; overflow: auto; }
.purpose { margin: 0 0 14px; font-size: 13.5px; color: #eaf7ff; }
.block { margin-bottom: 14px; }
h4 {
  margin: 0 0 8px;
  font-size: 13px; color: #9fe4ff; font-weight: 700;
  letter-spacing: 0.06em;
}
h4::before {
  content: ""; display: inline-block;
  width: 6px; height: 6px; margin-right: 7px;
  background: #7fe9ff; transform: rotate(45deg);
}
.needs { margin: 0; padding-left: 20px; font-size: 12.5px; line-height: 2; color: #bcdcff; }
.small { font-size: 12px; line-height: 1.9; }
.actions { display: flex; gap: 8px; margin-top: 16px; }
</style>
