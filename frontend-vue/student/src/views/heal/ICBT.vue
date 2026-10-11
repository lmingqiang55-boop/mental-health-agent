<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxTag from '@/components/base/PxTag.vue'
import { icbtApi } from '@/api'
import { useStudentStore } from '@/stores/student'
import { STORAGE_KEYS, readLS, writeLS } from '@/utils/storage'

interface IcbtUnit {
  id: string
  no: number
  title: string
  goal: string
  steps: string[]
}

/** 6 个 iCBT 自助单元：先理解、再练习，每个单元都能单独完成。 */
const UNITS: IcbtUnit[] = [
  {
    id: 'u1',
    no: 1,
    title: '认识情绪',
    goal: '学会给情绪命名，理解情绪没有对错。',
    steps: [
      '回想今天最明显的一种情绪，试着用一个词说出它',
      '给这种情绪的强烈程度打个分（0—10）',
      '注意它出现时身体有什么感觉（胸口、肩膀、胃…）',
    ],
  },
  {
    id: 'u2',
    no: 2,
    title: '想法与情绪',
    goal: '看见「想法」如何影响「感受」。',
    steps: [
      '写下让你难受的一个瞬间',
      '写下当时脑子里冒出的第一句话',
      '问自己：这个想法一定是事实吗？有没有别的解释？',
    ],
  },
  {
    id: 'u3',
    no: 3,
    title: '识别思维陷阱',
    goal: '认识常见的思维偏差，例如「非黑即白」「以偏概全」。',
    steps: [
      '回想一句你常对自己说的话',
      '对照：是不是「全或无」「贴标签」「灾难化」？',
      '把这句话改写得更有弹性一点',
    ],
  },
  {
    id: 'u4',
    no: 4,
    title: '行为激活',
    goal: '通过小小的行动，慢慢把状态带起来。',
    steps: [
      '列出 3 件以前让你感到一点点愉快的事',
      '选最简单的一件，今天就做（哪怕只有 5 分钟）',
      '做完后记录：做之前 / 之后的心情各是多少',
    ],
  },
  {
    id: 'u5',
    no: 5,
    title: '应对压力',
    goal: '在压力来临时，有一套可以自救的小方法。',
    steps: [
      '深呼吸 4-7-8：吸气 4 秒、屏住 7 秒、呼气 8 秒，重复 4 次',
      '把「必须做完」拆成三步，只做第一步',
      '允许自己休息，休息不是偷懒',
    ],
  },
  {
    id: 'u6',
    no: 6,
    title: '求助与支持',
    goal: '知道什么时候、向谁求助是可以的。',
    steps: [
      '写下 2 个你信任的人的名字',
      '想一句可以开口的话：「我最近有点难受，能陪我说说话吗？」',
      '把 12356 和心理老师联系方式存进手机',
    ],
  },
]

const student = useStudentStore()
const done = ref<string[]>([])
const open = ref<string>('u1')

const progress = computed(() => Math.round((done.value.length / UNITS.length) * 100))

onMounted(loadProgress)

/** 完成度以后端为准，同步到本机缓存；后端不可用时静默退回本机进度。 */
async function loadProgress() {
  try {
    done.value = await icbtApi.getProgress(student.studentRef)
    writeLS(STORAGE_KEYS.icbtProgress, done.value)
  } catch {
    done.value = readLS<string[]>(STORAGE_KEYS.icbtProgress, [])
  }
}

function isDone(id: string) {
  return done.value.includes(id)
}

function toggleUnit(id: string) {
  open.value = open.value === id ? '' : id
}

async function markDone(id: string) {
  const next = isDone(id) ? done.value.filter((x) => x !== id) : [...done.value, id]
  done.value = next
  writeLS(STORAGE_KEYS.icbtProgress, next)
  try {
    await icbtApi.setProgress(student.studentRef, next)
  } catch {
    /* 后端不可用：保留本机进度 */
  }
}
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="iCBT 自助单元" sub="每次一小步，学会照顾自己的情绪" back />

    <PxCard title="学习进度">
      <div class="ic__bar">
        <span class="ic__bar-fill" :style="{ width: `${progress}%` }" />
      </div>
      <p class="ic__progress-text">
        已完成 <b>{{ done.length }}</b> / {{ UNITS.length }} 个单元
      </p>
    </PxCard>

    <div class="ic__list">
      <PxCard v-for="u in UNITS" :key="u.id">
        <template #header>
          <span class="px-card__title ic__unit-title">单元 {{ u.no }} · {{ u.title }}</span>
          <PxTag v-if="isDone(u.id)" tone="success" size="sm">已完成</PxTag>
        </template>
        <p class="ic__goal">{{ u.goal }}</p>
        <div v-if="open === u.id" class="ic__steps">
          <ol>
            <li v-for="(s, i) in u.steps" :key="i">{{ s }}</li>
          </ol>
        </div>
        <div class="ic__actions">
          <PxButton size="sm" variant="ghost" @click="toggleUnit(u.id)">
            {{ open === u.id ? '收起' : '展开练习' }}
          </PxButton>
          <PxButton size="sm" :variant="isDone(u.id) ? 'secondary' : 'primary'" @click="markDone(u.id)">
            {{ isDone(u.id) ? '取消完成' : '标记完成' }}
          </PxButton>
        </div>
      </PxCard>
    </div>

    <p class="xq-disclaimer">
      这些单元是自助练习，不是治疗方案，也不能替代专业心理咨询。如果情绪持续低落或出现伤害自己的
      想法，请立刻告诉信任的成年人，或拨打 12356。
    </p>
  </div>
</template>

<style scoped>
.ic__unit-title {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-base);
}
.ic__bar {
  height: 16px;
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface-2);
}
.ic__bar-fill {
  display: block;
  height: 100%;
  background: var(--xq-primary);
  transition: width var(--xq-dur-base) var(--xq-ease-base);
}
.ic__progress-text {
  margin-top: var(--xq-sp-3);
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
}
.ic__progress-text b {
  color: var(--xq-primary-deep);
}
.ic__list {
  display: grid;
  gap: var(--xq-sp-3);
  margin-top: var(--xq-sp-3);
}
.ic__goal {
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
}
.ic__steps {
  margin-top: var(--xq-sp-3);
  border-left: 3px solid var(--xq-primary);
  background: var(--xq-primary-soft);
  padding: var(--xq-sp-3);
}
.ic__steps ol {
  display: grid;
  gap: var(--xq-sp-2);
  padding-left: 18px;
  font-size: var(--xq-fs-sm);
}
.ic__actions {
  display: flex;
  justify-content: space-between;
  gap: var(--xq-sp-2);
  margin-top: var(--xq-sp-4);
}
</style>
