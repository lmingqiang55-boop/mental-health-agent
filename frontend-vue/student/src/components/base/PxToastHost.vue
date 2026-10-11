<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { subscribeToast, dismissToast, type ToastItem } from '@/utils/toast'

const items = ref<ToastItem[]>([])
let unsub: (() => void) | null = null

onMounted(() => {
  unsub = subscribeToast((list) => (items.value = list))
})
onUnmounted(() => unsub?.())
</script>

<template>
  <Teleport to="body">
    <div class="px-toasts" aria-live="polite">
      <transition-group name="px-toast">
        <div
          v-for="t in items"
          :key="t.id"
          class="px-toast"
          :class="`px-toast--${t.type}`"
          @click="dismissToast(t.id)"
        >
          {{ t.message }}
        </div>
      </transition-group>
    </div>
  </Teleport>
</template>

<style scoped>
.px-toasts {
  position: fixed;
  top: calc(var(--xq-sp-4) + env(safe-area-inset-top, 0px));
  left: 50%;
  transform: translateX(-50%);
  z-index: 2000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(92vw, 420px);
  pointer-events: none;
}
.px-toast {
  pointer-events: auto;
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
  padding: 10px 14px;
  font-size: var(--xq-fs-sm);
  line-height: 1.5;
}
.px-toast--success {
  border-left: 8px solid var(--xq-success);
}
.px-toast--warning {
  border-left: 8px solid var(--xq-warning);
}
.px-toast--error {
  border-left: 8px solid var(--xq-danger);
}
.px-toast--info {
  border-left: 8px solid var(--xq-primary);
}
.px-toast-enter-active,
.px-toast-leave-active {
  transition: all var(--xq-dur-base) var(--xq-ease-base);
}
.px-toast-enter-from,
.px-toast-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
