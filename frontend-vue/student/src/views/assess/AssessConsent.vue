<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { sessionApi } from '@/api'
import { useStudentStore } from '@/stores/student'
import { useAssessStore } from '@/stores/assess'
import { STORAGE_KEYS, readLS, writeLS } from '@/utils/storage'
import PxButton from '@/components/base/PxButton.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxSteps from '@/components/base/PxSteps.vue'

const STEPS = ['知情同意', '设备检查', '对话测评', '安全检查', '查看报告']

const router = useRouter()
const student = useStudentStore()
const assess = useAssessStore()

const loading = ref(true)
const submitting = ref(false)
const sessionId = ref('')
/** 历史上是否已同意过（呈现型授权，不强制门控）。 */
const acked = ref(readLS<boolean>(STORAGE_KEYS.consentAck, false))

/** 创建会话；若曾经同意过则静默补齐 consent 后直接进入设备检查。 */
async function bootstrap() {
  loading.value = true
  try {
    const res = await sessionApi.create(student.studentRef)
    sessionId.value = res.session_id
    assess.setSession(res.session_id, 0)
    if (acked.value) {
      await sessionApi.consent(res.session_id, true)
      await router.replace({ name: 'assess-check' })
    }
  } catch {
    /* 拦截器已 toastError */
  } finally {
    loading.value = false
  }
}

async function agree() {
  if (!sessionId.value || submitting.value) return
  submitting.value = true
  try {
    await sessionApi.consent(sessionId.value, true)
    writeLS(STORAGE_KEYS.consentAck, true)
    acked.value = true
    await router.replace({ name: 'assess-check' })
  } catch {
    /* 拦截器已 toastError */
  } finally {
    submitting.value = false
  }
}

function decline() {
  void router.replace({ name: 'assess' })
}

onMounted(() => {
  void bootstrap()
})
</script>

<template>
  <div class="xq-page consent">
    <PxSteps :steps="STEPS" :current="0" />

    <h1 class="xq-page-title">开始前的知情同意</h1>
    <p class="xq-muted">在和小晴聊天之前，想先跟你说清楚我们会做什么、不会做什么。</p>

    <PxCard title="我们会这样使用你的信息" class="consent__card">
      <ul class="consent__list">
        <li>语音：仅<b>当场转写为文字</b>用于对话，<b>不留存原始录音</b>。</li>
        <li>摄像头（可选）：仅提取表情、注意力等<b>特征</b>，<b>不保存画面</b>。</li>
        <li>结果：只用于生成一份「<b>初步筛查</b>」报告，供你自己了解，<b>不用于诊断</b>。</li>
        <li>你可以随时关闭麦克风 / 摄像头，或中止本次测评。</li>
      </ul>
    </PxCard>

    <PxCard tone="warn" title="重要提醒" class="consent__card">
      <p>
        本测评<b>不构成医学诊断</b>，也不会给出「确诊 / 患病」之类的结论，只是帮你了解一下最近的状态。
        如果你正感到难以承受，请第一时间告诉身边可信任的成年人，或拨打全国心理援助热线
        <b>12356</b>（24 小时，可匿名）。
      </p>
    </PxCard>

    <div class="consent__actions">
      <PxButton
        size="lg"
        block
        :loading="submitting"
        :disabled="loading"
        @click="agree"
      >
        家长和学生已知情并同意
      </PxButton>
      <PxButton variant="ghost" block :disabled="loading || submitting" @click="decline">
        暂不测评
      </PxButton>
    </div>

    <p v-if="loading" class="xq-muted consent__loading">正在准备…</p>
  </div>
</template>

<style scoped>
.consent {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
}
.consent__card {
  margin-top: var(--xq-sp-2);
}
.consent__list {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-2);
}
.consent__list li {
  position: relative;
  padding-left: 18px;
  line-height: 1.7;
}
.consent__list li::before {
  content: '✦';
  position: absolute;
  left: 0;
  color: var(--xq-primary-deep);
}
.consent__actions {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
  margin-top: var(--xq-sp-4);
}
.consent__loading {
  text-align: center;
}
@media (min-width: 1024px) {
  .consent {
    max-width: 720px;
    margin: 0 auto;
  }
}
</style>
