<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import { HEAL_FUNCTIONS, type HealGroup } from '@/views/heal/functions'
import { historyApi } from '@/api'
import { useStudentStore } from '@/stores/student'
import { fmtRelative } from '@/utils/format'
import type { EvaluationRecord } from '@/api/types'

const student = useStudentStore()
const latest = ref<EvaluationRecord | null>(null)

/** 治愈陪伴（#13）是核心，单独做一张大卡片，其余按分组铺开。 */
const CORE = HEAL_FUNCTIONS.find((f) => f.core)
const GROUPS: HealGroup[] = ['陪伴', '工具', '成长', '联结']

const grouped = computed(() =>
  GROUPS.map((group) => ({
    group,
    items: HEAL_FUNCTIONS.filter((f) => f.group === group && !f.core),
  })).filter((x) => x.items.length > 0),
)

const LEVEL_TEXT: Record<string, string> = {
  low_concern: '状态较平稳',
  mild_concern: '轻微关注',
  moderate_concern: '中度关注',
  high_concern: '重点关注',
}

/** 有无测评记录决定治愈陪伴是否可直接进入。 */
const hasAssessment = computed(() => !!latest.value)

onMounted(async () => {
  try {
    const res = await historyApi.byStudent(student.studentRef)
    latest.value = res.records[0] ?? null
  } catch {
    /* 静默降级 */
  }
})
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="心理自助" sub="慢慢来，选一个此刻想做的事" />

    <!-- 核心：治愈陪伴 -->
    <router-link v-if="CORE" to="/heal/chat" class="hh__core">
      <span class="hh__core-badge">推荐</span>
      <div class="hh__core-top">
        <span class="hh__core-icon xq-star">✦</span>
        <div>
          <h2 class="hh__core-title">{{ CORE.title }}</h2>
          <p class="hh__core-desc">{{ CORE.desc }}</p>
        </div>
      </div>
      <p class="hh__core-hint">
        <template v-if="hasAssessment">
          上次测评：{{ fmtRelative(latest!.created_at) }} ·
          {{ LEVEL_TEXT[latest!.result.overall_level] ?? '已完成' }}，去看看小晴写的报告 ›
        </template>
        <template v-else>还没有测评记录，先做一次初步筛查再来 ›</template>
      </p>
    </router-link>

    <!-- 其余功能按分组 -->
    <section v-for="g in grouped" :key="g.group" class="hh__group">
      <h2 class="xq-section-title">{{ g.group }}</h2>
      <div class="hh__grid">
        <router-link v-for="f in g.items" :key="f.key" :to="f.path" class="hh__entry">
          <span class="hh__entry-icon">{{ f.icon }}</span>
          <span class="hh__entry-body">
            <span class="hh__entry-title">{{ f.title }}</span>
            <span class="hh__entry-desc">{{ f.desc }}</span>
          </span>
        </router-link>
      </div>
    </section>

    <p class="xq-disclaimer">
      这里都是帮自己缓一缓的小方法，做不做、做多久都由你决定。如果持续感到难受，
      去看看「专业协作」，或联系校内心理老师。
    </p>
  </div>
</template>

<style scoped>
.hh__core {
  position: relative;
  display: block;
  border: var(--xq-border-pixel);
  background: var(--xq-primary-soft);
  box-shadow: var(--xq-shadow-pixel);
  padding: var(--xq-sp-4);
  color: var(--xq-text);
  transition: transform var(--xq-dur-fast) var(--xq-ease-base),
    box-shadow var(--xq-dur-fast) var(--xq-ease-base);
}
.hh__core:hover {
  transform: translate(-2px, -2px);
  box-shadow: var(--xq-shadow-pixel-lg);
}
.hh__core:active {
  transform: translate(2px, 2px);
  box-shadow: none;
}
.hh__core-badge {
  position: absolute;
  top: -8px;
  right: -8px;
  background: var(--xq-star);
  border: 2px solid var(--xq-text);
  font-size: 10px;
  padding: 1px 6px;
}
.hh__core-top {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-3);
}
.hh__core-icon {
  font-size: 32px;
  color: var(--xq-star);
  flex: 0 0 auto;
}
.hh__core-title {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-lg);
}
.hh__core-desc {
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
  margin-top: 2px;
}
.hh__core-hint {
  margin-top: var(--xq-sp-3);
  padding-top: var(--xq-sp-3);
  border-top: 1px dashed var(--xq-text-disabled);
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.hh__group {
  margin-top: var(--xq-sp-4);
}
.hh__grid {
  display: grid;
  gap: var(--xq-sp-2);
}
.hh__entry {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-3);
  padding: var(--xq-sp-3);
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
  color: var(--xq-text);
  transition: transform var(--xq-dur-fast) var(--xq-ease-base);
}
.hh__entry:active {
  transform: translate(2px, 2px);
  box-shadow: none;
}
.hh__entry-icon {
  flex: 0 0 40px;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface-2);
  font-size: 20px;
  color: var(--xq-primary-deep);
}
.hh__entry-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.hh__entry-title {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-base);
}
.hh__entry-desc {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  line-height: 1.5;
}
@media (min-width: 768px) {
  .hh__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
