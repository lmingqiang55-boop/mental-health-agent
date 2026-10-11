<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAssessStore } from '@/stores/assess'
import { toastWarn } from '@/utils/toast'
import PxButton from '@/components/base/PxButton.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxSteps from '@/components/base/PxSteps.vue'
import PxSwitch from '@/components/base/PxSwitch.vue'
import PxTag from '@/components/base/PxTag.vue'

const STEPS = ['知情同意', '设备检查', '对话测评', '安全检查', '查看报告']

type MicState = 'idle' | 'checking' | 'ok' | 'fail'

const router = useRouter()
const assess = useAssessStore()

const camOn = ref(assess.camEnabled)
const micState = ref<MicState>('idle')
const camRef = ref<HTMLVideoElement | null>(null)
let camStream: MediaStream | null = null

/** 打开摄像头并显示自拍预览，方便确认自己在画面里。 */
async function openCam() {
  if (camStream) return
  try {
    camStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'user' },
      audio: false,
    })
    if (camRef.value) {
      camRef.value.srcObject = camStream
      await camRef.value.play().catch(() => undefined)
    }
  } catch {
    toastWarn('无法访问摄像头，请检查权限或改用仅语音')
    camOn.value = false
  }
}

function closeCam() {
  camStream?.getTracks().forEach((t) => t.stop())
  camStream = null
  if (camRef.value) camRef.value.srcObject = null
}

// 开关切换即预览/释放；进入正式测评前由 onUnmounted 释放，交给测评页重新取流。
watch(camOn, (v) => {
  if (v) void openCam()
  else closeCam()
})

async function checkMic() {
  micState.value = 'checking'
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    stream.getTracks().forEach((t) => t.stop())
    micState.value = 'ok'
    assess.setMicEnabled(true)
  } catch {
    micState.value = 'fail'
    assess.setMicEnabled(false)
  }
}

function start() {
  if (micState.value !== 'ok') return
  assess.setCamEnabled(camOn.value)
  void router.replace({ name: 'assess-session', params: { id: assess.sessionId } })
}

onMounted(() => {
  if (!assess.sessionId) {
    toastWarn('请先完成知情同意')
    void router.replace({ name: 'assess-consent' })
    return
  }
  void checkMic()
  if (camOn.value) void openCam()
})

onUnmounted(closeCam)
</script>

<template>
  <div class="xq-page check">
    <PxSteps :steps="STEPS" :current="1" />

    <h1 class="xq-page-title">设备检查</h1>
    <p class="xq-muted">确认下面两项设备状态，就可以开始啦。</p>

    <PxCard title="麦克风（必需）" class="check__card">
      <div class="check__row">
        <PxTag v-if="micState === 'ok'" tone="success">已就绪</PxTag>
        <PxTag v-else-if="micState === 'checking'" tone="default">检测中…</PxTag>
        <PxTag v-else tone="danger">未通过</PxTag>
        <span class="xq-muted">
          {{
            micState === 'ok'
              ? '能听到你的声音，可以正常对话。'
              : micState === 'checking'
                ? '正在请求麦克风权限…'
                : '请在浏览器允许使用麦克风，然后重新检测。'
          }}
        </span>
      </div>
      <PxButton variant="ghost" size="sm" class="check__retry" @click="checkMic">
        重新检测
      </PxButton>
    </PxCard>

    <PxCard title="摄像头（可选）" class="check__card">
      <div class="check__row check__row--between">
        <span>开启后小晴还能看到你的表情状态，<b>也可以随时关闭</b>，不影响测评有效性。</span>
        <PxSwitch v-model="camOn" :label="camOn ? '开' : '关'" />
      </div>

      <!-- 自拍预览小窗：确认自己在画面里；正式测评时不再展示 -->
      <div v-show="camOn" class="check__cam">
        <video ref="camRef" class="check__cam-video" muted playsinline autoplay />
        <span class="check__cam-tip">看看自己在不在画面里～</span>
      </div>

      <p class="xq-muted check__note">关闭时仅使用语音，同样可以完成测评。</p>
    </PxCard>

    <div class="check__actions">
      <PxButton
        size="lg"
        block
        :disabled="micState !== 'ok'"
        :loading="micState === 'checking'"
        @click="start"
      >
        开始测评
      </PxButton>
      <PxButton variant="ghost" block @click="router.replace({ name: 'assess' })">返回</PxButton>
    </div>

    <p class="xq-disclaimer">测评结果为初步筛查与关注提示，不构成医学诊断。</p>
  </div>
</template>

<style scoped>
.check {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
}
.check__card {
  margin-top: var(--xq-sp-2);
}
.check__row {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-3);
}
.check__row--between {
  justify-content: space-between;
  flex-wrap: wrap;
}
.check__retry {
  margin-top: var(--xq-sp-3);
}
.check__note {
  margin-top: var(--xq-sp-2);
}
/* ---- 自拍预览小窗 ---- */
.check__cam {
  margin-top: var(--xq-sp-3);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--xq-sp-2);
}
.check__cam-video {
  width: 100%;
  max-width: 240px;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  border-radius: var(--xq-radius-m);
  background: var(--xq-surface-2);
  box-shadow: var(--xq-shadow-pixel-lg);
  transform: scaleX(-1);
}
.check__cam-tip {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.check__actions {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
  margin-top: var(--xq-sp-4);
}
@media (min-width: 1024px) {
  .check {
    max-width: 720px;
    margin: 0 auto;
  }
}
</style>
