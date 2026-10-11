<script setup lang="ts">
withDefaults(
  defineProps<{
    text?: string
    icon?: string
  }>(),
  { text: '这里还空空的', icon: '✦' },
)
</script>

<template>
  <div class="px-empty">
    <div class="px-empty__icon xq-star">{{ icon }}</div>
    <p class="px-empty__text">{{ text }}</p>
    <div v-if="$slots.default" class="px-empty__action">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.px-empty {
  text-align: center;
  padding: var(--xq-sp-8) var(--xq-sp-4);
  color: var(--xq-text-2);
}
.px-empty__icon {
  font-size: 34px;
  margin-bottom: var(--xq-sp-3);
}
.px-empty__text {
  font-size: var(--xq-fs-sm);
}
.px-empty__action {
  margin-top: var(--xq-sp-4);
  display: flex;
  justify-content: center;
}
</style>
