<script setup lang="ts">
withDefaults(
  defineProps<{
    modelValue: number | null
    compact?: boolean
  }>(),
  { compact: false },
)
const emit = defineEmits<{ (e: 'update:modelValue', v: number): void }>()

/** 1~5：越大越积极（与 /api/heal/mood 的 mood 数值一致）。 */
const MOODS = [
  { value: 1, emoji: '🌧', label: '很难过' },
  { value: 2, emoji: '☁️', label: '有点低落' },
  { value: 3, emoji: '🌤', label: '一般' },
  { value: 4, emoji: '🌈', label: '还不错' },
  { value: 5, emoji: '☀️', label: '很开心' },
]
</script>

<template>
  <div class="mood-picker" :class="{ 'mood-picker--compact': compact }">
    <button
      v-for="m in MOODS"
      :key="m.value"
      type="button"
      class="mood-picker__item"
      :class="{ 'is-on': modelValue === m.value }"
      @click="emit('update:modelValue', m.value)"
    >
      <span class="mood-picker__emoji">{{ m.emoji }}</span>
      <span v-if="!compact" class="mood-picker__label">{{ m.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.mood-picker {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--xq-sp-2);
}
.mood-picker__item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: var(--xq-sp-1) 0;
  border: none;
  background: transparent;
  color: var(--xq-text-2);
}
.mood-picker__emoji {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
  font-size: 26px;
  line-height: 1;
  transition: transform var(--xq-dur-fast) var(--xq-ease-base),
    background var(--xq-dur-fast) var(--xq-ease-base),
    box-shadow var(--xq-dur-fast) var(--xq-ease-base);
}
.mood-picker__item:active .mood-picker__emoji {
  transform: scale(0.94);
}
.mood-picker__item.is-on {
  color: var(--xq-text);
}
.mood-picker__item.is-on .mood-picker__emoji {
  background: linear-gradient(135deg, #ffa176 0%, var(--xq-primary) 60%, var(--xq-primary-deep) 100%);
  box-shadow: 0 8px 18px rgba(255, 138, 92, 0.38);
  transform: scale(1.12);
}
.mood-picker__label {
  font-size: var(--xq-fs-xs);
  white-space: nowrap;
}
.mood-picker--compact .mood-picker__emoji {
  width: 44px;
  height: 44px;
  font-size: 20px;
}
</style>
