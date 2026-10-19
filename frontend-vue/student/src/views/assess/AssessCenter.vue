<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { historyApi, sessionApi } from '@/api'
import { isApiError } from '@/api/http'
import type { EvaluationRecord, OverallLevel } from '@/api/types'
import { useStudentStore } from '@/stores/student'
import { useAssessStore, type AssessProgress } from '@/stores/assess'
import { fmtDate, fmtFullDateTime, todayStr } from '@/utils/format'
import { toastWarn } from '@/utils/toast'
import PxButton from '@/components/base/PxButton.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import PxTag from '@/components/base/PxTag.vue'

/** session_id 为后端内存态，TTL 2 小时；超过即视为过期。 */
const TTL = 2 * 60 * 60 * 1000

const LEVEL_LABEL: Record<OverallLevel, string> = {
  low_concern: '状态较平稳',
  mild_concern: '轻度关注',
  moderate_concern: '中度关注',
  high_concern: '高度关注',
}
const LEVEL_TONE: Record<OverallLevel, 'success' | 'secondary' | 'warning' | 'danger'> = {
  low_concern: 'success',
  mild_concern: 'secondary',
  moderate_concern: 'warning',
  high_concern: 'danger',
}

const router = useRouter()
const student = useStudentStore()
const assess = useAssessStore()

const loading = ref(true)
const resuming = ref(false)
const records = ref<EvaluationRecord[]>([])
const resume = ref<AssessProgress | null>(null)

const todayTested = computed(() => records.value.some((r) => fmtDate(r.created_at) === todayStr()))

async function loadHistory() {
  loading.value = true
  try {
    const res = await historyApi.byStudent(student.studentRef)
    records.value = res.records
  } catch {
    records.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadHistory()
  const p = assess.readProgress()
  if (p && Date.now() - p.updatedAt <= TTL) resume.value = p
  else if (p) assess.clearProgress()
})

function startNew() {
  void router.push({ name: 'assess-consent' })
}

async function continueAssess() {
  const p = resume.value
  if (!p) return
  resuming.value = true
  try {
    const state = await sessionApi.get(p.sessionId)
    assess.setSession(state.session_id, state.turn_count)
    await router.push({ name: 'assess-session', params: { id: state.session_id } })
  } catch (e) {
    if (isApiError(e, 'SESSION_NOT_FOUND')) {
      assess.clearProgress()
      resume.value = null
      toastWarn('上次的测评会话已过期，请重新开始')
    }
  } finally {
    resuming.value = false
  }
}

function openReport(r: EvaluationRecord) {
  void router.push({
    name: 'assess-report',
    params: { resultId: r.result.result_id },
    query: { session: r.result.session_id },
  })
}
</script>

<template>
  <div class="xq-page assess">
    <h1 class="xq-page-title">测评中心</h1>

    <PxCard tone="primary" class="assess__hero">
      <div class="assess__hello">你好，{{ student.displayName }}</div>
      <p class="xq-muted">和小晴聊一会儿，帮你了解最近的状态，大约 5–10 分钟。</p>
      <div class="assess__actions">
        <PxButton size="lg" block @click="startNew">开始新测评</PxButton>
        <PxButton
          v-if="resume"
          variant="ghost"
          block
          :loading="resuming"
          @click="continueAssess"
        >
          继续上次测评
        </PxButton>
      </div>
      <p v-if="todayTested" class="assess__today">
        <PxTag tone="success" size="sm">今日已完成</PxTag>
        <span class="xq-muted">今天已经测过一次啦，也可以再测一次。</span>
      </p>
    </PxCard>

    <h2 class="xq-section-title">历史报告</h2>

    <PxEmpty v-if="loading" icon="…" text="正在加载历史报告…" />
    <PxEmpty v-else-if="!records.length" text="还没有测评记录，试试开始一次吧">
      <PxButton @click="startNew">开始新测评</PxButton>
    </PxEmpty>
    <div v-else class="assess__list">
      <PxCard
        v-for="r in records"
        :key="r.record_id"
        clickable
        class="assess__item"
        @click="openReport(r)"
      >
        <div class="assess__item-row">
          <div class="assess__item-main">
            <span class="assess__item-date">{{ fmtFullDateTime(r.created_at) }}</span>
            <PxTag :tone="LEVEL_TONE[r.result.overall_level]" size="sm">
              {{ LEVEL_LABEL[r.result.overall_level] }}
            </PxTag>
          </div>
          <span class="assess__item-index">{{ Math.round(r.result.concern_index) }}</span>
        </div>
        <p class="xq-muted">关注指数 · 点击查看报告</p>
      </PxCard>
    </div>

    <p class="xq-disclaimer">测评结果为初步筛查与关注提示，不构成医学诊断。</p>
  </div>
</template>

<style scoped>
.assess__hero {
  margin-bottom: var(--xq-sp-2);
}
.assess__hello {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-lg);
}
.assess__actions {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
  margin-top: var(--xq-sp-4);
}
.assess__today {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-2);
  margin-top: var(--xq-sp-3);
  flex-wrap: wrap;
}
.assess__list {
  display: grid;
  gap: var(--xq-sp-3);
  grid-template-columns: 1fr;
}
.assess__item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--xq-sp-3);
}
.assess__item-main {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-2);
}
.assess__item-date {
  font-family: var(--xq-font-pixel);
}
.assess__item-index {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-2xl);
}
@media (min-width: 1024px) {
  .assess__list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
