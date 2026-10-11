<script setup lang="ts">
import { useRouter } from 'vue-router'

withDefaults(
  defineProps<{
    title: string
    sub?: string
    back?: boolean
    star?: boolean
  }>(),
  { back: false, star: true },
)

const router = useRouter()

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/home')
}
</script>

<template>
  <header class="px-head">
    <button v-if="back" class="px-head__back" type="button" aria-label="返回" @click="goBack">
      ‹
    </button>
    <div class="px-head__main">
      <h1 class="px-head__title">
        <span v-if="star" class="px-head__star xq-star">✦</span>{{ title }}
      </h1>
      <p v-if="sub" class="px-head__sub">{{ sub }}</p>
    </div>
    <div v-if="$slots.default" class="px-head__extra">
      <slot />
    </div>
  </header>
</template>

<style scoped>
.px-head {
  display: flex;
  align-items: flex-start;
  gap: var(--xq-sp-3);
  margin: var(--xq-sp-2) 0 var(--xq-sp-4);
}
.px-head__back {
  border: none;
  border-radius: 50%;
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
  width: 40px;
  height: 40px;
  font-size: 22px;
  line-height: 1;
  color: var(--xq-text);
  flex: 0 0 auto;
  transition: transform var(--xq-dur-fast) var(--xq-ease-base);
}
.px-head__back:active {
  transform: scale(0.92);
}
.px-head__main {
  flex: 1;
  min-width: 0;
}
.px-head__title {
  font-family: var(--xq-font-pixel);
  font-weight: 700;
  font-size: var(--xq-fs-xl);
  display: flex;
  align-items: center;
  gap: 6px;
}
.px-head__star {
  font-size: 16px;
}
.px-head__sub {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  margin-top: 2px;
}
.px-head__extra {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--xq-sp-2);
}
</style>
