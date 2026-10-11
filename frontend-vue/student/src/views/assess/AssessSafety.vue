<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { assessmentApi, sessionApi } from '@/api'
import { isApiError } from '@/api/http'
import type { RiskResult } from '@/api/types'
import { useAssessStore } from '@/stores/assess'
import { toastWarn } from '@/utils/toast'
import PxButton from '@/components/base/PxButton.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import PxSteps from '@/components/base/PxSteps.vue'

const STEPS = ['知情同意', '设备检查', '对话测评', '安全检查', '查看报告']

const router = useRouter()
const assess = useAssessStore()

const loading = ref(true)
const running = ref(false)
const risk = ref<RiskResult | null>(null)

/** 命中风险：需要干预、或达到中/高风险等级。 */
const hit = computed(() => {
  const r = risk.value
  if (!r) return false
  return r.requires_intervention || r.risk_level === 'high' || r.risk_level === 'medium'
})

onMounted(async () => {
  if (!assess.sessionId) {
    void router.replace({ name: 'assess' })
    return
  }
  loading.value = true
  try {
    const state = await sessionApi.get(assess.sessionId)
    risk.value = state.latest_risk
  } catch (e) {
    if (isApiError(e, 'SESSION_NOT_FOUND')) {
      toastWarn('会话已过期，请重新开始')
      void router.replace({ name: 'assess' })
    }
  } finally {
    loading.value = false
  }
})

function callHotline() {
  window.location.href = 'tel:12356'
}

async function generate() {
  if (!assess.sessionId || running.value) return
  running.value = true
  try {
    const res = await assessmentApi.run(assess.sessionId)
    await router.replace({
      name: 'assess-report',
      params: { resultId: res.result.result_id },
      query: { session: res.session_id },
    })
  } catch {
    /* 拦截器已 toastError */
  } finally {
    running.value = false
  }
}
</script>

<template>
  <div class="xq-page safety">
    <PxSteps :steps="STEPS" :current="3" />

    <PxEmpty v-if="loading" icon="…" text="正在整理刚才的对话…" />

    <template v-else>
      <h1 class="xq-page-title">对话结束了</h1>

      <PxCard v-if="hit" tone="warn" title="先照顾好自己">
        <p class="safety__lead">
          谢谢你愿意说出来。刚才聊到的一些情况，值得有人在身边陪着你一起看看。
          如果现在心里的感觉很难受，请第一时间告诉身边可信任的成年人（家人、老师），
          或者拨打下方的心理援助热线。
        </p>
        <ul v-if="risk?.risk_reasons?.length" class="safety__reasons">
          <li v-for="(r, i) in risk.risk_reasons" :key="i">{{ r }}</li>
        </ul>
        <p class="xq-muted safety__note">
          这不是「确诊」，只是提醒我们可以多关注一下自己，也记得寻求身边人的支持。
        </p>
      </PxCard>

      <PxCard v-else title="谢谢你的坦诚">
        <p class="safety__lead">
          谢谢你和我聊了这么久。接下来，我会根据刚才的对话，为你整理一份「初步筛查」结果，
          帮你更了解自己最近的状态。请记得：它只是一个参考，不能代替专业的帮助。
        </p>
      </PxCard>

      <div class="safety__actions">
        <PxButton size="lg" block :loading="running" @click="generate">生成我的报告</PxButton>
        <PxButton v-if="hit" variant="hotline" block @click="callHotline">拨打 12356 心理援助热线</PxButton>
      </div>

      <p class="xq-disclaimer">
        本结果为初步筛查与关注提示，不构成医学诊断，也不代表任何确定性结论。
      </p>
    </template>
  </div>
</template>

<style scoped>
.safety {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
}
.safety__lead {
  line-height: 1.75;
}
.safety__reasons {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: var(--xq-sp-3);
}
.safety__reasons li {
  position: relative;
  padding-left: 18px;
  line-height: 1.7;
}
.safety__reasons li::before {
  content: '▸';
  position: absolute;
  left: 0;
  color: var(--xq-primary-deep);
}
.safety__note {
  margin-top: var(--xq-sp-3);
}
.safety__actions {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
  margin-top: var(--xq-sp-4);
}
@media (min-width: 1024px) {
  .safety {
    max-width: 720px;
    margin: 0 auto;
  }
}
</style>
