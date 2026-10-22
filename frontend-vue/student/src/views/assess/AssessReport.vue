<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { assessmentApi, historyApi } from '@/api'
import { isApiError } from '@/api/http'
import type { DimensionKey, EvaluationResult } from '@/api/types'
import { useAssessStore } from '@/stores/assess'
import { useStudentStore } from '@/stores/student'
import { toastSuccess } from '@/utils/toast'
import PxCard from '@/components/base/PxCard.vue'
import ReportViewer from '@/components/business/ReportViewer.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import PxPageHead from '@/components/base/PxPageHead.vue'

/**
 * ReportViewer 期望在结果顶层直接读到 primary_concern，
 * 而契约里它位于 report 区块内。这里做兼容填充，不改动已有组件。
 */
type ViewerResult = EvaluationResult & {
  primary_concern: { dimension: DimensionKey; description: string }
}

const route = useRoute()
const router = useRouter()
const assess = useAssessStore()
const student = useStudentStore()

const resultId = computed(() => String(route.params.resultId ?? ''))
const sessionId = computed(() => {
  const q = route.query.session
  return typeof q === 'string' && q ? q : assess.sessionId
})

const loading = ref(true)
const result = ref<EvaluationResult | null>(null)
const recordId = ref('')
const deleting = ref(false)
const loadError = ref('')
let loadVersion = 0

const viewer = computed<ViewerResult | null>(() => {
  const r = result.value
  if (!r) return null
  const primary = r.report?.primary_concern ?? { dimension: 'emotion' as DimensionKey, description: '整体状态' }
  return { ...r, primary_concern: primary }
})

async function load() {
  const version = ++loadVersion
  const id = resultId.value
  loading.value = true
  result.value = null
  recordId.value = ''
  loadError.value = ''
  try {
    // Resolve the exact report's owner session, including old links that used
    // a companionship session instead. Never substitute a different report.
    const history = await historyApi.byStudent(student.studentRef, { silent: true }).catch(() => null)
    const record = history?.records.find((r) => r.result.result_id === id)
    const ownerSession = record?.result.session_id ?? sessionId.value
    if (!ownerSession) throw new Error('缺少报告对应的会话信息，请从测评中心重新打开这份报告。')
    const loaded = await assessmentApi.result(id, ownerSession, { silent: true })
    if (version !== loadVersion) return
    result.value = loaded
    recordId.value = record?.record_id ?? ''
  } catch (e) {
    if (version !== loadVersion) return
    loadError.value = isApiError(e, 'RESULT_NOT_FOUND')
      ? '未找到这份报告，记录可能已删除，请从测评中心重新打开。'
      : isApiError(e) ? e.message : e instanceof Error ? e.message : '报告暂时无法加载，请稍后重试。'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

function restart() {
  void router.push({ name: 'assess-consent' })
}

function goCenter() {
  void router.push({ name: 'assess' })
}

async function deleteCurrentResult() {
  if (!recordId.value || deleting.value) return
  if (!window.confirm('确定永久删除本次评估结果吗？删除后无法恢复。')) return
  deleting.value = true
  try {
    await historyApi.remove(student.studentRef, recordId.value)
    toastSuccess('本次评估结果已删除')
    await router.replace({ name: 'assess' })
  } finally {
    deleting.value = false
  }
}

watch([resultId, sessionId], () => void load(), { immediate: true })
</script>

<template>
  <div class="xq-page report-page">
    <PxPageHead title="测评报告" sub="初步筛查结果" back>
      <PxButton size="sm" variant="ghost" @click="restart">重新测评</PxButton>
    </PxPageHead>

    <PxEmpty v-if="loading" icon="…" text="正在打开报告…" />
    <PxEmpty v-else-if="!viewer" :text="loadError || '报告暂时无法加载'">
      <PxButton variant="ghost" @click="load">重试</PxButton>
      <PxButton @click="goCenter">返回测评中心</PxButton>
    </PxEmpty>

    <ReportViewer v-else-if="viewer" :result="viewer" class="xq-fade-up" />

    <PxCard v-if="viewer" title="本次评估使用的数据" class="report-page__privacy">
      <ul class="report-page__sources">
        <li>✓ 对话文字</li>
        <li>{{ viewer.data_sources.includes('audio_transcription') ? '✓ 已使用语音转写' : '✗ 未采集语音' }}</li>
        <li>{{ viewer.data_sources.includes('vision_analysis') ? '✓ 已使用摄像头分析结果' : '✗ 未采集摄像头信息' }}</li>
      </ul>
      <p class="xq-muted">本结果保存在运行本系统设备的本地数据库中，并通过随机匿名标识关联；你可以在这里删除本次结果。</p>
      <p class="xq-disclaimer">本结果仅用于辅助筛查，不构成医学诊断；高风险结果需要人工复核。</p>
      <PxButton v-if="recordId" variant="danger" :loading="deleting" @click="deleteCurrentResult">删除本次结果</PxButton>
    </PxCard>

    <div v-if="viewer" class="report-page__cta">
      <PxButton size="lg" block @click="goCenter">返回测评中心</PxButton>
    </div>
  </div>
</template>

<style scoped>
.report-page {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
}
.report-page__cta {
  margin-top: var(--xq-sp-4);
}
.report-page__privacy { margin-top: var(--xq-sp-3); }
.report-page__sources { display: grid; gap: 8px; margin-bottom: var(--xq-sp-3); }
</style>
