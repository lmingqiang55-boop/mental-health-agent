<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string
    tone?: 'default' | 'primary' | 'secondary' | 'warn' | 'danger'
    pad?: boolean
    clickable?: boolean
  }>(),
  { tone: 'default', pad: true, clickable: false },
)
</script>

<template>
  <section class="px-card" :class="[`px-card--${tone}`, { 'px-card--clickable': clickable }]">
    <header v-if="title || $slots.header" class="px-card__head">
      <slot name="header">
        <span class="px-card__title">{{ title }}</span>
      </slot>
    </header>
    <div class="px-card__body" :class="{ 'px-card__body--nopad': !pad }">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="px-card__foot">
      <slot name="footer" />
    </footer>
  </section>
</template>

<style scoped>
.px-card {
  border-radius: var(--xq-radius-l);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel);
}
.px-card__head {
  padding: var(--xq-sp-4) var(--xq-sp-4) 0;
  display: flex;
  align-items: center;
  gap: var(--xq-sp-2);
}
.px-card__title {
  font-family: var(--xq-font-pixel);
  font-weight: 600;
  font-size: var(--xq-fs-base);
}
.px-card__body {
  padding: var(--xq-sp-4);
}
.px-card__body--nopad {
  padding: 0;
}
.px-card__foot {
  padding: 0 var(--xq-sp-4) var(--xq-sp-4);
}
.px-card--clickable {
  cursor: pointer;
  transition: transform var(--xq-dur-fast) var(--xq-ease-base),
    box-shadow var(--xq-dur-fast) var(--xq-ease-base);
}
.px-card--clickable:hover {
  transform: translateY(-3px);
  box-shadow: var(--xq-shadow-pixel-lg);
}
.px-card--primary {
  background: linear-gradient(135deg, #fff 0%, var(--xq-primary-soft) 100%);
}
.px-card--secondary {
  background: linear-gradient(135deg, #fff 0%, var(--xq-secondary-soft) 100%);
}
.px-card--warn {
  background: linear-gradient(135deg, #fff 0%, rgba(242, 184, 75, 0.16) 100%);
}
.px-card--danger {
  background: linear-gradient(135deg, #fff 0%, rgba(232, 106, 94, 0.12) 100%);
}
</style>
