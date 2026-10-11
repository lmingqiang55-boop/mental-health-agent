<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import FocusTimer from '@/components/business/FocusTimer.vue'
import MoodPicker from '@/components/business/MoodPicker.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import { healApi } from '@/api'
import type { FocusSession } from '@/api/types'
import { useStudentStore } from '@/stores/student'
import { fmtDateTime } from '@/utils/format'
import { toastSuccess } from '@/utils/toast'

const student = useStudentStore()

/** 可选专注时长：15 / 25 / 45 分钟。 */
const DURATIONS = [15, 25, 45]
const minutes = ref(25)
const moodBefore = ref<number | null>(null)
const moodAfter = ref<number | null>(null)

const sessions = ref<FocusSession[]>([])
const totalMinutes = ref(0)

const recent7 = computed(() => sessions.value.slice(0, 7))

async function load() {
  try {
    const res = await healApi.listFocus(student.studentRef, 7)
    sessions.value = [...res.sessions].reverse()
    totalMinutes.value = res.total_minutes
  } catch {
    /* 静默降级 */
  }
}

async function onComplete(m: number) {
  try {
    await healApi.saveFocus(
      student.studentRef,
      m,
      moodBefore.value ?? undefined,
      moodAfter.value ?? undefined,
    )
    toastSuccess(`完成了 ${m} 分钟专注`)
    await load()
  } catch {
    /* 拦截器已提示 */
  }
}

onMounted(load)
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="专注学习" sub="把注意力放回手头这一件事" back />

    <PxCard title="选择时长">
      <div class="fc__durations">
        <button
          v-for="d in DURATIONS"
          :key="d"
          type="button"
          class="fc__duration"
          :class="{ 'is-on': minutes === d }"
          @click="minutes = d"
        >
          {{ d }} 分钟
        </button>
      </div>
    </PxCard>

    <PxCard class="fc__block" title="开始专注">
      <FocusTimer :key="minutes" :focus-minutes="minutes" :break-minutes="5" @complete="onComplete" />
    </PxCard>

    <PxCard class="fc__block" title="专注前 / 后，记录一下心情">
      <div class="fc__moods">
        <div class="fc__mood">
          <p class="fc__mood-label">开始前</p>
          <MoodPicker v-model="moodBefore" compact />
        </div>
        <div class="fc__mood">
          <p class="fc__mood-label">完成后</p>
          <MoodPicker v-model="moodAfter" compact />
        </div>
      </div>
      <p class="xq-muted">选填。写下前后心情，能帮你看到专注带来的细小变化。</p>
    </PxCard>

    <PxCard class="fc__block" title="近 7 天专注">
      <ul class="fc__stats">
        <li>
          <strong>{{ totalMinutes }}</strong>
          <em>累计分钟</em>
        </li>
        <li>
          <strong>{{ sessions.length }}</strong>
          <em>完成次数</em>
        </li>
      </ul>
      <PxEmpty v-if="!recent7.length" text="还没有专注记录，从一次 15 分钟开始" />
      <ul v-else class="fc__list">
        <li v-for="(s, i) in recent7" :key="i" class="fc__item">
          <span class="fc__item-time">{{ s.created_at ? fmtDateTime(s.created_at) : '刚刚' }}</span>
          <span class="fc__item-min">{{ s.minutes }} 分钟</span>
        </li>
      </ul>
    </PxCard>

    <p class="xq-disclaimer">
      专注练习不追求时长，累了就停下来休息。番茄钟只是一个提醒工具，不是必须完成的任务。
    </p>
  </div>
</template>

<style scoped>
.fc__durations {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--xq-sp-2);
}
.fc__duration {
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  padding: 12px 6px;
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
}
.fc__duration.is-on {
  background: var(--xq-primary-soft);
  color: var(--xq-text);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.fc__block {
  margin-top: var(--xq-sp-3);
}
.fc__moods {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--xq-sp-3);
  margin-bottom: var(--xq-sp-3);
}
.fc__mood-label {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  margin-bottom: var(--xq-sp-2);
}
.fc__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  text-align: center;
  margin-bottom: var(--xq-sp-3);
}
.fc__stats strong {
  display: block;
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-2xl);
  color: var(--xq-primary-deep);
}
.fc__stats em {
  font-style: normal;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.fc__list {
  display: grid;
  gap: var(--xq-sp-2);
}
.fc__item {
  display: flex;
  justify-content: space-between;
  font-size: var(--xq-fs-sm);
  border-bottom: 1px dashed var(--xq-text-disabled);
  padding-bottom: var(--xq-sp-2);
}
.fc__item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.fc__item-time {
  color: var(--xq-text-2);
  font-size: var(--xq-fs-xs);
}
.fc__item-min {
  color: var(--xq-primary-deep);
}
</style>
