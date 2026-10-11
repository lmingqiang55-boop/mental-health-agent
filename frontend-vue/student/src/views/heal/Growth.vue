<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxTag from '@/components/base/PxTag.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import { healApi } from '@/api'
import type { GrowthResponse } from '@/api/types'
import { useStudentStore } from '@/stores/student'

const student = useStudentStore()

const data = ref<GrowthResponse | null>(null)
const loading = ref(true)

const tagList = computed(() => {
  const counts = data.value?.mood_tag_counts ?? {}
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
})

const maxTag = computed(() => (tagList.value.length ? tagList.value[0][1] : 1))

/** 近 14 天心情：缺失的日期留空柱。 */
const last14 = computed(() => {
  const map = new Map((data.value?.moods ?? []).map((m) => [m.date, m.mood]))
  const out: { date: string; mood: number | null }[] = []
  for (let i = 13; i >= 0; i--) {
    const date = dayjs().subtract(i, 'day').format('YYYY-MM-DD')
    out.push({ date, mood: map.get(date) ?? null })
  }
  return out
})

const hasAny = computed(
  () =>
    !!data.value &&
    (data.value.mood_days > 0 ||
      data.value.habit_days > 0 ||
      data.value.focus_sessions > 0 ||
      data.value.streak > 0),
)

async function load() {
  try {
    data.value = await healApi.growth(student.studentRef, 90)
  } catch {
    /* 静默降级 */
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="成长回顾" sub="看看这 90 天里，你走过的痕迹" back />

    <PxEmpty v-if="!loading && !hasAny" text="还没有足够的数据，先去记录几天心情吧" />
    <template v-else-if="data">
      <div class="gr__stats">
        <div class="gr__stat">
          <strong>{{ data.mood_days }}</strong>
          <em>记录心情天数</em>
        </div>
        <div class="gr__stat">
          <strong>{{ data.habit_days }}</strong>
          <em>打卡天数</em>
        </div>
        <div class="gr__stat">
          <strong>{{ data.streak }}</strong>
          <em>当前连续</em>
        </div>
        <div class="gr__stat">
          <strong>{{ data.focus_minutes }}</strong>
          <em>专注分钟</em>
        </div>
      </div>

      <PxCard class="gr__block" title="近 14 天心情">
        <div class="gr__bars">
          <div v-for="d in last14" :key="d.date" class="gr__bar-col" :title="d.date">
            <span
              class="gr__bar"
              :class="{ 'is-empty': d.mood === null, [`is-lv${d.mood ?? 0}`]: d.mood !== null }"
              :style="{ height: `${(d.mood ?? 0) * 20}%` }"
            />
          </div>
        </div>
        <p class="xq-muted">柱子越高，当天的整体心情越好。</p>
      </PxCard>

      <PxCard class="gr__block" title="常出现的心情标签">
        <PxEmpty v-if="!tagList.length" text="还没有心情标签记录" />
        <div v-else class="gr__tags">
          <span
            v-for="[tag, count] in tagList"
            :key="tag"
            class="gr__tag"
            :style="{ fontSize: `${12 + (count / maxTag) * 8}px` }"
          >
            <PxTag tone="primary">{{ tag }}</PxTag>
            <em class="gr__tag-count">×{{ count }}</em>
          </span>
        </div>
      </PxCard>

      <PxCard class="gr__block" title="一路走来">
        <ul class="gr__facts">
          <li>
            <span>累计记录心情</span>
            <b>{{ data.mood_days }} 天</b>
          </li>
          <li>
            <span>累计点亮打卡</span>
            <b>{{ data.habit_days }} 天</b>
          </li>
          <li>
            <span>累计专注</span>
            <b>{{ data.focus_sessions }} 次 · {{ data.focus_minutes }} 分钟</b>
          </li>
        </ul>
      </PxCard>
    </template>

    <p class="xq-disclaimer">
      成长回顾只是为了让你看见自己的坚持。数字高低不代表你的努力多少，慢慢来就好。
    </p>
  </div>
</template>

<style scoped>
.gr__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--xq-sp-3);
}
.gr__stat {
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
  padding: var(--xq-sp-4);
  text-align: center;
}
.gr__stat strong {
  display: block;
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-2xl);
  color: var(--xq-primary-deep);
}
.gr__stat em {
  font-style: normal;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.gr__block {
  margin-top: var(--xq-sp-3);
}
.gr__bars {
  display: grid;
  grid-template-columns: repeat(14, minmax(0, 1fr));
  align-items: end;
  gap: 4px;
  height: 120px;
  margin-bottom: var(--xq-sp-2);
}
.gr__bar-col {
  display: flex;
  align-items: flex-end;
  height: 100%;
}
.gr__bar {
  width: 100%;
  min-height: 4px;
  background: var(--xq-primary);
  border: 2px solid var(--xq-text);
}
.gr__bar.is-empty {
  background: var(--xq-surface-2);
  border-color: var(--xq-text-disabled);
}
.gr__bar.is-lv1 {
  background: var(--xq-level-high);
}
.gr__bar.is-lv2 {
  background: var(--xq-level-moderate);
}
.gr__bar.is-lv3 {
  background: var(--xq-level-mild);
}
.gr__bar.is-lv4,
.gr__bar.is-lv5 {
  background: var(--xq-level-low);
}
.gr__tags {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--xq-sp-3);
}
.gr__tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.gr__tag-count {
  font-style: normal;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.gr__facts {
  display: grid;
  gap: var(--xq-sp-2);
}
.gr__facts li {
  display: flex;
  justify-content: space-between;
  font-size: var(--xq-fs-sm);
  border-bottom: 1px dashed var(--xq-text-disabled);
  padding-bottom: var(--xq-sp-2);
}
.gr__facts li:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.gr__facts b {
  color: var(--xq-primary-deep);
}
</style>
