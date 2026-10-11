<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxInput from '@/components/base/PxInput.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import MoodPicker from '@/components/business/MoodPicker.vue'
import { healApi } from '@/api'
import type { MoodEntry } from '@/api/types'
import { useStudentStore } from '@/stores/student'
import { fmtDate, todayStr } from '@/utils/format'
import { readLS, removeLS, writeLS, STORAGE_KEYS } from '@/utils/storage'
import { toastSuccess, toastWarn } from '@/utils/toast'

const student = useStudentStore()

/** 1~5 的展示信息（与 MoodPicker 一致，用于历史回看）。 */
const MOOD_META: Record<number, { emoji: string; label: string }> = {
  1: { emoji: '🌧', label: '很难过' },
  2: { emoji: '☁️', label: '有点低落' },
  3: { emoji: '🌤', label: '一般' },
  4: { emoji: '🌈', label: '还不错' },
  5: { emoji: '☀️', label: '很开心' },
}

const WEATHERS = ['晴', '多云', '阴', '雨', '雪']
const TAGS = ['学习', '人际', '家庭', '睡眠', '运动', '独处', '未来', '身体']

interface MoodDraft {
  mood: number | null
  weather: string
  tags: string[]
  note: string
}

const draft = readLS<MoodDraft>(STORAGE_KEYS.moodDraft, {
  mood: null,
  weather: '',
  tags: [],
  note: '',
})

const mood = ref<number | null>(draft.mood ?? null)
const weather = ref(draft.weather ?? '')
const tags = ref<string[]>(draft.tags ?? [])
const note = ref(draft.note ?? '')

const entries = ref<MoodEntry[]>([])
const loading = ref(true)
const saving = ref(false)

const today = todayStr()
const todayEntry = computed(() => entries.value.find((e) => e.date === today))
const recent = computed(() => [...entries.value].reverse().slice(0, 30))

function persistDraft() {
  writeLS(STORAGE_KEYS.moodDraft, {
    mood: mood.value,
    weather: weather.value,
    tags: tags.value,
    note: note.value,
  })
}

function toggleTag(t: string) {
  tags.value = tags.value.includes(t) ? tags.value.filter((x) => x !== t) : [...tags.value, t]
}

function pickWeather(w: string) {
  weather.value = weather.value === w ? '' : w
}

watch([mood, weather, tags, note], persistDraft, { deep: true })

async function load() {
  loading.value = true
  try {
    const res = await healApi.listMood(student.studentRef, 30)
    entries.value = res.entries
    const doc = res.entries.find((e) => e.date === today)
    if (doc) {
      mood.value = doc.mood
      weather.value = doc.weather ?? ''
      tags.value = doc.tags ? [...doc.tags] : []
      note.value = doc.note ?? ''
      persistDraft()
    }
  } catch {
    /* 静默降级 */
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!mood.value) {
    toastWarn('先选一个此刻的心情吧')
    return
  }
  saving.value = true
  try {
    await healApi.saveMood({
      student_ref: student.studentRef,
      date: today,
      mood: mood.value,
      weather: weather.value || null,
      tags: tags.value,
      note: note.value.trim() || null,
    })
    toastSuccess(todayEntry.value ? '今天的心情已经更新' : '记下今天的心情了')
    removeLS(STORAGE_KEYS.moodDraft)
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
    <PxPageHead title="心情日记" sub="每天一次情绪打卡，看看这段时间的变化" back />

    <PxCard title="此刻的心情">
      <MoodPicker v-model="mood" />
      <p class="xq-muted mj__hint">
        {{ mood ? MOOD_META[mood].label : '从左边选一个最接近的就好' }}
      </p>
    </PxCard>

    <PxCard class="mj__block" title="今天的天气（选填）">
      <div class="mj__chips">
        <button
          v-for="w in WEATHERS"
          :key="w"
          type="button"
          class="mj__chip"
          :class="{ 'is-on': weather === w }"
          @click="pickWeather(w)"
        >
          {{ w }}
        </button>
      </div>
    </PxCard>

    <PxCard class="mj__block" title="和什么有关（选填）">
      <div class="mj__chips">
        <button
          v-for="t in TAGS"
          :key="t"
          type="button"
          class="mj__chip"
          :class="{ 'is-on': tags.includes(t) }"
          @click="toggleTag(t)"
        >
          {{ t }}
        </button>
      </div>
    </PxCard>

    <PxCard class="mj__block" title="想说点什么（选填）">
      <PxInput
        v-model="note"
        textarea
        :rows="4"
        :maxlength="500"
        placeholder="发生了什么？当时是什么感觉？写几句就好。"
        hint="不会给别人看，只属于你自己。"
      />
    </PxCard>

    <div class="mj__save">
      <PxButton block :loading="saving" @click="save">
        {{ todayEntry ? '更新今天的心情' : '记下今天的心情' }}
      </PxButton>
    </div>

    <h2 class="xq-section-title">最近的心情</h2>
    <PxEmpty v-if="!loading && !recent.length" text="还没有心情记录，从今天开始吧" />
    <ul v-else class="mj__list">
      <li v-for="e in recent" :key="e.date" class="mj__item">
        <div class="mj__item-head">
          <span class="mj__emoji">{{ MOOD_META[e.mood]?.emoji ?? '·' }}</span>
          <span class="mj__date">{{ fmtDate(e.date) }}</span>
          <span class="mj__label">{{ MOOD_META[e.mood]?.label ?? '' }}</span>
          <span v-if="e.weather" class="mj__weather">{{ e.weather }}</span>
        </div>
        <div v-if="e.tags?.length" class="mj__item-tags">
          <span v-for="t in e.tags" :key="t" class="mj__mini-tag">{{ t }}</span>
        </div>
        <p v-if="e.note" class="mj__note">{{ e.note }}</p>
      </li>
    </ul>

    <p class="xq-disclaimer">
      心情没有好坏，记录下来本身就是一种照顾。中断几天也没关系，想起来再继续。
    </p>
  </div>
</template>

<style scoped>
.mj__hint {
  margin-top: var(--xq-sp-3);
  text-align: center;
}
.mj__block {
  margin-top: var(--xq-sp-3);
}
.mj__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--xq-sp-2);
}
.mj__chip {
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  color: var(--xq-text-2);
  padding: 6px 14px;
  font-size: var(--xq-fs-sm);
}
.mj__chip.is-on {
  background: var(--xq-primary-soft);
  color: var(--xq-text);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.mj__save {
  margin-top: var(--xq-sp-4);
}
.mj__list {
  display: grid;
  gap: var(--xq-sp-3);
}
.mj__item {
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
  padding: var(--xq-sp-3);
}
.mj__item-head {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-2);
}
.mj__emoji {
  font-size: 22px;
  line-height: 1;
}
.mj__date {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-sm);
}
.mj__label {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.mj__weather {
  margin-left: auto;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.mj__item-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--xq-sp-2);
}
.mj__mini-tag {
  font-size: 11px;
  padding: 1px 8px;
  border: 2px solid var(--xq-text-disabled);
  color: var(--xq-text-2);
}
.mj__note {
  margin-top: var(--xq-sp-2);
  font-size: var(--xq-fs-sm);
  white-space: pre-wrap;
  line-height: 1.7;
}
</style>
