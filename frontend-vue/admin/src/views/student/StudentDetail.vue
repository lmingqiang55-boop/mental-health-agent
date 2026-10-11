<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">个体档案 · {{ studentRef }}</h2>
        <p class="page-subtitle">数据源：/api/teacher/student/{ref} + /api/history/{ref} + /api/communication/{ref}</p>
      </div>
      <el-button text @click="$router.push('/students')">← 返回列表</el-button>
    </div>

    <div v-loading="loading">
      <!-- 头部信息卡 -->
      <div class="xq-card">
        <div class="info-row">
          <el-descriptions :column="4" size="small">
            <el-descriptions-item label="学生标识">{{ studentRef }}</el-descriptions-item>
            <el-descriptions-item label="年级">{{ latest?.result.grade ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="年龄">{{ latest?.result.age ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="评估次数">{{ records.length }} 次</el-descriptions-item>
          </el-descriptions>
        </div>
      </div>

      <el-row :gutter="16" style="margin-top: 16px">
        <!-- 趋势 -->
        <el-col :span="16">
          <div class="xq-card">
            <h3 class="card-title">五维趋势（最近 3 次）</h3>
            <div ref="trendEl" class="chart" />
          </div>
        </el-col>
        <!-- 最新画像 -->
        <el-col :span="8">
          <div class="xq-card">
            <h3 class="card-title">最新画像</h3>
            <DimensionRadar :profile="latest?.result.psychological_profile" :height="260" />
          </div>
        </el-col>
      </el-row>

      <!-- 测评时间线 -->
      <div class="xq-card" style="margin-top: 16px">
        <h3 class="card-title">测评时间线</h3>
        <el-timeline>
          <el-timeline-item
            v-for="r in reversedRecords"
            :key="r.record_id"
            :timestamp="`${fmtTime(r.created_at)} · 关注指数 ${r.result.concern_index}`"
            placement="top"
          >
            <div class="timeline-body">
              <div class="tl-row">
                <RiskTag :level="r.result.risk.risk_level" />
                <FollowUpTag :status="r.follow_up_status" />
                <el-button size="small" text type="primary" @click="$router.push(`/assessment/results/${r.record_id}`)">
                  查看报告
                </el-button>
              </div>
              <div class="tl-dims">
                <span v-for="(val, dim) in r.result.psychological_profile" :key="dim" class="dim-tag">
                  {{ DIMENSION_MAP[dim as keyof typeof DIMENSION_MAP] }} {{ val }}
                </span>
              </div>
            </div>
          </el-timeline-item>
        </el-timeline>
      </div>

      <!-- 沟通记录（老师可主动发消息） -->
      <div class="xq-card" style="margin-top: 16px">
        <h3 class="card-title">沟通记录</h3>
        <div class="chat-box">
          <div v-for="m in messages" :key="m.message_id" class="chat-msg" :class="m.direction">
            <div class="chat-bubble">{{ m.content }}</div>
            <div class="chat-meta">{{ fmtTime(m.created_at, 'MM-DD HH:mm') }} · {{ m.counselor_ref ?? '学生' }}</div>
          </div>
          <p v-if="!messages.length" class="cell-sub">暂无沟通记录</p>
        </div>
        <div class="chat-input-bar">
          <el-input v-model="reply" placeholder="向学生发送关怀/通知消息" maxlength="2000" show-word-limit>
            <template #append>
              <el-button type="primary" :disabled="!reply.trim()" @click="sendReply">发送</el-button>
            </template>
          </el-input>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef } from 'vue'
import { useRoute } from 'vue-router'
import type { EChartsOption } from 'echarts'
import { communicationApi, historyApi } from '@/api'
import DimensionRadar from '@/components/business/DimensionRadar.vue'
import RiskTag from '@/components/business/RiskTag.vue'
import FollowUpTag from '@/components/business/FollowUpTag.vue'
import { useChart } from '@/composables/useChart'
import { useUserStore } from '@/stores/user'
import { DIMENSION_MAP, fmtTime } from '@/utils/format'
import type { CommunicationMessage, EvaluationRecord } from '@/types'

const route = useRoute()
const user = useUserStore()
const studentRef = route.params.ref as string

const loading = ref(false)
const records = ref<EvaluationRecord[]>([])
const messages = ref<CommunicationMessage[]>([])
const reply = ref('')

const latest = computed(() => (records.value.length ? records.value[records.value.length - 1] : null))
const reversedRecords = computed(() => [...records.value].reverse())

const trendOption = computed<EChartsOption | null>(() => {
  if (!records.value.length) return null
  const dims = Object.keys(DIMENSION_MAP) as (keyof typeof DIMENSION_MAP)[]
  return {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, data: dims.map((d) => DIMENSION_MAP[d]) },
    grid: { left: 8, right: 10, top: 24, bottom: 40, containLabel: true },
    xAxis: { type: 'category', data: records.value.map((r) => fmtTime(r.created_at, 'MM-DD HH:mm')) },
    yAxis: { type: 'value', max: 100 },
    series: dims.map((dim, idx) => ({
      type: 'line',
      smooth: true,
      name: DIMENSION_MAP[dim],
      data: records.value.map((r) => r.result.psychological_profile[dim]),
      itemStyle: { color: ['#f0833c', '#e5655b', '#f2b84b', '#409EFF', '#52b788'][idx % 5] },
    })),
  }
})

const trendEl = useTemplateRef<HTMLElement>('trendEl')
useChart(trendEl, trendOption)

async function load() {
  loading.value = true
  try {
    const [h, c] = await Promise.all([
      historyApi.byStudent(studentRef),
      communicationApi.list(studentRef),
    ])
    records.value = h.records
    messages.value = c.messages
  } finally {
    loading.value = false
  }
}

async function sendReply() {
  if (!reply.value.trim()) return
  await communicationApi.send({
    student_ref: studentRef,
    counselor_ref: user.counselorRef,
    direction: 'counselor_to_student',
    content: reply.value.trim(),
  })
  reply.value = ''
  const c = await communicationApi.list(studentRef)
  messages.value = c.messages
}

onMounted(load)
</script>

<style scoped>
.info-row { padding-bottom: 4px; }
.card-title { margin: 0 0 8px; font-size: 15px; }
.timeline-body { background: var(--xq-primary-lighter); border-radius: 8px; padding: 10px 14px; }
.tl-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.tl-dims { display: flex; flex-wrap: wrap; gap: 6px; }
.dim-tag { font-size: 12px; color: var(--xq-primary-deep); background: #fff; padding: 2px 8px; border-radius: 4px; }
.chat-box { max-height: 360px; overflow-y: auto; padding: 6px 0; }
.chat-msg { margin-bottom: 10px; display: flex; flex-direction: column; }
.chat-msg.student_to_counselor { align-items: flex-start; }
.chat-msg.counselor_to_student { align-items: flex-end; }
.chat-bubble {
  max-width: 72%;
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.6;
}
.chat-msg.student_to_counselor .chat-bubble { background: #f0f2f5; color: #303133; }
.chat-msg.counselor_to_student .chat-bubble { background: var(--xq-primary-light); color: var(--xq-primary-deep); }
.chat-meta { font-size: 11px; color: var(--xq-text-secondary); margin-top: 2px; }
.chat-input-bar { display: flex; gap: 8px; margin-top: 10px; }
</style>
