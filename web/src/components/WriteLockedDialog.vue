<script setup lang="ts">
/**
 * 写操作被锁时的说明。
 *
 * 原则（豆包/GLM 评审一致意见）：**不要只说"未开放"**。
 * 必须四件事说全：
 *   1) 现在是什么阶段   2) 为什么不能点
 *   3) 你现在能做什么替代 4) 什么时候能开、由谁开
 */
withDefaults(
  defineProps<{
    open: boolean
    action: string
    /** 替代操作，给了就显示成可点的引导 */
    alternative?: string
    /** 替代操作对应的路由名 */
    altTo?: string
  }>(),
  { alternative: '', altTo: '' },
)
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <div v-if="open" class="mask" @click.self="emit('close')">
    <div class="dlg">
      <div class="pnl-title">
        <span class="dot" />
        <span>「{{ action }}」需要机器人写权限</span>
      </div>

      <div class="rows">
        <div class="row">
          <b>现在</b>
          <span>平台只读阶段：所有数据来自机器人真实上报，可以看、可以导、可以确认告警。</span>
        </div>
        <div class="row">
          <b>为什么锁</b>
          <span>写操作会真的让机器人动（下发任务、改点位、切地图）。方案 §5.7 要求真机联调通过 + 现场授权签字后才开，避免误操作。</span>
        </div>
        <div class="row" v-if="alternative">
          <b>可以先这样做</b>
          <span>
            {{ alternative }}
            <router-link v-if="altTo" class="alt-link" :to="{ name: altTo }" @click="emit('close')">去这里 →</router-link>
          </span>
        </div>
        <div class="row">
          <b>什么时候开</b>
          <span>真机到场（预计 2026-11-10）联调通过、采集表 01 表 15–17 行授权签字后，这些按钮直接可用，页面不用改。</span>
        </div>
      </div>

      <div class="foot">
        <button class="btn btn-sm primary" @click="emit('close')">知道了</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask {
  position: fixed; inset: 0; z-index: 130;
  display: grid; place-items: center;
  background: rgba(2, 14, 30, 0.66);
}
.dlg {
  width: 540px; padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(255, 207, 63, 0.6);
  box-shadow: 0 0 30px rgba(0, 60, 140, 0.7);
}
.pnl-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 700; color: #fff; margin-bottom: 12px;
}
.dot {
  width: 3px; height: 14px; border-radius: 2px;
  background: linear-gradient(180deg, #ffe08a, #ffb03a);
}
.rows { display: flex; flex-direction: column; gap: 10px; }
.row { display: grid; grid-template-columns: 84px 1fr; gap: 10px; font-size: 12.5px; line-height: 1.75; }
.row b { color: #9fd2ff; font-weight: 600; }
.row span { color: #dceeff; }
.alt-link { margin-left: 6px; color: #7fe9ff; }
.foot { display: flex; justify-content: flex-end; margin-top: 14px; }
</style>
