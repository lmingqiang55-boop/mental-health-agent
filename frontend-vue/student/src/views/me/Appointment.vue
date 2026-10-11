<script setup lang="ts">
import { onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxInput from '@/components/base/PxInput.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import { appointmentApi, type StudentAppointment } from '@/api'
import { useStudentStore } from '@/stores/student'
import { readLS, writeLS } from '@/utils/storage'
import { uid } from '@/utils/id'
import { fmtDate } from '@/utils/format'
import { toastSuccess, toastWarn } from '@/utils/toast'

/** 预约意向会同步到学校端供老师查看；后端不可用时静默退回本机记录。 */
const KEY = 'xq_appointments'

const student = useStudentStore()

const SLOTS = ['午休 12:30', '下午课后 16:30', '放学后 17:30']

const date = ref(dayjs().add(1, 'day').format('YYYY-MM-DD'))
const slot = ref(SLOTS[0])
const topic = ref('')
const list = ref<StudentAppointment[]>([])
const submitting = ref(false)

onMounted(loadList)

function persistLocal() {
  writeLS(KEY, list.value)
}

async function loadList() {
  try {
    list.value = await appointmentApi.list(student.studentRef)
    persistLocal()
  } catch {
    /* 后端不可用：退回本机记录 */
    list.value = readLS<StudentAppointment[]>(KEY, [])
  }
}

async function submit() {
  if (!date.value) {
    toastWarn('请选择希望的日期')
    return
  }
  if (submitting.value) return
  submitting.value = true
  const text = topic.value.trim()
  try {
    const created = await appointmentApi.create(student.studentRef, date.value, slot.value, text)
    list.value = [created, ...list.value]
    toastSuccess('已记录，去和老师确认一下吧')
  } catch {
    /* 后端不可用：仍然记在本机，不打断学生 */
    list.value = [
      { id: uid('ap'), date: date.value, slot: slot.value, topic: text, status: 'pending', createdAt: Date.now() },
      ...list.value,
    ]
  } finally {
    persistLocal()
    submitting.value = false
    topic.value = ''
  }
}

async function cancel(id: string) {
  try {
    await appointmentApi.cancel(id)
  } catch {
    /* 后端不可用：仅删本机记录 */
  }
  list.value = list.value.filter((a) => a.id !== id)
  persistLocal()
}
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="咨询预约" sub="找老师聊一聊，也是照顾自己" back />

    <PxCard tone="primary" title="预约前想说">
      <p class="ap__lead">
        预约心理老师不代表你有「问题」。有心事想找人说说，本身就很正常。你可以先在这里写下
        想聊的时间与话题，学校心理老师会看到并帮你安排后续。
      </p>
    </PxCard>

    <PxCard class="ap__block" title="填写预约意向">
      <div class="ap__form">
        <PxInput v-model="date" type="date" label="希望的日期" />
        <div class="ap__slots">
          <p class="ap__label">希望的时间</p>
          <div class="ap__slot-row">
            <button
              v-for="s in SLOTS"
              :key="s"
              type="button"
              class="ap__slot"
              :class="{ 'is-on': slot === s }"
              @click="slot = s"
            >
              {{ s }}
            </button>
          </div>
        </div>
        <PxInput
          v-model="topic"
          label="想聊的话题（选填）"
          placeholder="例如：最近睡不好 / 和朋友闹矛盾"
          :maxlength="60"
        />
      </div>
      <div class="ap__submit">
        <PxButton block @click="submit">记录预约意向</PxButton>
      </div>
    </PxCard>

    <h2 class="xq-section-title">我的预约意向</h2>
    <PxEmpty v-if="!list.length" text="还没有预约记录" />
    <div v-else class="ap__list">
      <PxCard v-for="a in list" :key="a.id">
        <div class="ap__item-head">
          <span class="ap__item-date">{{ fmtDate(a.date) }} · {{ a.slot }}</span>
          <PxButton size="sm" variant="ghost" @click="cancel(a.id)">取消</PxButton>
        </div>
        <p v-if="a.topic" class="ap__item-topic">{{ a.topic }}</p>
        <p v-else class="xq-muted">未填写话题</p>
      </PxCard>
    </div>

    <PxCard class="ap__block" tone="warn" title="如何真正预约">
      <ul class="ap__steps">
        <li>把上面选好的时间告诉班主任或心理辅导室老师；</li>
        <li>或直接前往学校心理咨询室，门口通常有预约方式；</li>
        <li>如果你很难受，不用等预约，随时可以先找信任的老师聊聊。</li>
      </ul>
    </PxCard>

    <p class="xq-disclaimer">
      提交后学校心理老师可以看到你的预约意向，用于提前安排时间；如需撤回，点击上方「取消」即可。
    </p>
  </div>
</template>

<style scoped>
.ap__lead {
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
}
.ap__block {
  margin-top: var(--xq-sp-3);
}
.ap__form {
  display: grid;
  gap: var(--xq-sp-3);
}
.ap__label {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  margin-bottom: var(--xq-sp-2);
}
.ap__slot-row {
  display: grid;
  gap: var(--xq-sp-2);
}
.ap__slot {
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  padding: 10px;
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
  text-align: left;
}
.ap__slot.is-on {
  background: var(--xq-primary-soft);
  color: var(--xq-text);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.ap__submit {
  margin-top: var(--xq-sp-4);
}
.ap__list {
  display: grid;
  gap: var(--xq-sp-3);
}
.ap__item-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.ap__item-date {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-sm);
}
.ap__item-topic {
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
  margin-top: var(--xq-sp-2);
}
.ap__steps {
  display: grid;
  gap: var(--xq-sp-2);
  font-size: var(--xq-fs-sm);
  line-height: 1.6;
  padding-left: 18px;
  list-style: decimal;
}
</style>
