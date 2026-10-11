<script setup lang="ts">
import { watch, onUnmounted } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    closable?: boolean
    width?: string
  }>(),
  { closable: true, width: '440px' },
)

const emit = defineEmits<{ (e: 'close'): void }>()

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.closable) emit('close')
}

watch(
  () => props.open,
  (v) => {
    document.body.style.overflow = v ? 'hidden' : ''
    if (v) window.addEventListener('keydown', onKey)
    else window.removeEventListener('keydown', onKey)
  },
  { immediate: true },
)

onUnmounted(() => {
  document.body.style.overflow = ''
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Teleport to="body">
    <transition name="px-modal">
      <div v-if="open" class="px-modal" role="dialog" aria-modal="true">
        <div class="px-modal__mask" @click="closable && emit('close')" />
        <div class="px-modal__panel" :style="{ maxWidth: width }">
          <header v-if="title || $slots.header" class="px-modal__head">
            <slot name="header">
              <span class="px-modal__title">{{ title }}</span>
            </slot>
            <button v-if="closable" class="px-modal__close" aria-label="关闭" @click="emit('close')">
              ✕
            </button>
          </header>
          <div class="px-modal__body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="px-modal__foot">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.px-modal {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--xq-sp-4);
}
.px-modal__mask {
  position: absolute;
  inset: 0;
  background: rgba(62, 47, 38, 0.42);
}
.px-modal__panel {
  position: relative;
  width: 100%;
  background: var(--xq-surface);
  border-radius: var(--xq-radius-l);
  box-shadow: var(--xq-shadow-pixel-lg);
  max-height: calc(100vh - 32px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.px-modal__head {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-2);
  padding: var(--xq-sp-4) var(--xq-sp-4) var(--xq-sp-2);
}
.px-modal__title {
  font-family: var(--xq-font-pixel);
  font-weight: 600;
  font-size: var(--xq-fs-lg);
  flex: 1;
}
.px-modal__close {
  border: none;
  border-radius: 50%;
  background: var(--xq-surface-2);
  width: 30px;
  height: 30px;
  font-size: 14px;
  color: var(--xq-text-2);
}
.px-modal__body {
  padding: var(--xq-sp-4);
  overflow-y: auto;
}
.px-modal__foot {
  padding: 0 var(--xq-sp-4) var(--xq-sp-4);
  display: flex;
  gap: var(--xq-sp-3);
  justify-content: flex-end;
}
.px-modal-enter-active,
.px-modal-leave-active {
  transition: opacity var(--xq-dur-base) var(--xq-ease-base);
}
.px-modal-enter-from,
.px-modal-leave-to {
  opacity: 0;
}
/* 手机：底部弹出全宽 */
@media (max-width: 640px) {
  .px-modal {
    align-items: flex-end;
    padding: 0;
  }
  .px-modal__panel {
    max-width: none !important;
    border-radius: var(--xq-radius-l) var(--xq-radius-l) 0 0;
    max-height: 88vh;
  }
  .px-modal__foot {
    flex-direction: column-reverse;
  }
  .px-modal__foot :deep(.px-btn) {
    width: 100%;
  }
}
</style>
