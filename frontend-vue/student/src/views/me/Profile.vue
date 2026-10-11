<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxInput from '@/components/base/PxInput.vue'
import { useStudentStore } from '@/stores/student'
import type { SchoolStage } from '@/api/types'
import { toastError, toastSuccess } from '@/utils/toast'

const student = useStudentStore()

const STAGE_OPTIONS: { value: SchoolStage; label: string }[] = [
  { value: 'primary', label: '小学' },
  { value: 'middle', label: '初中' },
  { value: 'high', label: '高中' },
]

const nickname = ref('')
const schoolStage = ref<SchoolStage | null>(null)
const className = ref('')
const saving = ref(false)

onMounted(async () => {
  await student.loadProfile()
  nickname.value = student.nickname
  schoolStage.value = student.schoolStage
  className.value = student.className
})

async function save() {
  saving.value = true
  // 先同步本地草稿到 store，再整体提交。
  student.nickname = nickname.value.trim()
  student.schoolStage = schoolStage.value
  student.className = className.value.trim()
  try {
    await student.saveProfile()
    nickname.value = student.nickname
    toastSuccess('已保存')
  } catch {
    toastError('保存失败，请稍后再试')
  } finally {
    saving.value = false
  }
}

async function copyRef() {
  try {
    await navigator.clipboard.writeText(student.studentRef)
    toastSuccess('已复制')
  } catch {
    /* 剪贴板不可用时忽略 */
  }
}
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="个人档案" sub="你的名字，由你来定" back />

    <PxCard title="昵称">
      <PxInput
        v-model="nickname"
        label="怎么称呼你"
        placeholder="例如：小明"
        :maxlength="20"
        hint="留空时，小晴会叫你「小晴的朋友」。"
      />
    </PxCard>

    <PxCard class="pf__block" title="学校阶段">
      <div class="pf__stages">
        <button
          v-for="opt in STAGE_OPTIONS"
          :key="opt.value"
          type="button"
          class="pf__stage"
          :class="{ 'is-active': schoolStage === opt.value }"
          @click="schoolStage = schoolStage === opt.value ? null : opt.value"
        >
          {{ opt.label }}
        </button>
      </div>
      <p class="xq-muted pf__stage-hint">选填，帮助小晴用更合适的方式陪你聊。</p>
    </PxCard>

    <PxCard class="pf__block" title="班级">
      <PxInput v-model="className" label="班级（选填）" placeholder="例如：初二(3)班" :maxlength="40" />
    </PxCard>

    <div class="pf__save">
      <PxButton block :loading="saving" @click="save">保存</PxButton>
    </div>

    <PxCard class="pf__block" title="匿名标识">
      <p class="pf__ref">{{ student.studentRef }}</p>
      <p class="xq-muted">
        这是你在心晴里的匿名编号，不是学号，也不包含你的真实姓名。测评与记录都靠它来区分。
      </p>
      <div class="pf__actions">
        <PxButton size="sm" variant="secondary" @click="copyRef">复制编号</PxButton>
      </div>
    </PxCard>

    <PxCard class="pf__block" title="关于隐私">
      <ul class="pf__list">
        <li>昵称、学校阶段与班级会保存到服务器，让你换设备后也能找回自己的档案。</li>
        <li>测评回答用于生成报告，帮助你与老师了解你的状态。</li>
        <li>你可以随时在「隐私与授权」里导出或删除数据。</li>
      </ul>
    </PxCard>

    <p class="xq-disclaimer">
      档案里不需要填写真实姓名、住址等敏感信息。请不要把别人的资料填到自己名下。
    </p>
  </div>
</template>

<style scoped>
.pf__save {
  margin-top: var(--xq-sp-4);
}
.pf__block {
  margin-top: var(--xq-sp-3);
}
.pf__stages {
  display: flex;
  flex-wrap: wrap;
  gap: var(--xq-sp-2);
}
.pf__stage {
  padding: 6px 16px;
  border-radius: 999px;
  border: var(--xq-border-pixel);
  background: var(--xq-surface-2);
  color: var(--xq-text-2);
  font-size: var(--xq-fs-sm);
  cursor: pointer;
  transition: all 0.15s ease;
}
.pf__stage.is-active {
  border-color: var(--xq-primary);
  background: var(--xq-primary-soft);
  color: var(--xq-primary-deep);
}
.pf__stage-hint {
  margin-top: var(--xq-sp-3);
}
.pf__ref {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-base);
  word-break: break-all;
  margin-bottom: var(--xq-sp-2);
}
.pf__actions {
  margin-top: var(--xq-sp-3);
}
.pf__list {
  display: grid;
  gap: var(--xq-sp-2);
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
  padding-left: 18px;
  list-style: square;
}
</style>
