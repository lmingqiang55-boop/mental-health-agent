<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">报告详情</h2>
        <p class="page-subtitle">{{ record?.student_ref ?? '' }} · {{ fmtTime(record?.created_at) }}</p>
      </div>
      <el-button text @click="$router.back()">← 返回</el-button>
    </div>

    <div v-loading="loading">
      <template v-if="record">
        <div class="xq-card">
          <div class="report-head">
            <RiskTag :level="record.result.risk.risk_level" />
            <FollowUpTag :status="record.follow_up_status" />
            <span class="cell-sub">评估结果 ID：{{ record.result.result_id }}</span>
          </div>
        </div>
        <ReportViewer :result="record.result" />
      </template>
      <el-empty v-else description="报告不存在" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { teacherApi } from '@/api'
import ReportViewer from '@/components/business/ReportViewer.vue'
import RiskTag from '@/components/business/RiskTag.vue'
import FollowUpTag from '@/components/business/FollowUpTag.vue'
import { fmtTime } from '@/utils/format'
import type { EvaluationRecord } from '@/types'

const route = useRoute()
const recordId = route.params.recordId as string

const loading = ref(false)
const record = ref<EvaluationRecord | null>(null)

async function load() {
  loading.value = true
  try {
    record.value = await teacherApi.getRecord(recordId)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.report-head { display: flex; align-items: center; gap: 10px; }
</style>
