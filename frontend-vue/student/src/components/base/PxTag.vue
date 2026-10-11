<script setup lang="ts">
withDefaults(
  defineProps<{
    tone?: 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'danger' | 'star'
    size?: 'sm' | 'md'
  }>(),
  { tone: 'default', size: 'md' },
)
</script>

<template>
  <span class="px-tag" :class="[`px-tag--${tone}`, `px-tag--${size}`]">
    <slot />
  </span>
</template>

<style scoped>
.px-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 999px;
  background: var(--xq-surface-2);
  color: var(--xq-text-2);
  font-size: var(--xq-fs-xs);
  line-height: 1.4;
  padding: 3px 10px;
  white-space: nowrap;
}
.px-tag--sm {
  padding: 2px 8px;
  font-size: 11px;
}
.px-tag--primary {
  background: var(--xq-primary-soft);
  color: var(--xq-primary-deep);
}
.px-tag--secondary {
  background: var(--xq-secondary-soft);
  color: var(--xq-secondary-deep);
}
.px-tag--success {
  background: rgba(111, 191, 143, 0.16);
  color: #3d8a5f;
}
.px-tag--warning {
  background: rgba(242, 184, 75, 0.2);
  color: #a8742a;
}
.px-tag--danger {
  background: rgba(232, 106, 94, 0.14);
  color: var(--xq-danger);
}
.px-tag--star {
  background: rgba(255, 184, 77, 0.22);
  color: #b07a1f;
}
</style>
