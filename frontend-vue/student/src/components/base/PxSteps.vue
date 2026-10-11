<script setup lang="ts">
withDefaults(
  defineProps<{
    steps: string[]
    current: number
  }>(),
  {},
)
</script>

<template>
  <div class="px-steps">
    <div
      v-for="(s, i) in steps"
      :key="s"
      class="px-steps__item"
      :class="{ 'is-done': i < current, 'is-active': i === current }"
    >
      <span class="px-steps__dot">{{ i < current ? '✓' : i + 1 }}</span>
      <span class="px-steps__label">{{ s }}</span>
      <span v-if="i < steps.length - 1" class="px-steps__line" />
    </div>
  </div>
</template>

<style scoped>
.px-steps {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow-x: auto;
  padding: 4px 0;
  scrollbar-width: none;
}
.px-steps::-webkit-scrollbar {
  display: none;
}
.px-steps__item {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  color: var(--xq-text-2);
  font-size: var(--xq-fs-xs);
}
.px-steps__dot {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--xq-surface-2);
  color: var(--xq-text-2);
  font-weight: 600;
  font-size: 12px;
}
.px-steps__item.is-active {
  color: var(--xq-text);
}
.px-steps__item.is-active .px-steps__dot {
  background: var(--xq-primary);
  color: #fff;
  box-shadow: 0 4px 10px rgba(255, 138, 92, 0.35);
}
.px-steps__item.is-done .px-steps__dot {
  background: var(--xq-success);
  color: #fff;
}
.px-steps__line {
  width: 18px;
  height: 2px;
  background: var(--xq-text-disabled);
  margin: 0 4px;
}
.px-steps__item.is-done .px-steps__line {
  background: var(--xq-success);
}
</style>
