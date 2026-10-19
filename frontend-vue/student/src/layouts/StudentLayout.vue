<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useBreakpoint } from '@/composables/useBreakpoint'
import EmergencyFab from '@/components/business/EmergencyFab.vue'

const route = useRoute()
const { useTabBar } = useBreakpoint()

const NAV = [
  { to: '/home', label: '首页', icon: '⌂' },
  { to: '/assess', label: '测评', icon: '✎' },
  { to: '/heal', label: '心理自助', icon: '✦' },
  { to: '/me', label: '我的', icon: '☺' },
]

const activeKey = computed(() => {
  const p = route.path
  if (p.startsWith('/assess')) return '/assess'
  if (p.startsWith('/heal')) return '/heal'
  if (p.startsWith('/me')) return '/me'
  return '/home'
})
</script>

<template>
  <div class="layout" :class="{ 'layout--tabbar': useTabBar }">
    <!-- 桌面顶部导航 -->
    <header v-if="!useTabBar" class="topnav">
      <div class="topnav__inner">
        <router-link to="/home" class="brand">
          <span class="brand__dot" aria-hidden="true">☀</span>
          <span class="brand__name">心晴</span>
          <span class="brand__sub">学生端</span>
        </router-link>
        <nav class="topnav__links">
          <router-link
            v-for="n in NAV"
            :key="n.to"
            :to="n.to"
            class="topnav__link"
            :class="{ 'is-active': activeKey === n.to }"
          >
            {{ n.label }}
          </router-link>
        </nav>
      </div>
    </header>

    <!-- 移动端顶栏 -->
    <header v-else class="mobilehead">
      <router-link to="/home" class="brand brand--sm">
        <span class="brand__dot" aria-hidden="true">☀</span>
        <span class="brand__name">心晴</span>
      </router-link>
    </header>

    <main class="layout__main">
      <router-view />
    </main>

    <EmergencyFab />

    <!-- 移动端底部 Tab -->
    <nav v-if="useTabBar" class="tabbar">
      <router-link
        v-for="n in NAV"
        :key="n.to"
        :to="n.to"
        class="tabbar__item"
        :class="{ 'is-active': activeKey === n.to }"
      >
        <span class="tabbar__icon">{{ n.icon }}</span>
        <span class="tabbar__label">{{ n.label }}</span>
      </router-link>
    </nav>
  </div>
</template>

<style scoped>
.layout {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}
.layout--tabbar {
  padding-bottom: calc(var(--xq-tabbar-h) + env(safe-area-inset-bottom, 0px));
}
.layout__main {
  flex: 1;
  min-width: 0;
}

/* ---- 桌面顶栏 ---- */
.topnav {
  position: sticky;
  top: 0;
  z-index: 800;
  background: rgba(255, 253, 249, 0.9);
  border-bottom: 1px solid rgba(240, 218, 203, 0.72);
  backdrop-filter: blur(16px);
  box-shadow: 0 2px 12px rgba(214, 150, 108, 0.05);
}
.topnav__inner {
  max-width: var(--xq-maxw);
  margin: 0 auto;
  height: var(--xq-topnav-h);
  display: flex;
  align-items: center;
  gap: var(--xq-sp-6);
  padding: 0 var(--xq-sp-6);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 6px;
  color: var(--xq-text);
}
.brand__dot {
  font-size: 18px;
  color: var(--xq-primary);
}
.brand__name {
  font-weight: 700;
  font-size: var(--xq-fs-xl);
}
.brand__sub {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.topnav__links {
  display: flex;
  gap: var(--xq-sp-2);
  flex: 1;
  justify-content: flex-end;
}
.topnav__link {
  padding: 8px 16px;
  border-radius: 999px;
  color: var(--xq-text-2);
  font-size: var(--xq-fs-base);
  transition: background var(--xq-dur-fast) var(--xq-ease-base),
    color var(--xq-dur-fast) var(--xq-ease-base);
}
.topnav__link.is-active {
  color: var(--xq-primary-deep);
  font-weight: 600;
  background: var(--xq-primary-soft);
}

/* ---- 移动顶栏 ---- */
.mobilehead {
  position: sticky;
  top: 0;
  z-index: 800;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 52px;
  padding: 0 var(--xq-sp-4);
  background: rgba(255, 253, 249, 0.9);
  border-bottom: 1px solid rgba(240, 218, 203, 0.72);
  backdrop-filter: blur(16px);
}
.brand--sm .brand__name {
  font-size: var(--xq-fs-lg);
}

/* ---- 底部 Tab ---- */
.tabbar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 900;
  display: flex;
  height: calc(var(--xq-tabbar-h) + env(safe-area-inset-bottom, 0px));
  padding-bottom: env(safe-area-inset-bottom, 0px);
  background: rgba(255, 253, 249, 0.94);
  backdrop-filter: blur(12px);
  box-shadow: 0 -4px 16px rgba(214, 150, 108, 0.1);
}
.tabbar__item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: var(--xq-text-2);
  transition: color var(--xq-dur-fast) var(--xq-ease-base);
}
.tabbar__item.is-active {
  color: var(--xq-primary-deep);
}
.tabbar__item.is-active .tabbar__icon {
  background: var(--xq-primary-soft);
  border-radius: 999px;
  padding: 2px 14px;
}
.tabbar__icon {
  font-size: 18px;
  line-height: 1.4;
  transition: background var(--xq-dur-fast) var(--xq-ease-base);
}
.tabbar__label {
  font-size: 11px;
}
</style>
