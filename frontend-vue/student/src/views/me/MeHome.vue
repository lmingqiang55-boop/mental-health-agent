<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import { useStudentStore } from '@/stores/student'
import { healApi } from '@/api'
import type { GrowthResponse } from '@/api/types'

const router = useRouter()
const student = useStudentStore()

const growth = ref<GrowthResponse | null>(null)

const maskedRef = computed(() => {
  const r = student.studentRef
  return r.length > 12 ? `${r.slice(0, 6)}…${r.slice(-4)}` : r
})

const ENTRIES = [
  { title: '个人档案', desc: '昵称与基本信息', icon: '✦', path: '/me/profile' },
  { title: '专业协作', desc: '老师的建议与留言', icon: '❖', path: '/me/collaboration' },
  { title: '咨询预约', desc: '预约校内心理老师', icon: '✚', path: '/me/appointment' },
  { title: '隐私与授权', desc: '相机 / 麦克风 / 数据', icon: '⛨', path: '/me/privacy' },
  { title: '紧急联系人', desc: '需要时能联系到的人', icon: '☏', path: '/me/contacts' },
  { title: '消息中心', desc: '测评与留言通知', icon: '✉', path: '/me/messages' },
  { title: '设置', desc: '主题与偏好', icon: '⚙', path: '/me/settings' },
  { title: '成长回顾', desc: '看看你的记录', icon: '★', path: '/heal/growth' },
]

async function load() {
  try {
    growth.value = await healApi.growth(student.studentRef, 90)
  } catch {
    /* 静默降级 */
  }
}

onMounted(load)
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="我的" sub="你的空间，只有你能做主" />

    <PxCard tone="primary">
      <div class="mh__profile">
        <div class="mh__avatar">☺</div>
        <div class="mh__info">
          <p class="mh__name">{{ student.displayName }}</p>
          <p class="mh__ref">匿名标识：{{ maskedRef }}</p>
        </div>
      </div>
      <div class="mh__profile-actions">
        <PxButton size="sm" variant="secondary" @click="router.push('/me/profile')">编辑档案</PxButton>
        <PxButton size="sm" variant="ghost" @click="router.push('/me/privacy')">隐私设置</PxButton>
      </div>
    </PxCard>

    <PxCard class="mh__block" title="这 90 天">
      <ul class="mh__stats">
        <li>
          <strong>{{ growth?.mood_days ?? 0 }}</strong>
          <em>心情记录</em>
        </li>
        <li>
          <strong>{{ growth?.streak ?? 0 }}</strong>
          <em>连续打卡</em>
        </li>
        <li>
          <strong>{{ growth?.focus_minutes ?? 0 }}</strong>
          <em>专注分钟</em>
        </li>
      </ul>
    </PxCard>

    <h2 class="xq-section-title">常用</h2>
    <div class="mh__grid">
      <button
        v-for="e in ENTRIES"
        :key="e.path"
        type="button"
        class="mh__entry"
        @click="router.push(e.path)"
      >
        <span class="mh__entry-icon">{{ e.icon }}</span>
        <span class="mh__entry-title">{{ e.title }}</span>
        <span class="mh__entry-desc">{{ e.desc }}</span>
      </button>
    </div>

    <PxCard class="mh__block" tone="warn" title="需要帮助的时候">
      <p class="mh__help">
        如果你正感到难以承受，请拨打 <a href="tel:12356">12356</a>，或告诉信任的大人、老师。
        你不需要一个人扛着。
      </p>
    </PxCard>

    <p class="xq-disclaimer">
      心晴是测评与自助陪伴工具，不能替代专业诊断与治疗。所有回答仅保存在本机与学校服务器，用于帮助你。
    </p>
  </div>
</template>

<style scoped>
.mh__profile {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-4);
}
.mh__avatar {
  width: 56px;
  height: 56px;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.mh__info {
  min-width: 0;
}
.mh__name {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-lg);
}
.mh__ref {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  margin-top: 4px;
  word-break: break-all;
}
.mh__profile-actions {
  display: flex;
  gap: var(--xq-sp-2);
  margin-top: var(--xq-sp-4);
}
.mh__block {
  margin-top: var(--xq-sp-3);
}
.mh__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  text-align: center;
}
.mh__stats strong {
  display: block;
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-2xl);
  color: var(--xq-primary-deep);
}
.mh__stats em {
  font-style: normal;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.mh__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--xq-sp-3);
}
.mh__entry {
  display: grid;
  gap: 2px;
  text-align: left;
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  padding: var(--xq-sp-4);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.mh__entry-icon {
  font-size: 20px;
  color: var(--xq-primary-deep);
}
.mh__entry-title {
  font-size: var(--xq-fs-base);
  margin-top: 4px;
}
.mh__entry-desc {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.mh__help {
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
}
.mh__help a {
  color: var(--xq-hotline);
  font-weight: 700;
}
@media (min-width: 1024px) {
  .mh__grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
</style>
