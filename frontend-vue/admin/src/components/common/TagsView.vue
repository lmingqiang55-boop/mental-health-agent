<template>
  <div class="tags-view">
    <el-scrollbar class="tags-scroll">
      <div class="tags-wrap">
        <div
          v-for="t in tags"
          :key="t.path"
          class="tag-item"
          :class="{ active: t.path === route.path }"
          @click="go(t)"
          @contextmenu.prevent="openMenu(t, $event)"
        >
          <span class="tag-dot" />
          <span class="tag-text">{{ t.title }}</span>
          <el-icon v-if="!t.affix" class="tag-close" @click.stop="close(t)"><Close /></el-icon>
        </div>
      </div>
    </el-scrollbar>

    <ul v-show="menuVisible" class="ctx-menu" :style="{ left: `${menuLeft}px`, top: `${menuTop}px` }">
      <li @click="closeOthers">关闭其他</li>
      <li @click="closeAll">关闭全部</li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteLocationNormalizedLoaded } from 'vue-router'
import { Close } from '@element-plus/icons-vue'

interface Tag {
  path: string
  title: string
  affix?: boolean
}

const route = useRoute()
const router = useRouter()

const HOME: Tag = { path: '/dashboard', title: '工作台', affix: true }
const tags = ref<Tag[]>([{ ...HOME }])

const menuVisible = ref(false)
const menuLeft = ref(0)
const menuTop = ref(0)

function addTag(r: RouteLocationNormalizedLoaded) {
  if (r.path === '/login' || r.path === '/') return
  if (tags.value.some((t) => t.path === r.path)) return
  tags.value.push({ path: r.path, title: (r.meta.title as string) ?? '页面' })
}

function go(t: Tag) {
  if (t.path !== route.path) router.push(t.path)
}

function closeTag(t: Tag) {
  const idx = tags.value.findIndex((x) => x.path === t.path)
  if (idx < 0) return
  tags.value.splice(idx, 1)
  // 关闭的是当前页 → 回到最后一个标签
  if (t.path === route.path) {
    const next = tags.value[tags.value.length - 1] ?? HOME
    router.push(next.path)
  }
}

function close(t: Tag) {
  closeTag(t)
}

function closeOthers() {
  tags.value = tags.value.filter((t) => t.affix || t.path === route.path)
  menuVisible.value = false
}

function closeAll() {
  tags.value = tags.value.filter((t) => t.affix)
  menuVisible.value = false
  if (route.path !== HOME.path) router.push(HOME.path)
}

function openMenu(t: Tag, e: MouseEvent) {
  if (t.affix) return
  go(t)
  menuLeft.value = e.clientX
  menuTop.value = e.clientY
  menuVisible.value = true
}

function closeMenu() {
  menuVisible.value = false
}

watch(() => route.path, () => addTag(route), { immediate: true })
watch(menuVisible, (v) => {
  if (v) document.addEventListener('click', closeMenu)
  else document.removeEventListener('click', closeMenu)
})
onBeforeUnmount(() => document.removeEventListener('click', closeMenu))
</script>

<style scoped>
.tags-view {
  height: 40px;
  background: #fff;
  border-bottom: 1px solid var(--xq-border);
  display: flex;
  align-items: center;
  padding: 0 12px;
}
.tags-scroll { width: 100%; }
.tags-wrap { display: flex; align-items: center; gap: 8px; padding: 6px 0; }

.tag-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--xq-border);
  border-radius: 6px;
  background: #fff;
  color: var(--xq-text-secondary);
  font-size: 12px;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.tag-item:hover { color: var(--xq-primary); border-color: var(--xq-primary-light); }
.tag-item.active {
  background: var(--xq-primary-light);
  border-color: var(--xq-primary-light);
  color: var(--xq-primary-deep);
  font-weight: 600;
}
.tag-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: 0.5; }
.tag-item.active .tag-dot { opacity: 1; }
.tag-close {
  font-size: 12px;
  border-radius: 50%;
}
.tag-close:hover { background: var(--xq-primary); color: #fff; }

.ctx-menu {
  position: fixed;
  z-index: 3000;
  margin: 0;
  padding: 4px;
  list-style: none;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(30, 41, 59, 0.18);
  font-size: 13px;
}
.ctx-menu li {
  padding: 6px 16px;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
}
.ctx-menu li:hover { background: var(--xq-primary-lighter); color: var(--xq-primary-deep); }
</style>
