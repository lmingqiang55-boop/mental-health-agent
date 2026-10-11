<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    modelValue: boolean
    label?: string
    disabled?: boolean
  }>(),
  { disabled: false },
)
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

function toggle() {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <button
    class="px-switch"
    :class="{ 'is-on': modelValue, 'is-disabled': disabled }"
    type="button"
    role="switch"
    :aria-checked="modelValue"
    @click="toggle"
  >
    <span class="px-switch__track"><span class="px-switch__knob" /></span>
    <span v-if="label" class="px-switch__label">{{ label }}</span>
  </button>
</template>

<style scoped>
.px-switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: none;
  background: transparent;
  padding: 4px 0;
  color: var(--xq-text);
}
.px-switch__track {
  width: 46px;
  height: 28px;
  border-radius: 999px;
  background: var(--xq-surface-2);
  box-shadow: inset 0 1px 3px rgba(62, 47, 38, 0.12);
  position: relative;
  transition: background var(--xq-dur-fast) var(--xq-ease-base);
}
.px-switch__knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 2px 6px rgba(62, 47, 38, 0.2);
  transition: transform var(--xq-dur-fast) var(--xq-ease-base);
}
.is-on .px-switch__track {
  background: var(--xq-primary);
}
.is-on .px-switch__knob {
  transform: translateX(18px);
  background: #fff;
}
.is-disabled {
  opacity: 0.5;
}
</style>
