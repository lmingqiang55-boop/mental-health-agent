<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { sessionApi } from '@/api'
import { useStudentStore } from '@/stores/student'
import { useAssessStore } from '@/stores/assess'
import PxButton from '@/components/base/PxButton.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxSteps from '@/components/base/PxSteps.vue'

const STEPS = ['知情同意', '设备检查', '对话测评', '安全检查', '查看报告']
const REQUIRED_SCOPES = ['text_processing', 'third_party_ai', 'assessment_storage']

const router = useRouter()
const route = useRoute()
const student = useStudentStore()
const assess = useAssessStore()
const loading = ref(true)
const submitting = ref(false)
const sessionId = ref('')
const audioAllowed = ref(false)
const visionAllowed = ref(false)

const canAgree = computed(() => !loading.value && !submitting.value)

async function bootstrap() {
  loading.value = true
  try {
    // 从设备检查返回时仍处在同一次测评流程中，保留当前会话和授权选择。
    // 其他入口（例如“开始新测评”）仍会创建全新的会话。
    if (route.query.edit === 'devices' && assess.sessionId) {
      sessionId.value = assess.sessionId
      audioAllowed.value = assess.consentScopes.includes('audio_transcription')
      visionAllowed.value = assess.consentScopes.includes('vision_analysis')
      return
    }
    const res = await sessionApi.create(student.studentRef)
    sessionId.value = res.session_id
    assess.setSession(res.session_id, 0)
    assess.setConsentScopes([])
    assess.setMicEnabled(false)
    assess.setCamEnabled(false)
  } finally {
    loading.value = false
  }
}

function selectedScopes(textOnly = false): string[] {
  return [
    ...REQUIRED_SCOPES,
    ...(!textOnly && audioAllowed.value ? ['audio_transcription'] : []),
    ...(!textOnly && visionAllowed.value ? ['vision_analysis'] : []),
  ]
}

async function agree(textOnly = false) {
  if (!sessionId.value || !canAgree.value) return
  submitting.value = true
  try {
    const scopes = selectedScopes(textOnly)
    await sessionApi.consent(sessionId.value, true, scopes)
    assess.setConsentScopes(scopes)
    student.prefs.allowMic = scopes.includes('audio_transcription')
    student.prefs.allowCamera = scopes.includes('vision_analysis')
    await router.replace({ name: 'assess-check' })
  } finally {
    submitting.value = false
  }
}

async function decline() {
  if (sessionId.value) {
    await sessionApi.consent(sessionId.value, false, []).catch(() => undefined)
    await sessionApi.remove(sessionId.value).catch(() => undefined)
  }
  assess.clearProgress()
  await router.replace({ name: 'assess' })
}

onMounted(() => void bootstrap())
</script>

<template>
  <div class="xq-page consent">
    <PxSteps :steps="STEPS" :current="0" />
    <h1 class="xq-page-title">开始前，请了解信息如何被处理</h1>
    <p class="xq-muted">本系统用于心理状态辅助筛查，不提供医学诊断，也不用于处分、招生或就业等高影响决定。</p>

    <PxCard title="本次筛查的数据流" class="consent__card">
      <ul class="consent__list">
        <li><b>文字：</b>对话文字会发送至本机项目后端，部分内容会发送给第三方大模型服务生成回复与评估。</li>
        <li><b>语音（可选）：</b>录音上传至本机项目后端转写，最长 60 秒；原始录音不作为评估记录长期保存。</li>
        <li><b>摄像头（可选）：</b>画面发送至本机项目后端实时分析；原始画面不写入评估记录。</li>
        <li><b>结果：</b>保存在运行本系统设备的本地数据库中，直到你主动删除。</li>
        <li><b>身份保护：</b>系统使用随机匿名标识关联记录，页面不会要求填写真实姓名。</li>
        <li>你可以随时撤回同意、关闭设备或删除数据；高风险信息可能触发人工求助提示。</li>
      </ul>
    </PxCard>

    <PxCard title="选择授权范围" class="consent__card">
      <label class="consent__check"><input type="checkbox" checked disabled /> 基础文字处理、第三方模型处理与结果保存（完成筛查必需）</label>
      <label class="consent__check"><input v-model="audioAllowed" type="checkbox" /> 允许语音转写</label>
      <label class="consent__check"><input v-model="visionAllowed" type="checkbox" /> 允许摄像头表情分析</label>
      <p class="xq-muted consent__note">所有可选项目默认关闭。拒绝麦克风或摄像头不影响文字筛查。</p>
    </PxCard>

    <PxCard tone="warn" title="安全提醒" class="consent__card">
      <p class="xq-muted consent__note">本系统只提供心理状态辅助筛查与自助支持，不代替医生、心理咨询师或学校专业人员的判断。</p>
      <p class="consent__help">如正感到难以承受，请立即联系可信任的人或专业机构；紧急危险请拨打 110 / 120。</p>
    </PxCard>

    <div class="consent__actions">
      <PxButton size="lg" block :loading="submitting" :disabled="!canAgree" @click="agree(false)">同意所选项目并开始</PxButton>
      <PxButton variant="secondary" block :disabled="!canAgree" @click="agree(true)">仅使用文字方式</PxButton>
      <PxButton variant="ghost" block :disabled="loading || submitting" @click="decline">不同意并退出</PxButton>
    </div>
    <p v-if="loading" class="xq-muted consent__loading">正在创建不含用户内容的空会话…</p>
  </div>
</template>

<style scoped>
.consent { display: flex; flex-direction: column; gap: var(--xq-sp-3); }
.consent__card { margin-top: var(--xq-sp-2); }
.consent__list { display: flex; flex-direction: column; gap: var(--xq-sp-2); line-height: 1.7; }
.consent__list li { position: relative; padding-left: 18px; }
.consent__list li::before { content: '✦'; position: absolute; left: 0; color: var(--xq-primary-deep); }
.consent__check { display: flex; align-items: flex-start; gap: 10px; margin: 12px 0; line-height: 1.55; }
.consent__check input { width: 18px; height: 18px; margin-top: 2px; accent-color: var(--xq-primary); }
.consent__note, .consent__help { margin-top: var(--xq-sp-3); line-height: 1.65; }
.consent__help { font-weight: 600; }
.consent__actions { display: flex; flex-direction: column; gap: var(--xq-sp-3); margin-top: var(--xq-sp-4); }
.consent__loading { text-align: center; }
@media (min-width: 1024px) { .consent { max-width: 760px; margin: 0 auto; } }
</style>
