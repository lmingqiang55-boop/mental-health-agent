<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxTag from '@/components/base/PxTag.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import { communicationApi, historyApi } from '@/api'
import type { CommunicationMessage, EvaluationRecord } from '@/api/types'
import { useStudentStore } from '@/stores/student'
import { fmtDateTime } from '@/utils/format'

const router = useRouter()
const student = useStudentStore()

const LEVEL_TEXT: Record<string, string> = {
  low_concern: '状态较平稳',
  mild_concern: '轻微关注',
  moderate_concern: '中度关注',
  high_concern: '重点关注',
}

const records = ref<EvaluationRecord[]>([])
const replies = ref<CommunicationMessage[]>([])
const loading = ref(true)

const hasAny = computed(() => records.value.length > 0 || replies.value.length > 0)

async function load() {
  try {
    const [h, c] = await Promise.all([
      historyApi.byStudent(student.studentRef).catch(() => null),
      communicationApi.list(student.studentRef).catch(() => null),
    ])
    if (h) records.value = h.records
    if (c) replies.value = c.messages.filter((m) => m.direction === 'counselor_to_student')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="消息中心" sub="报告与老师回复都会出现在这里" back />

    <PxEmpty v-if="!loading && !hasAny" text="暂时还没有消息" />

    <template v-else>
      <h2 v-if="replies.length" class="xq-section-title">老师的回复</h2>
      <div v-if="replies.length" class="ms__list">
        <PxCard v-for="(m, i) in replies" :key="m.id ?? i" clickable @click="router.push('/me/collaboration')">
          <div class="ms__item">
            <span class="ms__icon">✉</span>
            <div class="ms__body">
              <p class="ms__content">{{ m.content }}</p>
              <span class="ms__time">{{ fmtDateTime(m.created_at) }}</span>
            </div>
          </div>
        </PxCard>
      </div>

      <h2 v-if="records.length" class="xq-section-title">测评报告</h2>
      <div v-if="records.length" class="ms__list">
        <PxCard
          v-for="r in records"
          :key="r.record_id"
          clickable
          @click="router.push(`/assess/report/${r.result.result_id}`)"
        >
          <div class="ms__item">
            <span class="ms__icon">✦</span>
            <div class="ms__body">
              <div class="ms__head">
                <span class="ms__title">测评报告已生成</span>
                <PxTag :tone="r.result.overall_level === 'high_concern' ? 'danger' : 'primary'" size="sm">
                  {{ LEVEL_TEXT[r.result.overall_level] ?? r.result.overall_level }}
                </PxTag>
              </div>
              <span class="ms__time">{{ fmtDateTime(r.created_at) }}</span>
            </div>
          </div>
        </PxCard>
      </div>
    </template>

    <p class="xq-disclaimer">
      消息仅作提醒，不会包含你的隐私细节。点击报告可查看完整解读。
    </p>
  </div>
</template>

<style scoped>
.ms__list {
  display: grid;
  gap: var(--xq-sp-3);
}
.ms__item {
  display: flex;
  gap: var(--xq-sp-3);
}
.ms__icon {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  color: var(--xq-primary-deep);
  border: var(--xq-border-pixel-thin);
  background: var(--xq-primary-soft);
}
.ms__body {
  min-width: 0;
  flex: 1;
}
.ms__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--xq-sp-2);
}
.ms__title {
  font-size: var(--xq-fs-sm);
}
.ms__content {
  font-size: var(--xq-fs-sm);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.ms__time {
  display: block;
  margin-top: 4px;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
</style>
