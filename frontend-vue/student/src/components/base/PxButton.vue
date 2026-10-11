<script setup lang="ts">
import { computed } from 'vue'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'hotline'
type Size = 'sm' | 'md' | 'lg'

const props = withDefaults(
  defineProps<{
    variant?: Variant
    size?: Size
    block?: boolean
    disabled?: boolean
    loading?: boolean
    type?: 'button' | 'submit'
  }>(),
  { variant: 'primary', size: 'md', block: false, disabled: false, loading: false, type: 'button' },
)

const emit = defineEmits<{ (e: 'click', ev: MouseEvent): void }>()

const classes = computed(() => [
  'px-btn',
  `px-btn--${props.variant}`,
  `px-btn--${props.size}`,
  { 'px-btn--block': props.block, 'is-disabled': props.disabled || props.loading },
])

function onClick(ev: MouseEvent) {
  if (props.disabled || props.loading) return
  emit('click', ev)
}
</script>

<template>
  <button :class="classes" :type="type" :disabled="disabled || loading" @click="onClick">
    <span v-if="loading" class="px-btn__spin xq-star">✦</span>
    <slot />
  </button>
</template>

<style scoped>
.px-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-family: var(--xq-font-base);
  font-weight: 600;
  border: none;
  border-radius: 999px;
  background: var(--xq-surface-2);
  color: var(--xq-text);
  box-shadow: var(--xq-shadow-pixel-sm);
  transition: transform var(--xq-dur-fast) var(--xq-ease-base),
    box-shadow var(--xq-dur-fast) var(--xq-ease-base),
    background var(--xq-dur-fast) var(--xq-ease-base);
  user-select: none;
  white-space: nowrap;
}
.px-btn:active:not(.is-disabled) {
  transform: scale(0.96);
}
.px-btn--sm {
  padding: 7px 14px;
  font-size: var(--xq-fs-sm);
}
.px-btn--md {
  padding: 10px 20px;
  font-size: var(--xq-fs-base);
  min-height: 44px;
}
.px-btn--lg {
  padding: 14px 26px;
  font-size: var(--xq-fs-lg);
  min-height: 52px;
}
.px-btn--block {
  display: flex;
  width: 100%;
}
.px-btn--primary {
  background: linear-gradient(135deg, #ffa176 0%, var(--xq-primary) 60%, var(--xq-primary-deep) 100%);
  color: #fff;
  box-shadow: 0 6px 16px rgba(255, 138, 92, 0.35);
}
.px-btn--secondary {
  background: linear-gradient(135deg, #ffd38e 0%, var(--xq-secondary) 100%);
  color: #6b4a1a;
}
.px-btn--ghost {
  background: transparent;
  box-shadow: none;
  color: var(--xq-primary-deep);
}
.px-btn--ghost:active:not(.is-disabled) {
  transform: none;
  background: var(--xq-primary-soft);
}
.px-btn--danger {
  background: var(--xq-danger);
  color: #fff;
}
.px-btn--hotline {
  background: var(--xq-hotline);
  color: #fff;
  box-shadow: 0 6px 16px rgba(255, 107, 74, 0.35);
}
.is-disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.px-btn__spin {
  animation: xq-twinkle 0.8s linear infinite;
}
</style>
