<script setup lang="ts">
/**
 * 多智能体运行轨迹面板（演示专用，默认不出现）。
 *
 * 数据全部来自后端 `/api/chat` 的真实执行记录（`trace` 字段），前端不做任何
 * 推断与补全：后端没给的信息这里就显示「—」，绝不画一条假的调用流程。
 *
 * 【如实标注】Safety 目前在 LangGraph **之外**执行，因此单独放在「图外 · 前置」
 * 分组里，不与图内节点混在一起。
 */
import { computed } from 'vue'
import type { AgentTrace, TraceState } from '@/api/types'

const props = defineProps<{
  trace: AgentTrace | null
  /** 轮次；变化时整块重新入场，让"这一轮又跑了一遍"看得见。 */
  turn?: number
}>()

/** 状态 → 徽标文案。四态是后端定的统一词表，前端只负责显示。 */
const STATE_BADGES: Record<TraceState, string> = {
  ran: '已调用',
  skipped: '跳过',
  short_circuit: '提前结束',
  unavailable: '不适用',
}

const SAFETY_OUTCOMES: Record<string, string> = {
  continue: '放行，进入多轮评估对话',
  review: '不放行，转入安全澄清',
  stop: '不放行，转入安全支持',
}

const RISK_LABELS: Record<string, string> = {
  normal: '正常',
  uncertain: '不确定',
  high: '高风险',
  imminent: '紧急',
}

interface Row {
  key: string
  name: string
  state: TraceState
  detail: string
  note?: string
}

interface Group {
  key: string
  label: string
  rows: Row[]
}

const groups = computed<Group[]>(() => {
  const trace = props.trace
  if (!trace) return []

  const safety: Row = {
    key: 'safety',
    name: 'Safety Agent',
    state: trace.safety.state,
    detail: SAFETY_OUTCOMES[trace.safety.outcome] ?? trace.safety.outcome,
    note: `${trace.safety.engine} · ${RISK_LABELS[trace.safety.risk_level] ?? trace.safety.risk_level}/${trace.safety.route}`,
  }

  const dialogue: Row = {
    key: 'dialogue',
    name: 'Dialogue Agent',
    state: trace.dialogue.state,
    detail: dialogueDetail(trace),
    note: trace.dialogue.reason_code || trace.dialogue.forced_reason || undefined,
  }

  const decision: Row = {
    key: 'decision',
    name: 'Decision Agent',
    state: trace.decision.state,
    detail: trace.decision.strategy
      ? `${trace.decision.label} → ${trace.decision.strategy}`
      : trace.decision.label || '—',
  }

  const vision: Row = {
    key: 'vision',
    name: '视觉感知',
    state: trace.vision.state,
    detail: visionDetail(trace),
    note: `reason=${trace.vision.reason}`,
  }

  const output: Row = {
    key: 'output',
    name: '消息输出',
    state: 'ran',
    detail: `${trace.output.bubbles} 条聊天气泡`,
  }

  return [
    {
      key: 'pre',
      // 位置说明直接用后端给的 placement_label（"前置安全检查（LangGraph 之外）"），
      // 前端不自己写一句架构描述，免得跟实现走样。
      label: trace.safety.placement_label,
      rows: [safety],
    },
    {
      key: 'graph',
      label: `图内 · ${trace.engine === 'graph' ? 'LangGraph 调度' : `${trace.engine} 顺序执行`}`,
      rows: [dialogue, decision, vision],
    },
    { key: 'out', label: '输出', rows: [output] },
  ]
})

/** Dialogue 这一轮到底干了什么：自主继续 / 自主请求新策略 / 没被问到。 */
function dialogueDetail(trace: AgentTrace): string {
  const { state, routed, need_decision, reason_label, forced_label } = trace.dialogue
  if (state === 'short_circuit') return '安全分支提前结束，本轮未执行'
  if (state === 'unavailable') return '该引擎不提供图内调度信息'
  if (routed === false) {
    return forced_label ? `未询问 Dialogue，后端强制换策略（${forced_label}）` : '未询问 Dialogue，后端强制换策略'
  }
  const why = reason_label ? `（${reason_label}）` : ''
  return need_decision
    ? `自主路由：请求新策略${why}`
    : `自主路由：继续当前话题${why}`
}

/** 视觉这一轮：线索有没有效，和有没有真的说出口，是两件事。 */
function visionDetail(trace: AgentTrace): string {
  if (trace.vision.state === 'short_circuit') return '安全分支提前结束，本轮未执行'
  if (!trace.vision.cue_valid) return '本轮没有可用的视觉线索'
  const cue = trace.vision.cue ? `${trace.vision.channel_label} · ${trace.vision.cue}` : trace.vision.channel_label
  return `线索有效：${cue}${trace.vision.spoken ? ' · 已说出口' : ' · 未说出口'}`
}
</script>

<template>
  <section v-if="trace" class="flow">
    <header class="flow__head">
      <p class="flow__title">多智能体运行轨迹</p>
      <span class="flow__engine">{{ trace.engine === 'graph' ? 'LangGraph' : trace.engine }}</span>
    </header>

    <!-- key 绑定轮次：每轮重新入场，动画只做状态更替，不做流式推送 -->
    <div :key="turn ?? 0" class="xq-fade-up">
      <div v-for="group in groups" :key="group.key" class="flow__group">
        <p class="flow__group-label">{{ group.label }}</p>

        <div v-for="row in group.rows" :key="row.key" class="flow__row" :class="`is-${row.state}`">
          <div class="flow__row-head">
            <i class="flow__dot" :class="{ 'xq-pulse': row.state === 'ran' }" />
            <span class="flow__name">{{ row.name }}</span>
            <span class="flow__badge">{{ STATE_BADGES[row.state] }}</span>
          </div>
          <p class="flow__detail">{{ row.detail }}</p>
          <p v-if="row.note" class="flow__note">{{ row.note }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.flow {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
  padding: var(--xq-sp-4);
  border: var(--xq-border-pixel);
  border-radius: var(--xq-radius-m);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
}

.flow__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--xq-sp-2);
}
.flow__title {
  font-family: var(--xq-font-pixel);
  font-weight: 700;
  font-size: var(--xq-fs-base);
  color: var(--xq-text);
}
.flow__engine {
  flex: none;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: var(--xq-fs-xs);
  background: var(--xq-primary-soft);
  color: var(--xq-primary-deep);
}

.flow__group {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-2);
  padding-top: var(--xq-sp-3);
  border-top: var(--xq-border-pixel-thin);
}
.flow__group:first-child {
  padding-top: 0;
  border-top: none;
}
.flow__group-label {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  letter-spacing: 0.02em;
}

.flow__row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--xq-sp-2) var(--xq-sp-3);
  border-radius: var(--xq-radius-s);
  background: var(--xq-surface-2);
  border-left: 3px solid transparent;
}
.flow__row-head {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-2);
}
.flow__dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}
.flow__name {
  flex: 1;
  min-width: 0;
  font-size: var(--xq-fs-sm);
  font-weight: 600;
  color: var(--xq-text);
}
.flow__badge {
  flex: none;
  border-radius: 999px;
  padding: 1px 8px;
  font-size: var(--xq-fs-xs);
  background: rgba(62, 47, 38, 0.06);
  color: var(--xq-text-2);
}
.flow__detail {
  padding-left: 16px;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text);
  line-height: 1.5;
}
.flow__note {
  padding-left: 16px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: var(--xq-text-2);
  word-break: break-all;
}

/* 已调用：主色 */
.flow__row.is-ran {
  border-left-color: var(--xq-primary);
  color: var(--xq-primary);
}
.flow__row.is-ran .flow__badge {
  background: var(--xq-primary-soft);
  color: var(--xq-primary-deep);
}

/* 跳过：中性灰，一眼看出"这一步没花模型调用" */
.flow__row.is-skipped {
  border-left-color: var(--xq-text-disabled);
  color: var(--xq-text-disabled);
}
.flow__row.is-skipped .flow__name,
.flow__row.is-skipped .flow__detail {
  color: var(--xq-text-2);
}

/* 安全分支提前结束：警示色 */
.flow__row.is-short_circuit {
  border-left-color: var(--xq-hotline);
  color: var(--xq-hotline);
}
.flow__row.is-short_circuit .flow__badge {
  background: rgba(255, 107, 74, 0.14);
  color: var(--xq-hotline);
}

/* 该引擎不提供：虚线边，明确区别于"跑过但没调用" */
.flow__row.is-unavailable {
  border-left-style: dashed;
  border-left-color: var(--xq-text-disabled);
  color: var(--xq-text-disabled);
}
.flow__row.is-unavailable .flow__name,
.flow__row.is-unavailable .flow__detail {
  color: var(--xq-text-2);
}
</style>
