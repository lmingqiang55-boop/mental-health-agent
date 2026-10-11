<script setup lang="ts">
import { computed, ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxSwitch from '@/components/base/PxSwitch.vue'
import PxModal from '@/components/base/PxModal.vue'
import { useStudentStore } from '@/stores/student'
import { STORAGE_KEYS, readLS } from '@/utils/storage'
import { toastSuccess } from '@/utils/toast'

const student = useStudentStore()

const consentAck = computed(() => readLS<boolean>(STORAGE_KEYS.consentAck, false))

const confirmOpen = ref(false)
const clearing = ref(false)

/** 导出本机保存的所有偏好与本地记录（xq_ 前缀）。 */
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

/** 清空本机数据并重置匿名身份（旧记录将无法再访问）。 */
function clearAll() {
  clearing.value = true
  try {
    const keys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith('xq_')) keys.push(k)
    }
    keys.forEach((k) => localStorage.removeItem(k))
    sessionStorage.clear()
  } catch {
    /* ignore */
  }
  student.resetIdentity()
  clearing.value = false
  confirmOpen.value = false
  toastSuccess('本机数据已清空')
}
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="隐私与授权" sub="你随时可以决定分享什么" back />

    <PxCard title="采集授权">
      <ul class="pv__switches">
        <li>
          <div class="pv__switch-text">
            <p class="pv__switch-title">允许使用麦克风</p>
            <p class="xq-muted">语音回答需要它。关闭后仍可继续测评，但只能靠文字记录。</p>
          </div>
          <PxSwitch v-model="student.prefs.allowMic" />
        </li>
        <li>
          <div class="pv__switch-text">
            <p class="pv__switch-title">允许使用摄像头</p>
            <p class="xq-muted">默认关闭。开启后会采集表情与注意力信号用于报告解释，可随时关闭。</p>
          </div>
          <PxSwitch v-model="student.prefs.allowCamera" />
        </li>
        <li>
          <div class="pv__switch-text">
            <p class="pv__switch-title">允许在本机保存记录</p>
            <p class="xq-muted">关闭后，心情日记、打卡等本地记录不会被保存。</p>
          </div>
          <PxSwitch v-model="student.prefs.allowStorage" />
        </li>
      </ul>
    </PxCard>

    <PxCard class="pv__block" title="知情同意">
      <p class="pv__ack" :class="consentAck ? 'is-ok' : ''">
        {{ consentAck ? '✓ 你已确认家长与本人已知情并同意' : '尚未完成知情同意确认' }}
      </p>
      <p class="xq-muted">
        首次测评前需要确认家长与学生已知情。这里显示的是你上次的确认状态。
      </p>
    </PxCard>

    <PxCard class="pv__block" title="你的数据">
      <p class="xq-muted pv__data-lead">
        心晴不会把你的回答卖给任何人。测评结果用于生成你的报告与帮助老师了解你的状态。
      </p>
      <div class="pv__data-actions">
        <PxButton variant="secondary" @click="exportData">导出本机数据</PxButton>
        <PxButton variant="danger" @click="confirmOpen = true">清空本机数据</PxButton>
      </div>
    </PxCard>

    <p class="xq-disclaimer">
      清空后你将获得一个新的匿名身份，之前的报告与记录将无法再被访问，请谨慎操作。
    </p>

    <PxModal :open="confirmOpen" title="确定清空本机数据？" width="420px" @close="confirmOpen = false">
      <p class="pv__confirm">
        这会删除本机保存的昵称、联系人、日记、打卡等全部记录，并重置你的匿名身份。此操作不可撤销。
      </p>
      <template #footer>
        <PxButton variant="ghost" @click="confirmOpen = false">再想想</PxButton>
        <PxButton variant="danger" :loading="clearing" @click="clearAll">确定清空</PxButton>
      </template>
    </PxModal>
  </div>
</template>

<style scoped>
.pv__switches {
  display: grid;
  gap: var(--xq-sp-4);
}
.pv__switches li {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--xq-sp-3);
}
.pv__switch-text {
  min-width: 0;
}
.pv__switch-title {
  font-size: var(--xq-fs-base);
  margin-bottom: 2px;
}
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
