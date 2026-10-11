<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxInput from '@/components/base/PxInput.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import { STORAGE_KEYS, readLS, writeLS } from '@/utils/storage'
import { uid } from '@/utils/id'
import { fmtDateTime } from '@/utils/format'
import { toastSuccess, toastWarn } from '@/utils/toast'

interface ReframeNote {
  id: string
  situation: string
  thought: string
  support: string
  against: string
  balanced: string
  createdAt: number
}

const notes = ref<ReframeNote[]>([])
const situation = ref('')
const thought = ref('')
const support = ref('')
const against = ref('')
const balanced = ref('')

onMounted(() => {
  notes.value = readLS<ReframeNote[]>(STORAGE_KEYS.reframeNotes, [])
})

function persist() {
  writeLS(STORAGE_KEYS.reframeNotes, notes.value)
}

function save() {
  if (!situation.value.trim() || !thought.value.trim()) {
    toastWarn('先写下发生了什么、当时冒出的想法')
    return
  }
  notes.value = [
    {
      id: uid('rf'),
      situation: situation.value.trim(),
      thought: thought.value.trim(),
      support: support.value.trim(),
      against: against.value.trim(),
      balanced: balanced.value.trim(),
      createdAt: Date.now(),
    },
    ...notes.value,
  ]
  persist()
  situation.value = ''
  thought.value = ''
  support.value = ''
  against.value = ''
  balanced.value = ''
  toastSuccess('记下来了，换个角度看看它')
}

function remove(id: string) {
  notes.value = notes.value.filter((n) => n.id !== id)
  persist()
}
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="认知重构" sub="把想法拆开看看，它也许没这么绝对" back />

    <PxCard title="四步拆想法">
      <div class="rf__form">
        <PxInput v-model="situation" label="① 发生了什么" placeholder="例如：今天上课回答问题答错了" />
        <PxInput v-model="thought" label="② 当时冒出的想法" placeholder="例如：我什么都做不好" />
        <PxInput v-model="support" label="③ 支持它的证据" placeholder="有哪些事实真的支持这个想法？" />
        <PxInput v-model="against" label="④ 不支持它的证据" placeholder="有没有相反的例子？别人会怎么看？" />
        <PxInput v-model="balanced" label="⑤ 更平衡的说法" placeholder="例如：这次没答好，但我会的东西也不少" />
      </div>
      <div class="rf__save">
        <PxButton block @click="save">保存这次练习</PxButton>
      </div>
    </PxCard>

    <h2 class="xq-section-title">我的练习（仅保存在本机）</h2>
    <PxEmpty v-if="!notes.length" text="还没有记录，慢慢来" />
    <div v-else class="rf__list">
      <PxCard v-for="n in notes" :key="n.id" :title="fmtDateTime(n.createdAt)">
        <dl class="rf__dl">
          <dt>发生了什么</dt>
          <dd>{{ n.situation }}</dd>
          <dt>原来的想法</dt>
          <dd>{{ n.thought }}</dd>
          <dt v-if="n.against">不支持它的证据</dt>
          <dd v-if="n.against">{{ n.against }}</dd>
          <dt v-if="n.balanced">更平衡的说法</dt>
          <dd v-if="n.balanced" class="rf__balanced">{{ n.balanced }}</dd>
        </dl>
        <div class="rf__actions">
          <PxButton size="sm" variant="ghost" @click="remove(n.id)">删除</PxButton>
        </div>
      </PxCard>
    </div>

    <p class="xq-disclaimer">
      认知重构是常见的自助练习方式，它帮你看见想法的其他可能，不代表你的感受是「错的」。
      如果情绪持续低落，请告诉信任的大人或专业老师。
    </p>
  </div>
</template>

<style scoped>
.rf__form {
  display: grid;
  gap: var(--xq-sp-3);
}
.rf__save {
  margin-top: var(--xq-sp-4);
}
.rf__list {
  display: grid;
  gap: var(--xq-sp-3);
}
.rf__dl {
  display: grid;
  gap: 2px;
  font-size: var(--xq-fs-sm);
}
.rf__dl dt {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  margin-top: var(--xq-sp-2);
}
.rf__dl dt:first-child {
  margin-top: 0;
}
.rf__balanced {
  border-left: 3px solid var(--xq-primary);
  padding-left: var(--xq-sp-2);
  background: var(--xq-primary-soft);
}
.rf__actions {
  margin-top: var(--xq-sp-3);
  text-align: right;
}
</style>
