<script setup lang="ts">
defineProps<{ open: boolean; action: string }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <div v-if="open" class="mask" @click.self="emit('close')">
    <div class="dlg">
      <div class="panel-title"><span>写操作未开放</span></div>
      <p class="lead">「{{ action }}」要下发到机器人执行，现在被锁着。</p>
      <ul class="reasons">
        <li>方案 §5.7：所有写操作要等真机联调通过 + 现场授权签字</li>
        <li>采集表 01 表 15–17 行：授权人、授权日期、紧急联系人</li>
        <li>锁解除后这些按钮直接可用，页面不用改</li>
      </ul>
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
  width: 460px; padding: 14px 16px 16px;
  background: linear-gradient(180deg, rgba(0, 112, 200, 0.97), rgba(0, 60, 118, 0.98));
  border: 1px solid rgba(255, 207, 63, 0.6);
  box-shadow: 0 0 30px rgba(0, 60, 140, 0.7);
}
.lead { margin: 0 0 10px; font-size: 13px; color: #eaf7ff; }
.reasons { margin: 0; padding-left: 18px; font-size: 12.5px; line-height: 1.9; color: #bcdcff; }
.foot { display: flex; justify-content: flex-end; margin-top: 14px; }
</style>
