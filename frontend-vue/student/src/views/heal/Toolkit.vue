<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxTag from '@/components/base/PxTag.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import MoodPicker from '@/components/business/MoodPicker.vue'
import { healApi } from '@/api'
import type { HealContent } from '@/api/types'
import { HEAL_FUNCTIONS } from '@/views/heal/functions'

/** 工具箱下的 5 个练习入口（数据源与心理自助主页一致）。 */
const TOOLS = HEAL_FUNCTIONS.filter((f) => f.group === '工具' && f.path.startsWith('/heal/toolkit/'))

const contents = ref<HealContent[]>([])
const tags = ref<string[]>([])
const loading = ref(true)
const mood = ref<number | null>(null)

const activeTag = ref('')

const shown = computed(() =>
  activeTag.value ? contents.value.filter((c) => c.tags?.includes(activeTag.value)) : contents.value,
)

async function load() {
  loading.value = true
  try {
    const res = await healApi.contents(mood.value ?? undefined)
    contents.value = res.contents
    tags.value = res.tags
    if (activeTag.value && !res.tags.includes(activeTag.value)) activeTag.value = ''
  } catch {
    /* 静默降级 */
  } finally {
    loading.value = false
  }
}

function onMood() {
  activeTag.value = ''
  void load()
}

watch(mood, onMood)

function pickTag(t: string) {
  activeTag.value = activeTag.value === t ? '' : t
}

onMounted(load)
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="练习工具箱" sub="挑一个小练习，陪自己待一会儿" back />

    <div class="tk__grid">
      <router-link
        v-for="t in TOOLS"
        :key="t.key"
        :to="t.path"
        class="tk__tool"
      >
        <span class="tk__tool-icon xq-star">{{ t.icon }}</span>
        <span class="tk__tool-title">{{ t.title }}</span>
        <span class="tk__tool-desc">{{ t.desc }}</span>
      </router-link>
    </div>

    <PxCard class="tk__filter" title="按此刻的心情看看">
      <MoodPicker v-model="mood" compact />
      <p class="xq-muted">不选也可以，直接看下面的全部内容。</p>
    </PxCard>

    <h2 class="xq-section-title">小晴准备的内容</h2>
    <div v-if="tags.length" class="tk__tags">
      <button
        v-for="t in tags"
        :key="t"
        type="button"
        class="tk__tag"
        :class="{ 'is-on': activeTag === t }"
        @click="pickTag(t)"
      >
        {{ t }}
      </button>
    </div>

    <PxEmpty v-if="!loading && !shown.length" text="这里暂时没有内容，试试换一个心情" />
    <ul v-else class="tk__list">
      <li v-for="c in shown" :key="c.id">
        <PxCard>
          <div class="tk__content-head">
            <strong>{{ c.title }}</strong>
            <PxTag v-if="c.category" tone="secondary" size="sm">{{ c.category }}</PxTag>
          </div>
          <p v-if="c.summary" class="tk__summary">{{ c.summary }}</p>
          <p v-else-if="c.body" class="tk__summary">{{ c.body }}</p>
          <div v-if="c.tags?.length" class="tk__content-tags">
            <PxTag v-for="t in c.tags" :key="t" size="sm" tone="primary">{{ t }}</PxTag>
          </div>
        </PxCard>
      </li>
    </ul>

    <p class="xq-disclaimer">
      练习没有对错，也不必都做完。找到一个此刻愿意试试的就够了。
    </p>
  </div>
</template>

<style scoped>
.tk__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--xq-sp-3);
}
.tk__tool {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: var(--xq-border-pixel);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel);
  padding: var(--xq-sp-4);
  color: inherit;
  transition: transform var(--xq-dur-fast) var(--xq-ease-base),
    box-shadow var(--xq-dur-fast) var(--xq-ease-base);
}
.tk__tool:hover {
  transform: translate(-2px, -2px);
  box-shadow: var(--xq-shadow-pixel-lg);
}
.tk__tool-icon {
  font-size: 26px;
  line-height: 1;
  color: var(--xq-primary-deep);
}
.tk__tool-title {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-base);
}
.tk__tool-desc {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  line-height: 1.5;
}
.tk__filter {
  margin-top: var(--xq-sp-3);
}
.tk__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--xq-sp-2);
  margin-bottom: var(--xq-sp-3);
}
.tk__tag {
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  color: var(--xq-text-2);
  padding: 4px 12px;
  font-size: var(--xq-fs-xs);
}
.tk__tag.is-on {
  background: var(--xq-primary-soft);
  color: var(--xq-text);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.tk__list {
  display: grid;
  gap: var(--xq-sp-3);
}
.tk__content-head {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-2);
  margin-bottom: var(--xq-sp-2);
}
.tk__content-head strong {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-base);
}
.tk__summary {
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
  white-space: pre-wrap;
}
.tk__content-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--xq-sp-2);
}
@media (min-width: 640px) {
  .tk__grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
