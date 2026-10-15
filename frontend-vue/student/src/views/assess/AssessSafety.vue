<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { assessmentApi, sessionApi } from '@/api'
import { isApiError } from '@/api/http'
import type { SafetyVerdict } from '@/api/types'
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
const safety = ref<SafetyVerdict | null>(null)

/** 命中安全提示：Safety 判定有风险（需澄清或需支持）。 */
const hit = computed(() => safety.value?.risk_detected === true)

/** 安全支持模式：HIGH / IMMINENT，需要给出即时求助入口。 */
const stopped = computed(() => safety.value?.route === 'safety_stop')

/**
 * 地区适用热线由后端按部署地区下发并已核实，前端不硬编码号码。
 * 部署地区未配置时为空数组，此时不展示任何号码。
 */
const hotlines = computed(() => safety.value?.hotline_numbers ?? [])

onMounted(async () => {
  if (!assess.sessionId) {
    void router.replace({ name: 'assess' })
    return
  }
  loading.value = true
  try {
    const state = await sessionApi.get(assess.sessionId)
    safety.value = state.latest_safety
  } catch (e) {
    if (isApiError(e, 'SESSION_NOT_FOUND')) {
      toastWarn('会话已过期，请重新开始')
      void router.replace({ name: 'assess' })
    }
  } finally {
    loading.value = false
  }
})

function callHotline(number: string) {
  window.location.href = `tel:${number}`
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

      <PxCard v-if="hit" tone="warn" :title="stopped ? '先照顾好自己' : '想再确认一件事'">
        <p class="safety__lead">
          {{
            stopped
              ? '谢谢你愿意说出来。刚才聊到的情况，需要有人在身边陪着你一起看看。如果现在很难受，请第一时间告诉身边可信任的成年人（家人、老师）。'
              : '谢谢你愿意说出来。我还想再确认一下你现在的状态，先别急着继续下面的内容。'
          }}
        </p>
        <ul v-if="safety?.messages?.length" class="safety__reasons">
          <li v-for="(m, i) in safety.messages" :key="i">{{ m }}</li>
        </ul>
        <p v-if="stopped && !hotlines.length" class="safety__lead">
          请尽快联系身边可信任的成年人，或当地急救服务，确保自己此刻有人陪伴。
        </p>
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
        <PxButton
          v-for="number in hotlines"
          :key="number"
          variant="hotline"
          block
          @click="callHotline(number)"
        >
          拨打 {{ number }} 心理援助热线
        </PxButton>
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
