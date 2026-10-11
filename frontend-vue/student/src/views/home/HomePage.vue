<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxTag from '@/components/base/PxTag.vue'
import PxInput from '@/components/base/PxInput.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import MoodPicker from '@/components/business/MoodPicker.vue'
import { useStudentStore } from '@/stores/student'
import { healApi, historyApi } from '@/api'
import type { EvaluationRecord, GrowthResponse, HealContent, MoodEntry } from '@/api/types'
import { HEAL_HOME_ENTRIES } from '@/views/heal/functions'
import { fmtRelative, todayStr } from '@/utils/format'
import { toastSuccess, toastWarn } from '@/utils/toast'

const router = useRouter()
const student = useStudentStore()

/** 首页只做「展示 + 快捷跳转」，所有接口失败都静默降级，不打断学生。 */
const latestRecord = ref<EvaluationRecord | null>(null)
const contents = ref<HealContent[]>([])
const growth = ref<GrowthResponse | null>(null)
const todayMood = ref<MoodEntry | null>(null)

const moodDraft = ref<number | null>(null)
const tagDraft = ref<string[]>([])
const noteDraft = ref('')
const saving = ref(false)

const TAGS = ['学习', '朋友', '家人', '睡眠', '身体', '未来']
const MOOD_FACE: Record<number, string> = { 1: '🌧', 2: '☁️', 3: '🌤', 4: '🌈', 5: '☀️' }

const LEVEL_TEXT: Record<string, string> = {
  low_concern: '状态较平稳',
  mild_concern: '轻微关注',
  moderate_concern: '中度关注',
  high_concern: '重点关注',
}

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 11) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const dateLine = computed(() => {
  const d = new Date()
  const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  return `${d.getMonth() + 1}月${d.getDate()}日 ${week} · 愿你今天心情晴朗`
})

function toggleTag(t: string) {
  tagDraft.value = tagDraft.value.includes(t)
    ? tagDraft.value.filter((x) => x !== t)
    : [...tagDraft.value, t]
}

async function loadAll() {
  await Promise.all([loadRecord(), loadContents(), loadGrowth(), loadMood()])
}

async function loadRecord() {
  try {
    const res = await historyApi.byStudent(student.studentRef)
    latestRecord.value = res.records[0] ?? null
  } catch {
    /* 静默降级 */
  }
}

async function loadContents() {
  try {
    const res = await healApi.contents(todayMood.value?.mood)
    contents.value = res.contents.slice(0, 3)
  } catch {
    /* 静默降级 */
  }
}

async function loadGrowth() {
  try {
    growth.value = await healApi.growth(student.studentRef, 30)
  } catch {
    /* 静默降级 */
  }
}

async function loadMood() {
  try {
    const res = await healApi.listMood(student.studentRef, 7)
    todayMood.value = res.entries.find((e) => e.date === todayStr()) ?? null
  } catch {
    /* 静默降级 */
  }
}

async function saveMood() {
  if (!moodDraft.value) {
    toastWarn('先选一个此刻的心情吧')
    return
  }
  saving.value = true
  try {
    const res = await healApi.saveMood({
      student_ref: student.studentRef,
      date: todayStr(),
      mood: moodDraft.value,
      tags: [...tagDraft.value],
      note: noteDraft.value.trim() || null,
    })
    todayMood.value = res.entry
    toastSuccess('已经记下今天的心情啦')
    await loadGrowth()
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}

function editMood() {
  todayMood.value = null
}

onMounted(loadAll)
</script>

<template>
  <div class="xq-page home">
    <!-- 呼吸光晕氛围 -->
    <div class="home__glow" aria-hidden="true" />

    <!-- 问候 -->
    <header class="home__hello">
      <h1 class="home__title">{{ greeting }}，{{ student.displayName }}</h1>
      <p class="home__date">{{ dateLine }}</p>
    </header>

    <!-- 今日心情 -->
    <PxCard class="home__card xq-fade-up">
      <div class="home__card-head">
        <span class="home__card-icon">🌤</span>
        <div>
          <p class="home__card-title">今日心情</p>
          <p class="home__card-sub">花 3 秒钟，标记此刻的感受</p>
        </div>
      </div>
      <template v-if="todayMood">
        <div class="home__mooddone">
          <span class="home__moodface">{{ MOOD_FACE[todayMood.mood] }}</span>
          <div>
            <p>今天记下了：心情 {{ todayMood.mood }} / 5</p>
            <p v-if="todayMood.note" class="xq-muted">{{ todayMood.note }}</p>
            <p v-if="todayMood.tags?.length" class="home__tagrow">
              <PxTag v-for="t in todayMood!.tags" :key="t" tone="secondary" size="sm">{{ t }}</PxTag>
            </p>
          </div>
          <PxButton size="sm" variant="ghost" @click="editMood">重新记录</PxButton>
        </div>
      </template>
      <template v-else>
        <MoodPicker v-model="moodDraft" compact />
        <div class="home__tags">
          <PxTag
            v-for="t in TAGS"
            :key="t"
            :tone="tagDraft.includes(t) ? 'primary' : 'default'"
            size="sm"
            class="home__tag"
            @click="toggleTag(t)"
          >
            {{ t }}
          </PxTag>
        </div>
        <PxInput
          v-model="noteDraft"
          textarea
          :rows="2"
          placeholder="想补充一句吗？（可不填）"
          :maxlength="120"
        />
        <div class="home__save">
          <PxButton block :loading="saving" @click="saveMood">记下此刻</PxButton>
        </div>
      </template>
    </PxCard>

    <!-- 待办测评 -->
    <PxCard tone="primary" clickable class="home__card xq-fade-up" @click="router.push('/assess/consent')">
      <div class="home__todo">
        <div class="home__todo-main">
          <p class="home__todo-kicker">待办测评 · PHQ-9 对话测评</p>
          <p class="home__todo-sub">
            <template v-if="latestRecord">
              上次 {{ fmtRelative(latestRecord.created_at) }} ·
              {{ LEVEL_TEXT[latestRecord.result.overall_level] ?? '已完成' }}
            </template>
            <template v-else>约 8 分钟 · 支持暂停续测</template>
          </p>
        </div>
        <span class="home__todo-btn">开始</span>
      </div>
    </PxCard>

    <!-- 小晴 · 治愈陪伴 -->
    <PxCard clickable class="home__card home__xiaoqing xq-fade-up" @click="router.push('/heal/chat')">
      <div class="home__xq-row">
        <span class="home__xq-avatar">小晴</span>
        <div>
          <p class="home__card-title">小晴 · 治愈陪伴</p>
          <p class="home__card-sub">想聊聊吗？我一直都在</p>
        </div>
        <span class="home__xq-arrow">›</span>
      </div>
    </PxCard>

    <!-- 专注学习 -->
    <PxCard clickable class="home__card xq-fade-up" @click="router.push('/heal/focus')">
      <div class="home__card-head">
        <span class="home__card-icon">🍅</span>
        <div>
          <p class="home__card-title">专注学习 · 番茄钟</p>
          <p class="home__card-sub">25 分钟专注 + 5 分钟休息</p>
        </div>
      </div>
    </PxCard>

    <!-- 紧急求助 -->
    <div class="home__help xq-fade-up">
      <strong>紧急求助</strong>
      <p class="xq-muted">如果现在很难受，可以拨打 12356 心理援助热线，或联系校内心理老师。</p>
      <a class="home__tel" href="tel:12356">拨打 12356</a>
    </div>

    <!-- 心理自助入口 -->
    <h2 class="xq-section-title">心理自助</h2>
    <div class="home__entries">
      <router-link v-for="f in HEAL_HOME_ENTRIES" :key="f.key" :to="f.path" class="home__entry">
        <span class="home__entry-icon" :class="{ 'is-core': f.core }">{{ f.icon }}</span>
        <span class="home__entry-title">{{ f.title }}</span>
      </router-link>
    </div>
    <div class="home__more">
      <router-link to="/heal">全部 13 项功能 ›</router-link>
    </div>

    <!-- 坚持足迹 -->
    <PxCard v-if="growth" class="home__card" title="坚持足迹">
      <ul class="home__stats">
        <li>
          <strong>{{ growth?.focus_minutes ?? 0 }}</strong>
          <em>近 30 天专注分钟</em>
        </li>
        <li>
          <strong>{{ growth?.streak ?? 0 }}</strong>
          <em>连续打卡天数</em>
        </li>
        <li>
          <strong>{{ growth?.mood_days ?? 0 }}</strong>
          <em>记心情的天数</em>
        </li>
      </ul>
    </PxCard>

    <!-- 心理小知识 -->
    <template v-if="contents.length">
      <h2 class="xq-section-title">心理小知识</h2>
      <div class="xq-grid">
        <PxCard v-for="c in contents" :key="c.id" :title="c.title">
          <p class="home__content">{{ c.summary || c.body || '点开看看这一条小知识。' }}</p>
        </PxCard>
      </div>
    </template>
    <PxEmpty v-else text="内容正在路上，先和小晴聊聊吧" />

    <p class="xq-disclaimer">
      心晴提供的是初步筛查与自助支持，不构成任何诊断或治疗建议。结果不能替代专业医生的判断，
      如果持续感到困扰，请寻求专业帮助。
    </p>
  </div>
</template>

<style scoped>
.home {
  position: relative;
}
/* 呼吸光晕：氛围装饰，不遮挡交互 */
.home__glow {
  position: absolute;
  top: -30px;
  right: -20px;
  width: 180px;
  height: 180px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 184, 77, 0.35), rgba(255, 138, 92, 0) 70%);
  filter: blur(6px);
  pointer-events: none;
  animation: xq-breathe 4.8s ease-in-out infinite;
}

.home__hello {
  margin: var(--xq-sp-3) 0 var(--xq-sp-5);
}
.home__title {
  font-size: var(--xq-fs-2xl);
  font-weight: 700;
}
.home__date {
  margin-top: 4px;
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
}

.home__card {
  margin-top: var(--xq-sp-3);
}
.home__card-head {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-3);
}
.home__card-icon {
  font-size: 26px;
  line-height: 1;
}
.home__card-title {
  font-weight: 600;
  font-size: var(--xq-fs-base);
}
.home__card-sub {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  margin-top: 2px;
}
.home__mooddone {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-3);
}
.home__moodface {
  font-size: 34px;
  line-height: 1;
}
.home__tagrow {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}
.home__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: var(--xq-sp-3) 0;
}
.home__tag {
  cursor: pointer;
}
.home__save {
  margin-top: var(--xq-sp-3);
}

/* 待办测评大卡 */
.home__todo {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-3);
}
.home__todo-main {
  flex: 1;
  min-width: 0;
}
.home__todo-kicker {
  font-weight: 700;
  font-size: var(--xq-fs-lg);
}
.home__todo-sub {
  margin-top: 4px;
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
}
.home__todo-btn {
  flex: 0 0 auto;
  padding: 10px 22px;
  border-radius: 999px;
  background: linear-gradient(135deg, #ffa176 0%, var(--xq-primary) 60%, var(--xq-primary-deep) 100%);
  color: #fff;
  font-weight: 600;
  box-shadow: 0 6px 16px rgba(255, 138, 92, 0.35);
}

/* 小晴 */
.home__xiaoqing {
  background: linear-gradient(135deg, #fff 0%, var(--xq-primary-soft) 55%, #ffe3cd 100%);
}
.home__xq-row {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-3);
}
.home__xq-avatar {
  flex: 0 0 46px;
  width: 46px;
  height: 46px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ffb84d 0%, var(--xq-primary) 100%);
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 6px 14px rgba(255, 138, 92, 0.35);
}
.home__xq-arrow {
  margin-left: auto;
  font-size: 20px;
  color: var(--xq-primary-deep);
}

/* 紧急求助 */
.home__help {
  margin-top: var(--xq-sp-4);
  padding: var(--xq-sp-4);
  border-radius: var(--xq-radius-l);
  background: rgba(255, 107, 74, 0.08);
}
.home__tel {
  display: inline-block;
  margin-top: var(--xq-sp-3);
  background: var(--xq-hotline);
  color: #fff;
  border-radius: 999px;
  padding: 8px 18px;
  font-size: var(--xq-fs-sm);
  font-weight: 600;
  box-shadow: 0 6px 14px rgba(255, 107, 74, 0.3);
}

/* 入口网格：手机 4 列，桌面 8 列 */
.home__entries {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--xq-sp-2);
}
.home__entry {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: var(--xq-sp-3) 4px;
  border-radius: var(--xq-radius-m);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
  color: var(--xq-text);
  transition: transform var(--xq-dur-fast) var(--xq-ease-base);
}
.home__entry:active {
  transform: scale(0.95);
}
.home__entry-icon {
  font-size: 22px;
  color: var(--xq-primary-deep);
}
.home__entry-icon.is-core {
  color: var(--xq-star);
}
.home__entry-title {
  font-size: 11px;
  text-align: center;
  line-height: 1.3;
}
.home__more {
  text-align: right;
  margin-top: var(--xq-sp-2);
  font-size: var(--xq-fs-sm);
}
.home__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--xq-sp-2);
  text-align: center;
}
.home__stats strong {
  display: block;
  font-weight: 700;
  font-size: var(--xq-fs-xl);
  color: var(--xq-primary-deep);
}
.home__stats em {
  font-style: normal;
  font-size: 10px;
  color: var(--xq-text-2);
}
.home__content {
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
  line-height: 1.7;
}
@media (min-width: 1024px) {
  .home__entries {
    grid-template-columns: repeat(8, minmax(0, 1fr));
  }
}
</style>
