<script setup lang="ts">
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import AudioScape from '@/components/business/AudioScape.vue'

const STEPS = [
  '戴上耳机，或把音量调到刚好能盖过环境噪音。',
  '闭上眼，把注意力放到声音上，不去评价它好不好听。',
  '走神了就把耳朵重新「拉」回声音，像重新坐下一样。',
  '听 5~10 分钟就够，觉得舒服可以再久一点。',
]
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="声音疗愈" sub="雨声、海浪、篝火等实时音景" back />

    <PxCard title="挑一个此刻想听的">
      <AudioScape />
    </PxCard>

    <PxCard class="st__block" title="怎么听更放松">
      <ol class="st__steps">
        <li v-for="(s, i) in STEPS" :key="s">
          <span class="st__no">{{ i + 1 }}</span>
          <span>{{ s }}</span>
        </li>
      </ol>
    </PxCard>

    <p class="xq-disclaimer">
      声音只是帮你专注的「扶手」，真正起作用的是把注意力放回当下的那一刻。音量以不伤耳朵为准。
    </p>
  </div>
</template>

<style scoped>
.st__block {
  margin-top: var(--xq-sp-3);
}
.st__steps {
  display: grid;
  gap: var(--xq-sp-3);
}
.st__steps li {
  display: flex;
  gap: var(--xq-sp-3);
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
}
.st__no {
  flex: 0 0 auto;
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-xs);
  border: var(--xq-border-pixel-thin);
  background: var(--xq-primary-soft);
}
</style>
