<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import { historyApi } from '@/api'
import type { EvaluationRecord } from '@/api/types'
import { useStudentStore } from '@/stores/student'
import { fmtDateTime } from '@/utils/format'

const router = useRouter()
const student = useStudentStore()

interface NoteItem {
  key: string
  counselor_ref: string
  content: string
  created_at: string
  from: string
}

const notes = ref<NoteItem[]>([])
const records = ref<EvaluationRecord[]>([])
const loading = ref(true)

const latest = computed(() => records.value[0] ?? null)

async function load() {
  try {
    const res = await historyApi.byStudent(student.studentRef)
    records.value = res.records
    const list: NoteItem[] = []
    res.records.forEach((r, ri) => {
      ;(r.counselor_notes ?? []).forEach((n, ni) => {
        list.push({
          key: `${ri}-${ni}`,
          counselor_ref: n.counselor_ref,
          content: n.content,
          created_at: n.created_at,
          from: fmtDateTime(r.created_at),
        })
      })
    })
    notes.value = list.sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
  } catch {
    /* 静默降级 */
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="专业协作" sub="来自老师的建议与关注" back />

    <PxCard tone="primary" title="这是什么">
      <p class="co__lead">
        当你的测评显示需要更多关注时，学校心理老师可能会在这里留下建议。这里的内容只有你和老师能看到。
      </p>
      <div class="co__actions">
        <PxButton size="sm" variant="secondary" @click="router.push('/heal/support')">去留言板</PxButton>
        <PxButton size="sm" variant="ghost" @click="router.push('/me/appointment')">预约咨询</PxButton>
      </div>
    </PxCard>

    <PxCard v-if="latest" class="co__block" title="最近一次测评">
      <ul class="co__facts">
        <li>
          <span>测评时间</span>
          <b>{{ fmtDateTime(latest.created_at) }}</b>
        </li>
        <li>
          <span>关注等级</span>
          <b>{{ latest.result.overall_level }}</b>
        </li>
      </ul>
      <PxButton size="sm" variant="ghost" @click="router.push(`/assess/report/${latest.result.result_id}`)">
        查看完整报告
      </PxButton>
    </PxCard>

    <h2 class="xq-section-title">老师的留言</h2>
    <PxEmpty v-if="!loading && !notes.length" text="暂时还没有老师的留言" />
    <div v-else class="co__list">
      <PxCard v-for="n in notes" :key="n.key">
        <div class="co__note-head">
          <span class="co__counselor">{{ n.counselor_ref || '心理老师' }}</span>
          <span class="co__time">{{ fmtDateTime(n.created_at) }}</span>
        </div>
        <p class="co__content">{{ n.content }}</p>
        <p class="co__from">来自 {{ n.from }} 的测评记录</p>
      </PxCard>
    </div>

    <p class="xq-disclaimer">
      专业协作是老师提供的陪伴与建议，不能替代正式的心理咨询或医疗诊断。
    </p>
  </div>
</template>

<style scoped>
.co__lead {
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
}
.co__actions {
  display: flex;
  gap: var(--xq-sp-2);
  margin-top: var(--xq-sp-4);
}
.co__block {
  margin-top: var(--xq-sp-3);
}
.co__facts {
  display: grid;
  gap: var(--xq-sp-2);
  margin-bottom: var(--xq-sp-3);
}
.co__facts li {
  display: flex;
  justify-content: space-between;
  font-size: var(--xq-fs-sm);
}
.co__facts b {
  color: var(--xq-primary-deep);
}
.co__list {
  display: grid;
  gap: var(--xq-sp-3);
}
.co__note-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: var(--xq-sp-2);
}
.co__counselor {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-sm);
}
.co__time {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.co__content {
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
  white-space: pre-wrap;
  border-left: 3px solid var(--xq-primary);
  background: var(--xq-primary-soft);
  padding: var(--xq-sp-3);
}
.co__from {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  margin-top: var(--xq-sp-2);
}
</style>
