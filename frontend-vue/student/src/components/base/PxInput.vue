<script setup lang="ts">
withDefaults(
  defineProps<{
    modelValue: string
    label?: string
    placeholder?: string
    type?: string
    textarea?: boolean
    rows?: number
    maxlength?: number
    disabled?: boolean
    hint?: string
  }>(),
  { type: 'text', textarea: false, rows: 3, disabled: false },
)

defineEmits<{
  (e: 'update:modelValue', v: string): void
}>()
</script>

<template>
  <label class="px-field" :class="{ 'is-disabled': disabled }">
    <span v-if="label" class="px-field__label">{{ label }}</span>
    <textarea
      v-if="textarea"
      class="px-input px-input--area"
      :value="modelValue"
      :rows="rows"
      :placeholder="placeholder"
      :maxlength="maxlength"
      :disabled="disabled"
      @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
    />
    <input
      v-else
      class="px-input"
      :value="modelValue"
      :type="type"
      :placeholder="placeholder"
      :maxlength="maxlength"
      :disabled="disabled"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <span v-if="hint" class="px-field__hint">{{ hint }}</span>
  </label>
</template>

<style scoped>
.px-field {
  display: block;
}
.px-field__label {
  display: block;
  font-size: var(--xq-fs-sm);
  margin-bottom: 6px;
  color: var(--xq-text-2);
}
.px-field__hint {
  display: block;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  margin-top: 4px;
}
.px-input {
  width: 100%;
  border: 1.5px solid transparent;
  border-radius: var(--xq-radius-m);
  background: var(--xq-surface-2);
  color: var(--xq-text);
  padding: 10px 14px;
  min-height: 44px;
  outline: none;
  transition: border-color var(--xq-dur-fast) var(--xq-ease-base),
    background var(--xq-dur-fast) var(--xq-ease-base),
    box-shadow var(--xq-dur-fast) var(--xq-ease-base);
}
.px-input:focus {
  background: var(--xq-surface);
  border-color: var(--xq-primary);
  box-shadow: 0 0 0 4px rgba(255, 138, 92, 0.14);
}
.px-input::placeholder {
  color: var(--xq-text-disabled);
}
.px-input--area {
  resize: vertical;
  min-height: 88px;
  line-height: 1.6;
}
.is-disabled {
  opacity: 0.6;
}
</style>
