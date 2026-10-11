<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import { healApi } from '@/api'
import type { HabitRecord } from '@/api/types'
import { useStudentStore } from '@/stores/student'
import { fmtDate, todayStr } from '@/utils/format'
import { toastSuccess, toastWarn } from '@/utils/toast'

const student = useStudentStore()

/** 打卡候选：都是「小到可以做到」的事，重点是持续性而非强度。 */
const ITEMS = [
  '喝够水',
  '吃了早饭',
  '出门走走',
  '和一个人说说话',
  '按时上床',
  '做了一件喜欢的小事',
  '深呼吸几次',
  '离开屏幕休息',
]

const picked = ref<string[]>([])
const records = ref<HabitRecord[]>([])
const streak = ref(0)
const totalDays = ref(0)
const saving = ref(false)

const doneToday = computed(() => records.value.some((r) => r.date === todayStr()))

const last14 = computed(() => {
  const set = new Set(records.value.map((r) => r.date))
  const out: { date: string; done: boolean }[] = []
  for (let i = 13; i >= 0; i--) {
    const date = dayjs().subtract(i, 'day').format('YYYY-MM-DD')
    out.push({ date, done: set.has(date) })
  }
  return out
})

function toggle(item: string) {
  picked.value = picked.value.includes(item)
    ? picked.value.filter((x) => x !== item)
    : [...picked.value, item]
}

async function load() {
  try {
    const res = await healApi.listHabits(student.studentRef, 30)
    records.value = res.records
    streak.value = res.streak
    totalDays.value = res.total_days
    const today = res.records.find((r) => r.date === todayStr())
    picked.value = today ? [...today.items] : []
  } catch {
    /* 静默降级 */
  }
}

async function save() {
  if (!picked.value.length) {
    toastWarn('至少点亮一件小事吧')
    return
  }
  saving.value = true
  try {
    const res = await healApi.saveHabits(student.studentRef, [...picked.value])
    streak.value = res.streak
    totalDays.value = res.total_days
    toastSuccess(`今天点亮了 ${res.record.items.length} 颗星`)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="微光打卡" sub="完成一件小事，就点亮一颗星" back />

    <PxCard title="今天做到了什么">
      <div class="hb__items">
        <button
          v-for="it in ITEMS"
          :key="it"
          type="button"
          class="hb__item"
          :class="{ 'is-on': picked.includes(it) }"
          @click="toggle(it)"
        >
          <span class="hb__icon">{{ picked.includes(it) ? '✧' : '·' }}</span>
          {{ it }}
        </button>
      </div>
      <div class="hb__save">
        <PxButton block :loading="saving" @click="save">
          {{ doneToday ? '更新今天的打卡' : '点亮今天' }}
        </PxButton>
      </div>
    </PxCard>

    <PxCard class="hb__block" title="坚持记录">
      <ul class="hb__stats">
        <li>
          <strong>{{ streak }}</strong>
          <em>连续天数</em>
        </li>
        <li>
          <strong>{{ totalDays }}</strong>
          <em>累计天数</em>
        </li>
      </ul>
      <div class="hb__grid">
        <span
          v-for="d in last14"
          :key="d.date"
          class="hb__cell"
          :class="{ 'is-done': d.done }"
          :title="d.date"
        />
      </div>
      <p class="xq-muted">最近 14 天</p>
    </PxCard>

    <h2 class="xq-section-title">之前的记录</h2>
    <PxEmpty v-if="!records.length" text="还没有打卡记录，从今天开始吧" />
    <PxCard v-else pad>
      <ul class="hb__history">
        <li v-for="r in [...records].reverse().slice(0, 10)" :key="r.date" class="hb__history-item">
          <span class="hb__date">{{ fmtDate(r.date) }}</span>
          <span class="hb__tags">{{ r.items.join(' · ') }}</span>
        </li>
      </ul>
    </PxCard>

    <p class="xq-disclaimer">
      连续天数断了也没关系，随时可以从今天重新开始。打卡只是提醒，不是任务。
    </p>
  </div>
</template>

<style scoped>
.hb__items {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--xq-sp-2);
}
.hb__item {
  display: flex;
  align-items: center;
  gap: 6px;
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  padding: 10px;
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
  text-align: left;
}
.hb__item.is-on {
  background: var(--xq-primary-soft);
  color: var(--xq-text);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.hb__icon {
  color: var(--xq-star);
  font-size: 16px;
}
.hb__save {
  margin-top: var(--xq-sp-4);
}
.hb__block {
  margin-top: var(--xq-sp-3);
}
.hb__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  text-align: center;
  margin-bottom: var(--xq-sp-3);
}
.hb__stats strong {
  display: block;
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-2xl);
  color: var(--xq-primary-deep);
}
.hb__stats em {
  font-style: normal;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.hb__grid {
  display: grid;
  grid-template-columns: repeat(14, minmax(0, 1fr));
  gap: 4px;
  margin-bottom: 4px;
}
.hb__cell {
  aspect-ratio: 1;
  border: 2px solid var(--xq-text-disabled);
  background: var(--xq-surface-2);
}
.hb__cell.is-done {
  background: var(--xq-star);
  border-color: var(--xq-text);
}
.hb__history {
  display: grid;
  gap: var(--xq-sp-2);
}
.hb__history-item {
  display: flex;
  gap: var(--xq-sp-3);
  font-size: var(--xq-fs-sm);
  border-bottom: 1px dashed var(--xq-text-disabled);
  padding-bottom: var(--xq-sp-2);
}
.hb__history-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.hb__date {
  flex: 0 0 auto;
  color: var(--xq-text-2);
  font-size: var(--xq-fs-xs);
}
.hb__tags {
  min-width: 0;
}
</style>
