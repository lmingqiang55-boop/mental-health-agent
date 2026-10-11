<script setup lang="ts">
withDefaults(
  defineProps<{
    role?: 'assistant' | 'user' | 'system'
    speaking?: boolean
  }>(),
  { role: 'assistant', speaking: false },
)
</script>

<template>
  <div class="px-bubble" :class="`px-bubble--${role}`">
    <div v-if="role === 'assistant'" class="px-bubble__avatar" aria-hidden="true">
      <span class="xq-star">✦</span>
    </div>
    <div class="px-bubble__box">
      <slot />
      <span v-if="speaking" class="px-bubble__speaking xq-star">🔊</span>
    </div>
  </div>
</template>

<style scoped>
.px-bubble {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  max-width: 92%;
}
.px-bubble--user {
  flex-direction: row-reverse;
  margin-left: auto;
}
.px-bubble__avatar {
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ffb84d 0%, var(--xq-primary) 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  box-shadow: 0 4px 10px rgba(255, 138, 92, 0.3);
}
.px-bubble__box {
  position: relative;
  border-radius: 18px;
  border-top-left-radius: 6px;
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
  padding: 10px 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.px-bubble--user .px-bubble__box {
  border-radius: 18px;
  border-top-right-radius: 6px;
  background: var(--xq-primary);
  color: #fff;
  box-shadow: 0 6px 14px rgba(255, 138, 92, 0.28);
}
.px-bubble--system .px-bubble__box {
  background: var(--xq-surface-2);
  box-shadow: none;
  color: var(--xq-text-2);
  font-size: var(--xq-fs-sm);
  border-radius: 999px;
  margin: 0 auto;
}
.px-bubble__speaking {
  margin-left: 6px;
}
</style>
