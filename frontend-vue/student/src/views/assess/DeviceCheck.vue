<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAssessStore } from '@/stores/assess'
import { useStudentStore } from '@/stores/student'
import { toastWarn } from '@/utils/toast'
import PxButton from '@/components/base/PxButton.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxSteps from '@/components/base/PxSteps.vue'
import PxSwitch from '@/components/base/PxSwitch.vue'
import PxTag from '@/components/base/PxTag.vue'
import PxModal from '@/components/base/PxModal.vue'

const STEPS = ['知情同意', '设备检查', '对话测评', '安全检查', '查看报告']

type MicState = 'idle' | 'checking' | 'ok' | 'fail'

const router = useRouter()
const assess = useAssessStore()
const student = useStudentStore()

// 设备检查页就是本次测评的明确授权入口：用户可以当场允许或拒绝。
// 每次进入或刷新都从关闭开始，避免在没有本次用户手势时自动请求设备。
const micOn = ref(false)
const camOn = ref(false)
const permissionModal = ref<'mic' | 'camera' | null>(null)
const micState = ref<MicState>('idle')
const camRef = ref<HTMLVideoElement | null>(null)
let camStream: MediaStream | null = null

const micInScope = () => assess.consentScopes.includes('audio_transcription')
const cameraInScope = () => assess.consentScopes.includes('vision_analysis')

function requestToggle(kind: 'mic' | 'camera', value: boolean) {
  if (!value) {
    if (kind === 'mic') micOn.value = false
    else camOn.value = false
    return
  }
  if ((kind === 'mic' && !micInScope()) || (kind === 'camera' && !cameraInScope())) {
    toastWarn('本次知情同意未包含该设备，请返回上一步重新选择授权范围')
    return
  }
  permissionModal.value = kind
}

function confirmPermission() {
  const kind = permissionModal.value
  permissionModal.value = null
  if (kind === 'mic') micOn.value = true
  if (kind === 'camera') camOn.value = true
}

/** 打开摄像头并显示自拍预览，方便确认自己在画面里。 */
async function openCam() {
  if (camStream) return
  try {
    camStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'user' },
      audio: false,
    })
    if (!camOn.value) {
      closeCam()
      return
    }
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
// 摄像头开关与麦克风检测互相独立：一拨就即时写回 store，
// 避免麦克风未过检时，摄像头设置被 start() 的提前返回连带丢弃。
watch(camOn, (v) => {
  student.prefs.allowCamera = v
  assess.setCamEnabled(v)
  if (v) void openCam()
  else closeCam()
})

watch(micOn, (v) => {
  student.prefs.allowMic = v
  if (v) {
    void checkMic()
  } else {
    micState.value = 'idle'
    assess.setMicEnabled(false)
  }
})

async function checkMic() {
  if (!micOn.value) {
    micState.value = 'idle'
    assess.setMicEnabled(false)
    return
  }
  micState.value = 'checking'
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    stream.getTracks().forEach((t) => t.stop())
    if (!micOn.value) {
      micState.value = 'idle'
      assess.setMicEnabled(false)
      return
    }
    micState.value = 'ok'
    assess.setMicEnabled(true)
  } catch {
    micState.value = 'fail'
    assess.setMicEnabled(false)
  }
}

function start() {
  if (micOn.value && micState.value !== 'ok') return
  void router.replace({ name: 'assess-session', params: { id: assess.sessionId } })
}

function backToConsent() {
  // 明确回到测评流程的上一步，并复用当前空会话和已选授权，
  // 避免回到测评中心，也避免仅仅修改设备选择时重复创建会话。
  void router.replace({ name: 'assess-consent', query: { edit: 'devices' } })
}

onMounted(() => {
  if (!assess.sessionId) {
    toastWarn('请先完成知情同意')
    void router.replace({ name: 'assess-consent' })
    return
  }
  if (micOn.value) void checkMic()
  else assess.setMicEnabled(false)
  assess.setCamEnabled(camOn.value)
  if (camOn.value) void openCam()
})

onUnmounted(closeCam)
</script>

<template>
  <div class="xq-page check">
    <PxSteps :steps="STEPS" :current="1" />

    <h1 class="xq-page-title">设备检查</h1>
    <p class="xq-muted">确认下面两项设备状态，就可以开始啦。</p>

    <PxCard title="麦克风（可选）" class="check__card">
      <div class="check__row check__row--between check__permission">
        <span>允许后可以用语音回答；不允许时仍可使用文字完成测评。</span>
        <PxSwitch
          :model-value="micOn"
          :label="micOn ? '允许' : '不允许'"
          @update:model-value="requestToggle('mic', $event)"
        />
      </div>
      <div class="check__row">
        <PxTag v-if="!micOn" tone="default">未授权</PxTag>
        <PxTag v-else-if="micState === 'ok'" tone="success">已就绪</PxTag>
        <PxTag v-else-if="micState === 'checking'" tone="default">检测中…</PxTag>
        <PxTag v-else tone="danger">未通过</PxTag>
        <span class="xq-muted">
          {{
            !micOn
              ? '不会请求麦克风权限，可使用文字完成测评。'
              : micState === 'ok'
              ? '能听到你的声音，可以正常对话。'
              : micState === 'checking'
                ? '正在请求麦克风权限…'
                : '请在浏览器允许使用麦克风，然后重新检测。'
          }}
        </span>
      </div>
      <PxButton v-if="micOn" variant="ghost" size="sm" class="check__retry" @click="checkMic">
        重新检测
      </PxButton>
    </PxCard>

    <PxCard title="摄像头（可选）" class="check__card">
      <div class="check__row check__row--between">
        <span>开启后小晴还能看到你的表情状态，<b>也可以随时关闭</b>，不影响测评有效性。</span>
        <PxSwitch
          :model-value="camOn"
          :label="camOn ? '允许' : '不允许'"
          @update:model-value="requestToggle('camera', $event)"
        />
      </div>

      <!-- 自拍预览小窗：确认自己在画面里；正式测评时不再展示 -->
      <div v-show="camOn" class="check__cam">
        <video ref="camRef" class="check__cam-video" muted playsinline autoplay />
        <span class="check__cam-tip">看看自己在不在画面里～</span>
      </div>

      <p class="xq-muted check__note">
        {{ camOn ? '摄像头已就绪；正式对话中会发送至本机项目后端实时分析。' : '未允许摄像头，本次不会请求摄像头权限。' }}
      </p>
    </PxCard>

    <div class="check__actions">
      <PxButton
        size="lg"
        block
        :disabled="micOn && micState !== 'ok'"
        :loading="micState === 'checking'"
        @click="start"
      >
        {{ micOn ? '开始测评' : '开始文字测评' }}
      </PxButton>
      <PxButton variant="ghost" block @click="backToConsent">返回上一步</PxButton>
    </div>

    <p class="xq-disclaimer">测评结果为初步筛查与关注提示，不构成医学诊断。</p>

    <PxModal
      :open="permissionModal !== null"
      :title="permissionModal === 'camera' ? '开启摄像头前请确认' : '开启麦克风前请确认'"
      @close="permissionModal = null"
    >
      <p v-if="permissionModal === 'camera'" class="check__explain">
        摄像头用于分析本次发言期间的表情信息。画面会发送至本机运行的项目后端实时分析，原始画面不写入评估记录。你可以随时关闭，关闭后仍可继续文字或语音筛查。
      </p>
      <p v-else class="check__explain">
        录音会上传至本机项目后端进行文字转写，最长 60 秒。评估使用转写文字和时间信息，不长期保存原始录音；你也可以随时取消并改用文字输入。
      </p>
      <template #footer>
        <PxButton variant="ghost" @click="permissionModal = null">保持关闭</PxButton>
        <PxButton @click="confirmPermission">了解并继续</PxButton>
      </template>
    </PxModal>
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
.check__permission {
  margin-bottom: var(--xq-sp-3);
}
.check__note {
  margin-top: var(--xq-sp-2);
}
.check__explain { line-height: 1.75; }
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
