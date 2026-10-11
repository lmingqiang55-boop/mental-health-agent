<script setup lang="ts">
import { useRouter } from 'vue-router'
import PxButton from '@/components/base/PxButton.vue'

const router = useRouter()

const HIGHLIGHTS = [
  { icon: '✎', title: '对话式测评', desc: '像聊天一样回答，语音或文字都可以' },
  { icon: '✦', title: '可解释报告', desc: '五个维度 + 关注提示，看得懂自己的状态' },
  { icon: '♡', title: '小晴陪着你', desc: '报告之后还能继续聊，慢慢来就好' },
]
</script>

<template>
  <div class="launch">
    <div class="launch__sky" aria-hidden="true">
      <span v-for="i in 26" :key="i" class="launch__dot" :style="{ '--i': i }" />
    </div>

    <main class="launch__inner">
      <p class="launch__hello xq-fade-up">欢迎来到</p>
      <h1 class="launch__brand">
        <span class="xq-star">✦</span> 心晴
        <span class="launch__sub">学生端</span>
      </h1>
      <p class="launch__slogan xq-fade-up">
        了解此刻的情绪，<br />
        也照顾好自己的每一天。
      </p>

      <ul class="launch__list">
        <li v-for="h in HIGHLIGHTS" :key="h.title" class="launch__item xq-fade-up">
          <span class="launch__icon">{{ h.icon }}</span>
          <span class="launch__text">
            <strong>{{ h.title }}</strong>
            <em>{{ h.desc }}</em>
          </span>
        </li>
      </ul>

      <div class="launch__actions">
        <PxButton block size="lg" @click="router.push('/home')">进入心晴 ✦</PxButton>
        <PxButton block variant="secondary" @click="router.push('/assess/consent')">
          直接开始测评
        </PxButton>
      </div>

      <p class="launch__note">
        心晴不做诊断，也不给你贴标签。结果只作初步筛查参考，
        任何时候感到撑不住，请拨打 12356 或联系校内心理老师。
      </p>
    </main>
  </div>
</template>

<style scoped>
.launch {
  position: relative;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--xq-sp-6) var(--xq-sp-4);
  overflow: hidden;
}
.launch__sky {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.launch__dot {
  position: absolute;
  width: 3px;
  height: 3px;
  background: var(--xq-primary);
  opacity: 0.5;
  left: calc((var(--i) * 37) % 96 * 1%);
  top: calc((var(--i) * 53) % 92 * 1%);
  animation: xq-twinkle calc(1.6s + (var(--i) % 5) * 0.3s) ease-in-out infinite;
}
.launch__inner {
  position: relative;
  width: 100%;
  max-width: 520px;
  text-align: center;
}
.launch__hello {
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
}
.launch__brand {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-3xl);
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: var(--xq-sp-2);
  margin: var(--xq-sp-2) 0 var(--xq-sp-3);
}
.launch__sub {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.launch__slogan {
  font-size: var(--xq-fs-lg);
  line-height: 1.7;
  margin-bottom: var(--xq-sp-6);
}
.launch__list {
  display: grid;
  gap: var(--xq-sp-3);
  text-align: left;
  margin-bottom: var(--xq-sp-6);
}
.launch__item {
  display: flex;
  gap: var(--xq-sp-3);
  align-items: center;
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
  padding: var(--xq-sp-3) var(--xq-sp-4);
}
.launch__icon {
  font-size: 22px;
  color: var(--xq-primary-deep);
}
.launch__text {
  display: flex;
  flex-direction: column;
  font-size: var(--xq-fs-sm);
}
.launch__text em {
  font-style: normal;
  color: var(--xq-text-2);
  font-size: var(--xq-fs-xs);
}
.launch__actions {
  display: grid;
  gap: var(--xq-sp-3);
}
.launch__note {
  margin-top: var(--xq-sp-6);
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  line-height: 1.7;
}
@media (min-width: 768px) {
  .launch__list {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .launch__item {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
