<script setup lang="ts">
import { ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import AudioScape from '@/components/business/AudioScape.vue'

/** 睡前放松引导：一步一步来，不追求做完。 */
const GUIDE = [
  { title: '把灯光调暗一点', body: '关掉或调暗头顶的灯，屏幕亮度也调低。让身体先知道「天黑了」。' },
  { title: '放下手机', body: '把手机放到够不到的地方。如果必须放床边，也先翻面静音。' },
  { title: '松开肩膀和下巴', body: '深吸一口气，呼气时让肩膀自然下沉。轻轻张开嘴，松开咬紧的下巴。' },
  { title: '扫描一下身体', body: '从额头到脚尖，慢慢走一遍。遇到紧绷的地方，呼气时想象它松一点。' },
  { title: '不用逼自己睡着', body: '就躺着休息，让思绪慢下来。睡不着也没关系，闭眼休息同样有用。' },
]

const TIPS = [
  '睡前 1 小时尽量不喝含咖啡因的饮料。',
  '把明天要担心的事写在纸上，明天再处理。',
  '白天的小睡别超过 30 分钟。',
  '固定起床时间，比固定入睡时间更重要。',
]

const step = ref(0)

function next() {
  if (step.value < GUIDE.length - 1) step.value += 1
}
function prev() {
  if (step.value > 0) step.value -= 1
}
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="睡眠辅助" sub="睡前放松引导与轻柔音景" back />

    <PxCard title="睡前放松引导">
      <div class="sl__step">
        <p class="sl__step-no">第 {{ step + 1 }} / {{ GUIDE.length }} 步</p>
        <h3 class="sl__step-title">{{ GUIDE[step].title }}</h3>
        <p class="sl__step-body">{{ GUIDE[step].body }}</p>
      </div>
      <div class="sl__dots">
        <span
          v-for="(g, i) in GUIDE"
          :key="g.title"
          class="sl__dot"
          :class="{ 'is-on': i === step, 'is-done': i < step }"
        />
      </div>
      <div class="sl__nav">
        <PxButton variant="ghost" :disabled="step === 0" @click="prev">上一步</PxButton>
        <PxButton :disabled="step === GUIDE.length - 1" @click="next">下一步</PxButton>
      </div>
    </PxCard>

    <PxCard class="sl__block" title="轻柔音景">
      <AudioScape />
      <p class="xq-muted sl__hint">建议用小音量外放，或戴上耳机，设一个 20~30 分钟的定时停止。</p>
    </PxCard>

    <PxCard class="sl__block" title="助眠小贴士">
      <ul class="sl__tips">
        <li v-for="t in TIPS" :key="t">{{ t }}</li>
      </ul>
    </PxCard>

    <p class="xq-disclaimer">
      长期入睡困难、早醒或白天困得影响生活，建议找心理老师或医生聊聊各自的睡法。本页面只是辅助放松，不能替代诊疗。
    </p>
  </div>
</template>

<style scoped>
.sl__step {
  min-height: 120px;
}
.sl__step-no {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.sl__step-title {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-lg);
  margin: 6px 0 var(--xq-sp-2);
}
.sl__step-body {
  font-size: var(--xq-fs-sm);
  line-height: 1.8;
}
.sl__dots {
  display: flex;
  gap: 6px;
  justify-content: center;
  margin: var(--xq-sp-3) 0;
}
.sl__dot {
  width: 10px;
  height: 10px;
  border: 2px solid var(--xq-text-disabled);
  background: var(--xq-surface-2);
}
.sl__dot.is-done {
  background: var(--xq-primary-soft);
  border-color: var(--xq-primary);
}
.sl__dot.is-on {
  background: var(--xq-primary);
  border-color: var(--xq-text);
}
.sl__nav {
  display: flex;
  justify-content: space-between;
  gap: var(--xq-sp-2);
}
.sl__block {
  margin-top: var(--xq-sp-3);
}
.sl__hint {
  margin-top: var(--xq-sp-3);
}
.sl__tips {
  display: grid;
  gap: var(--xq-sp-2);
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
}
.sl__tips li {
  padding-left: var(--xq-sp-4);
  position: relative;
}
.sl__tips li::before {
  content: '✦';
  position: absolute;
  left: 0;
  color: var(--xq-star);
}
</style>
