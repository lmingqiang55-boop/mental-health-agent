<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import { communicationApi } from '@/api'
import type { CommunicationMessage } from '@/api/types'
import { useStudentStore } from '@/stores/student'
import { fmtDateTime } from '@/utils/format'
import { toastWarn } from '@/utils/toast'

const student = useStudentStore()

const messages = ref<CommunicationMessage[]>([])
const draft = ref('')
const sending = ref(false)
const loading = ref(true)

async function load() {
  try {
    const res = await communicationApi.list(student.studentRef)
    messages.value = res.messages
  } catch {
    /* 静默降级 */
  } finally {
    loading.value = false
  }
}

async function send() {
  const content = draft.value.trim()
  if (!content) {
    toastWarn('先写点什么再发送')
    return
  }
  sending.value = true
  try {
    const res = await communicationApi.send({
      student_ref: student.studentRef,
      direction: 'student_to_counselor',
      content,
    })
    messages.value = [...messages.value, res.message]
    draft.value = ''
  } catch {
    /* 拦截器已提示 */
  } finally {
    sending.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="同伴支持" sub="把想说的话留在这里，会有老师看到" back />

    <PxCard title="留言板">
      <PxEmpty v-if="!loading && !messages.length" text="还没有消息，写下你的第一句话吧" />
      <ul v-else class="sp__list">
        <li
          v-for="(m, i) in messages"
          :key="m.id ?? i"
          class="sp__row"
          :class="m.direction === 'student_to_counselor' ? 'is-me' : 'is-them'"
        >
          <div class="sp__bubble">
            <p class="sp__content">{{ m.content }}</p>
            <span class="sp__time">{{ m.created_at ? fmtDateTime(m.created_at) : '' }}</span>
          </div>
        </li>
      </ul>
    </PxCard>

    <PxCard class="sp__block" title="写一条留言">
      <textarea
        v-model="draft"
        class="sp__textarea"
        rows="3"
        maxlength="500"
        placeholder="说说最近发生了什么，或者只是想找个人聊聊"
      />
      <div class="sp__actions">
        <span class="xq-muted">{{ draft.length }}/500</span>
        <PxButton :loading="sending" @click="send">发送</PxButton>
      </div>
    </PxCard>

    <PxCard class="sp__block" title="如果现在很难受">
      <p class="sp__help">
        留言不一定能马上收到回复。如果你正在经历强烈痛苦，请立刻拨打
        <a href="tel:12356">12356</a>，或联系学校的心理老师。
      </p>
    </PxCard>

    <p class="xq-disclaimer">
      同伴支持是留言式的相互陪伴，不能替代专业心理咨询。紧急情况请优先寻求成年人帮助。
    </p>
  </div>
</template>

<style scoped>
.sp__list {
  display: grid;
  gap: var(--xq-sp-3);
}
.sp__row {
  display: flex;
}
.sp__row.is-me {
  justify-content: flex-end;
}
.sp__row.is-them {
  justify-content: flex-start;
}
.sp__bubble {
  max-width: 80%;
  border: var(--xq-border-pixel-thin);
  padding: var(--xq-sp-3);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.sp__row.is-me .sp__bubble {
  background: var(--xq-primary-soft);
}
.sp__row.is-them .sp__bubble {
  background: var(--xq-surface-2);
}
.sp__content {
  font-size: var(--xq-fs-sm);
  white-space: pre-wrap;
  word-break: break-word;
}
.sp__time {
  display: block;
  margin-top: 6px;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.sp__block {
  margin-top: var(--xq-sp-3);
}
.sp__textarea {
  width: 100%;
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  color: var(--xq-text);
  padding: 10px;
  font: inherit;
  font-size: var(--xq-fs-sm);
  resize: vertical;
}
.sp__textarea:focus {
  outline: none;
  box-shadow: var(--xq-shadow-pixel-sm);
}
.sp__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--xq-sp-3);
}
.sp__help {
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
}
.sp__help a {
  color: var(--xq-danger);
  font-weight: 700;
}
</style>
