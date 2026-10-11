<script setup lang="ts">
import { computed, ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'

type PartKey = 'head' | 'shoulder' | 'arm' | 'chest' | 'belly' | 'leg' | 'feet'

interface BodyPart {
  key: PartKey
  name: string
  body: string
}

const PARTS: BodyPart[] = [
  { key: 'head', name: '头顶与面部', body: '把注意力放到头顶，感受那里有没有发紧。放松额头、眼睛，最后松开咬紧的下巴。' },
  { key: 'shoulder', name: '肩膀与颈部', body: '吸气时感受肩膀轻轻抬起，呼气时让它掉下来。脖子可以慢慢地左右转一转。' },
  { key: 'arm', name: '手臂与手掌', body: '从肩膀到手肘，再到手腕和指尖。先轻轻握一下拳，再慢慢完全松开。' },
  { key: 'chest', name: '胸口与呼吸', body: '感受胸口随着呼吸一起一伏。如果有点发紧，试着把呼气拉得比吸气长一点。' },
  { key: 'belly', name: '腹部', body: '把手轻轻放在肚子上，感受它一鼓一收。不用刻意用力，只是观察。' },
  { key: 'leg', name: '大腿与小腿', body: '感受腿和椅子、床接触的重量。可以先绷紧几秒，再一下子放松，体会那个差别。' },
  { key: 'feet', name: '双脚', body: '把注意力放到脚掌，感受它与地面接触。脚趾轻轻动一动，再安静地放下。' },
]

const activeIdx = ref(0)
const visited = ref<Set<PartKey>>(new Set())
const finished = ref(false)

const active = computed(() => PARTS[activeIdx.value])

/** 每个部位是否被当前高亮（用于 SVG 上色）。 */
function isOn(key: PartKey) {
  return active.value.key === key
}

function select(key: PartKey) {
  const i = PARTS.findIndex((p) => p.key === key)
  if (i >= 0) activeIdx.value = i
}

function markVisited() {
  visited.value = new Set(visited.value).add(active.value.key)
}

function next() {
  markVisited()
  if (activeIdx.value < PARTS.length - 1) {
    activeIdx.value += 1
  } else {
    finished.value = true
  }
}

function prev() {
  finished.value = false
  if (activeIdx.value > 0) activeIdx.value -= 1
}

function restart() {
  activeIdx.value = 0
  visited.value = new Set()
  finished.value = false
}
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="身体觉察" sub="从头到脚扫描一遍，松开紧绷的地方" back />

    <PxCard title="轻轻碰一下想感受的部位">
      <div class="bs__stage">
        <svg class="bs__svg" viewBox="0 0 200 360" role="img" aria-label="身体示意图">
          <ellipse class="bs__part" :class="{ 'is-on': isOn('head'), 'is-visited': visited.has('head') }"
            cx="100" cy="46" rx="26" ry="30" @click="select('head')" />
          <rect class="bs__part" :class="{ 'is-on': isOn('shoulder'), 'is-visited': visited.has('shoulder') }"
            x="56" y="80" width="88" height="26" @click="select('shoulder')" />
          <rect class="bs__part" :class="{ 'is-on': isOn('chest'), 'is-visited': visited.has('chest') }"
            x="66" y="106" width="68" height="58" @click="select('chest')" />
          <rect class="bs__part" :class="{ 'is-on': isOn('belly'), 'is-visited': visited.has('belly') }"
            x="68" y="164" width="64" height="50" @click="select('belly')" />
          <rect class="bs__part" :class="{ 'is-on': isOn('arm'), 'is-visited': visited.has('arm') }"
            x="36" y="86" width="18" height="100" rx="8" @click="select('arm')" />
          <rect class="bs__part" :class="{ 'is-on': isOn('arm'), 'is-visited': visited.has('arm') }"
            x="146" y="86" width="18" height="100" rx="8" @click="select('arm')" />
          <rect class="bs__part" :class="{ 'is-on': isOn('leg'), 'is-visited': visited.has('leg') }"
            x="72" y="214" width="24" height="108" rx="8" @click="select('leg')" />
          <rect class="bs__part" :class="{ 'is-on': isOn('leg'), 'is-visited': visited.has('leg') }"
            x="104" y="214" width="24" height="108" rx="8" @click="select('leg')" />
          <rect class="bs__part" :class="{ 'is-on': isOn('feet'), 'is-visited': visited.has('feet') }"
            x="70" y="324" width="30" height="16" rx="6" @click="select('feet')" />
          <rect class="bs__part" :class="{ 'is-on': isOn('feet'), 'is-visited': visited.has('feet') }"
            x="100" y="324" width="30" height="16" rx="6" @click="select('feet')" />
        </svg>

        <div class="bs__guide">
          <p class="bs__guide-no">{{ activeIdx + 1 }} / {{ PARTS.length }}</p>
          <h3 class="bs__guide-title">{{ active.name }}</h3>
          <p class="bs__guide-body">{{ active.body }}</p>
        </div>
      </div>

      <div v-if="!finished" class="bs__nav">
        <PxButton variant="ghost" :disabled="activeIdx === 0" @click="prev">上一个</PxButton>
        <PxButton @click="next">
          {{ activeIdx === PARTS.length - 1 ? '完成扫描' : '下一个部位' }}
        </PxButton>
      </div>
      <div v-else class="bs__done">
        <p class="bs__done-text">扫描完成。现在留意一下，身体比刚才松了哪些？</p>
        <PxButton block variant="secondary" @click="restart">再来一遍</PxButton>
      </div>
    </PxCard>

    <PxCard class="bs__block" title="已感受的部位">
      <ul class="bs__list">
        <li
          v-for="(p, i) in PARTS"
          :key="p.key"
          class="bs__list-item"
          :class="{ 'is-on': i === activeIdx }"
          @click="select(p.key)"
        >
          <span class="bs__list-icon">{{ visited.has(p.key) ? '✓' : '·' }}</span>
          {{ p.name }}
        </li>
      </ul>
    </PxCard>

    <p class="xq-disclaimer">
      扫描过程中睡着也没关系，那说明身体正需要休息。若某个部位有持续疼痛，请及时就医。
    </p>
  </div>
</template>

<style scoped>
.bs__stage {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--xq-sp-4);
}
.bs__svg {
  width: 100%;
  max-width: 220px;
  margin: 0 auto;
  height: auto;
}
.bs__part {
  fill: var(--xq-surface-2);
  stroke: var(--xq-text);
  stroke-width: 2.5;
  cursor: pointer;
  transition: fill var(--xq-dur-base) var(--xq-ease-base);
}
.bs__part.is-visited {
  fill: var(--xq-primary-soft);
}
.bs__part.is-on {
  fill: var(--xq-primary);
}
.bs__guide {
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface-2);
  padding: var(--xq-sp-4);
}
.bs__guide-no {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.bs__guide-title {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-lg);
  margin: 4px 0 var(--xq-sp-2);
}
.bs__guide-body {
  font-size: var(--xq-fs-sm);
  line-height: 1.8;
}
.bs__nav {
  display: flex;
  justify-content: space-between;
  gap: var(--xq-sp-2);
  margin-top: var(--xq-sp-4);
}
.bs__done {
  margin-top: var(--xq-sp-4);
}
.bs__done-text {
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
  margin-bottom: var(--xq-sp-3);
}
.bs__block {
  margin-top: var(--xq-sp-3);
}
.bs__list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--xq-sp-2);
}
.bs__list-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  padding: 8px 10px;
  cursor: pointer;
}
.bs__list-item.is-on {
  color: var(--xq-text);
  background: var(--xq-primary-soft);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.bs__list-icon {
  color: var(--xq-star);
}
@media (min-width: 640px) {
  .bs__stage {
    grid-template-columns: 220px 1fr;
    align-items: center;
  }
}
</style>
