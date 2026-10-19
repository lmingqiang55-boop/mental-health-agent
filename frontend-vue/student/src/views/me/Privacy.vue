<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxModal from '@/components/base/PxModal.vue'
import { useStudentStore } from '@/stores/student'
import { useAssessStore } from '@/stores/assess'
import { privacyApi, sessionApi } from '@/api'
import { clearAppLocalStorage, readLS } from '@/utils/storage'
import { toastSuccess, toastWarn } from '@/utils/toast'

const student = useStudentStore()
const assess = useAssessStore()
const router = useRouter()
const consentActive = computed(() => assess.consentScopes.length > 0)
const scopeEnabled = (scope: string) => assess.consentScopes.includes(scope)

const confirmOpen = ref(false)
const clearing = ref(false)

/** 导出浏览器保存的偏好与本地记录（不包含后端 SQLite 数据）。 */
function exportData() {
  const payload: Record<string, unknown> = {
    exported_at: new Date().toISOString(),
    student_ref: student.studentRef,
    nickname: student.nickname,
    contacts: student.contacts,
    prefs: student.prefs,
  }
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith('xq_') && !(k in payload)) {
        payload[k] = readLS(k, null)
      }
    }
  } catch {
    /* ignore */
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `xinqing-export-${student.studentRef}.json`
  a.click()
  URL.revokeObjectURL(url)
  toastSuccess('已导出到本机')
}

/** 先永久删除后端记录，成功后再清理浏览器数据并重置身份。 */
async function clearAll() {
  if (clearing.value) return
  clearing.value = true
  try {
    const oldStudentRef = student.studentRef
    const result = await privacyApi.deleteAll(oldStudentRef)
    // 保留授权选择，尤其是“禁止本地存储”，避免删除后悄悄恢复默认开启。
    clearAppLocalStorage(false)
    sessionStorage.clear()
    student.resetIdentity()
    confirmOpen.value = false
    toastSuccess(`数据已永久删除（后端 ${result.total} 条，本机缓存已清空）`)
  } finally {
    clearing.value = false
  }
}

async function withdrawCurrentConsent() {
  if (!assess.sessionId) {
    toastWarn('当前没有进行中的筛查会话')
    return
  }
  if (!window.confirm('撤回后会结束并删除当前会话，但不会自动删除已经保存的历史报告。是否继续？')) return
  const sid = assess.sessionId
  await sessionApi.consent(sid, false, []).catch(() => undefined)
  await sessionApi.remove(sid).catch(() => undefined)
  assess.clearProgress()
  student.prefs.allowMic = false
  student.prefs.allowCamera = false
  toastSuccess('当前会话授权已撤回并结束')
}

function rotateIdentity() {
  if (!window.confirm('只清除匿名标识不会删除后端旧数据，旧记录也将无法再访问。若想删除数据，请使用“永久删除全部数据”。是否继续？')) return
  clearAppLocalStorage(false)
  sessionStorage.clear()
  assess.clearProgress()
  student.resetIdentity()
  toastSuccess('已生成新的匿名标识')
}
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="隐私与授权" sub="你随时可以决定分享什么" back />

    <PxCard title="当前会话的授权范围">
      <ul class="pv__scope">
        <li><span>基础文字与第三方模型处理</span><b>{{ scopeEnabled('text_processing') ? '已同意' : '未同意' }}</b></li>
        <li><span>麦克风语音转写</span><b>{{ scopeEnabled('audio_transcription') ? '已同意' : '未授权' }}</b></li>
        <li><span>摄像头实时分析</span><b>{{ scopeEnabled('vision_analysis') ? '已同意' : '未授权' }}</b></li>
        <li><span>保存评估结果</span><b>{{ scopeEnabled('assessment_storage') ? '已同意' : '未同意' }}</b></li>
      </ul>
      <div class="pv__data-actions">
        <PxButton variant="danger" :disabled="!consentActive" @click="withdrawCurrentConsent">撤回当前会话同意</PxButton>
        <PxButton variant="ghost" @click="router.push({ name: 'assess-consent' })">新建会话并重新选择</PxButton>
      </div>
    </PxCard>

    <PxCard class="pv__block" title="知情同意">
      <p class="pv__ack" :class="consentActive ? 'is-ok' : ''">
        {{ consentActive ? '✓ 当前会话已完成 1.0 版知情同意' : '当前没有生效中的会话授权' }}
      </p>
      <p class="xq-muted">
        每次新建筛查会话都需要重新确认，系统不会沿用旧授权自动开启摄像头或麦克风。
      </p>
    </PxCard>

    <PxCard class="pv__block" title="数据处理说明">
      <ul class="pv__details">
        <li><b>采集内容：</b>对话文字，以及你单独授权的语音转写和摄像头特征。</li>
        <li><b>处理位置：</b>音频与画面发送至本机运行的项目后端；文字可能发送至第三方大模型服务。</li>
        <li><b>保存方式：</b>评估结果保存在运行本系统设备的本地数据库中，直到你主动删除；原始录音和原始画面不作为评估记录长期保存。</li>
        <li><b>身份保护：</b>记录使用随机匿名标识关联，不会在学生页面向其他用户公开真实身份。</li>
      </ul>
      <PxButton variant="secondary" @click="router.push({ name: 'assess' })">查看我的历史记录</PxButton>
    </PxCard>

    <PxCard class="pv__block" title="你的数据">
      <p class="xq-muted pv__data-lead">
        浏览器缓存和本机后端数据库可以一并删除。对话与语音合成所使用的外部模型服务，仍按相应服务商的数据政策处理已发送内容。
      </p>
      <div class="pv__data-actions">
        <PxButton variant="secondary" @click="exportData">导出浏览器数据</PxButton>
        <PxButton variant="ghost" @click="rotateIdentity">清除此设备匿名标识</PxButton>
        <PxButton variant="danger" @click="confirmOpen = true">永久删除全部数据</PxButton>
      </div>
    </PxCard>

    <p class="xq-disclaimer">
      删除会清除当前匿名身份在浏览器和本机后端中的记录，并生成新身份。此操作不可撤销。
    </p>

    <PxModal :open="confirmOpen" title="确定永久删除全部数据？" width="420px" @close="confirmOpen = false">
      <p class="pv__confirm">
        这会删除当前匿名身份的测评报告、教师备注、档案、联系人、日记、打卡、预约、沟通消息、会话和浏览器缓存，并生成新的匿名身份。已经发送给外部模型服务的数据无法通过本按钮撤回。
      </p>
      <template #footer>
        <PxButton variant="ghost" @click="confirmOpen = false">再想想</PxButton>
        <PxButton variant="danger" :loading="clearing" @click="clearAll">永久删除</PxButton>
      </template>
    </PxModal>
  </div>
</template>

<style scoped>
.pv__scope, .pv__details { display: grid; gap: 10px; margin-bottom: var(--xq-sp-3); }
.pv__scope li { display: flex; justify-content: space-between; gap: 16px; }
.pv__scope b { color: var(--xq-primary-deep); white-space: nowrap; }
.pv__details { line-height: 1.7; }
.pv__block {
  margin-top: var(--xq-sp-3);
}
.pv__ack {
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
  margin-bottom: var(--xq-sp-2);
}
.pv__ack.is-ok {
  color: var(--xq-success);
}
.pv__data-lead {
  margin-bottom: var(--xq-sp-3);
}
.pv__data-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--xq-sp-2);
}
.pv__confirm {
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
}
</style>
