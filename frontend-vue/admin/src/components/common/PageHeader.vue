<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ title }}</h2>
        <p class="page-subtitle">{{ subtitle }}</p>
      </div>
      <slot name="extra" />
    </div>
    <slot />
  </div>
</template>

<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>
