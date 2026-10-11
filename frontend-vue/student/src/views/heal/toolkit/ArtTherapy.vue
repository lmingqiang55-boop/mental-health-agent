<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxInput from '@/components/base/PxInput.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import { uid } from '@/utils/id'
import { fmtDateTime } from '@/utils/format'
import { readLS, writeLS, STORAGE_KEYS } from '@/utils/storage'
import { toastSuccess, toastWarn } from '@/utils/toast'

interface ArtWork {
  id: string
  dataUrl: string
  createdAt: string
}

const PALETTE = ['#8b7fd4', '#e86a5e', '#f2b84b', '#5fae8c', '#4d8fd6', '#2a2438', '#ffffff']
const SIZES = [4, 10, 20]
const MAX_WORKS = 6
/** 缩略图最长边，控制 localStorage 占用。 */
const THUMB_MAX = 360

const canvas = ref<HTMLCanvasElement | null>(null)
const color = ref(PALETTE[0])
const size = ref(SIZES[1])

const works = ref<ArtWork[]>(readLS<ArtWork[]>(STORAGE_KEYS.artWorks, []))
const title = ref('')

let ctx: CanvasRenderingContext2D | null = null
let drawing = false
const undoStack: ImageData[] = []

function fillBackground() {
  if (!ctx || !canvas.value) return
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.value.width, canvas.value.height)
}

function setup() {
  const el = canvas.value
  if (!el) return
  ctx = el.getContext('2d')
  if (!ctx) return
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  fillBackground()
  pushUndo()
}

function pushUndo() {
  if (!ctx || !canvas.value) return
  undoStack.push(ctx.getImageData(0, 0, canvas.value.width, canvas.value.height))
  if (undoStack.length > 8) undoStack.shift()
}

function pointOf(e: PointerEvent): { x: number; y: number } | null {
  const el = canvas.value
  if (!el) return null
  const rect = el.getBoundingClientRect()
  return {
    x: (e.clientX - rect.left) * (el.width / rect.width),
    y: (e.clientY - rect.top) * (el.height / rect.height),
  }
}

function start(e: PointerEvent) {
  if (!ctx) return
  drawing = true
  canvas.value?.setPointerCapture(e.pointerId)
  const p = pointOf(e)
  if (!p) return
  ctx.beginPath()
  ctx.moveTo(p.x, p.y)
  ctx.lineTo(p.x, p.y)
  ctx.strokeStyle = color.value
  ctx.lineWidth = size.value
  ctx.stroke()
}

function move(e: PointerEvent) {
  if (!drawing || !ctx) return
  const p = pointOf(e)
  if (!p) return
  ctx.lineTo(p.x, p.y)
  ctx.stroke()
}

function end(e: PointerEvent) {
  if (!drawing) return
  drawing = false
  canvas.value?.releasePointerCapture(e.pointerId)
  pushUndo()
}

function undo() {
  if (!ctx || !canvas.value || undoStack.length <= 1) {
    toastWarn('没有可以撤销的笔迹了')
    return
  }
  undoStack.pop()
  const last = undoStack[undoStack.length - 1]
  if (last) ctx.putImageData(last, 0, 0)
}

function clearAll() {
  fillBackground()
  undoStack.length = 0
  pushUndo()
}

function makeThumb(source: HTMLCanvasElement): string {
  const ratio = Math.min(1, THUMB_MAX / Math.max(source.width, source.height))
  const c = document.createElement('canvas')
  c.width = Math.round(source.width * ratio)
  c.height = Math.round(source.height * ratio)
  const cctx = c.getContext('2d')
  if (cctx) {
    cctx.fillStyle = '#ffffff'
    cctx.fillRect(0, 0, c.width, c.height)
    cctx.drawImage(source, 0, 0, c.width, c.height)
  }
  return c.toDataURL('image/jpeg', 0.72)
}

function save() {
  const el = canvas.value
  if (!el) return
  const work: ArtWork = {
    id: uid('art'),
    dataUrl: makeThumb(el),
    createdAt: new Date().toISOString(),
  }
  const next = [work, ...works.value].slice(0, MAX_WORKS)
  works.value = next
  writeLS(STORAGE_KEYS.artWorks, next)
  title.value = ''
  toastSuccess('把这一幅收好了')
}

function remove(id: string) {
  const next = works.value.filter((w) => w.id !== id)
  works.value = next
  writeLS(STORAGE_KEYS.artWorks, next)
}

onMounted(setup)
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="艺术表达" sub="随手涂鸦，让情绪有另一种出口" back />

    <PxCard title="画布">
      <div class="at__canvas-wrap">
        <canvas
          ref="canvas"
          class="at__canvas"
          width="900"
          height="600"
          @pointerdown="start"
          @pointermove="move"
          @pointerup="end"
          @pointercancel="end"
        />
      </div>

      <div class="at__tools">
        <div class="at__palette">
          <button
            v-for="c in PALETTE"
            :key="c"
            type="button"
            class="at__swatch"
            :class="{ 'is-on': color === c }"
            :style="{ background: c }"
            :title="c === '#ffffff' ? '橡皮（白色）' : c"
            @click="color = c"
          />
        </div>
        <div class="at__sizes">
          <button
            v-for="s in SIZES"
            :key="s"
            type="button"
            class="at__size"
            :class="{ 'is-on': size === s }"
            @click="size = s"
          >
            <span class="at__size-dot" :style="{ width: `${s}px`, height: `${s}px` }" />
          </button>
        </div>
      </div>

      <div class="at__actions">
        <PxButton variant="ghost" @click="undo">撤销</PxButton>
        <PxButton variant="ghost" @click="clearAll">清空</PxButton>
      </div>
    </PxCard>

    <PxCard class="at__block" title="收好这一幅">
      <PxInput v-model="title" placeholder="给这幅画起个名字（选填）" :maxlength="30" />
      <div class="at__save">
        <PxButton block @click="save">保存到我的作品</PxButton>
      </div>
      <p class="xq-muted at__hint">只保存在这台设备上，最多保留 {{ MAX_WORKS }} 幅。</p>
    </PxCard>

    <h2 class="xq-section-title">我的作品</h2>
    <PxEmpty v-if="!works.length" text="还没有作品，随便画几笔也算" />
    <div v-else class="at__gallery">
      <figure v-for="w in works" :key="w.id" class="at__work">
        <img :src="w.dataUrl" :alt="`作品 ${fmtDateTime(w.createdAt)}`" />
        <figcaption class="at__work-cap">
          <span>{{ fmtDateTime(w.createdAt) }}</span>
          <button type="button" class="at__work-del" @click="remove(w.id)">删除</button>
        </figcaption>
      </figure>
    </div>

    <p class="xq-disclaimer">
      画画不需要好看。颜色、线条、涂满的色块，都是情绪在说话。
    </p>
  </div>
</template>

<style scoped>
.at__canvas-wrap {
  border: var(--xq-border-pixel-thin);
  background: #fff;
  overflow: hidden;
}
.at__canvas {
  display: block;
  width: 100%;
  height: auto;
  aspect-ratio: 3 / 2;
  touch-action: none;
  cursor: crosshair;
}
.at__tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--xq-sp-3);
  margin-top: var(--xq-sp-3);
}
.at__palette {
  display: flex;
  gap: 6px;
}
.at__swatch {
  width: 28px;
  height: 28px;
  border: 2px solid var(--xq-text-disabled);
}
.at__swatch.is-on {
  border-color: var(--xq-text);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.at__sizes {
  display: flex;
  gap: 6px;
}
.at__size {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--xq-text-disabled);
  background: var(--xq-surface);
}
.at__size.is-on {
  border-color: var(--xq-text);
  background: var(--xq-primary-soft);
}
.at__size-dot {
  display: block;
  border-radius: 50%;
  background: var(--xq-text);
}
.at__actions {
  display: flex;
  gap: var(--xq-sp-2);
  margin-top: var(--xq-sp-3);
}
.at__block {
  margin-top: var(--xq-sp-3);
}
.at__save {
  margin-top: var(--xq-sp-3);
}
.at__hint {
  margin-top: var(--xq-sp-2);
}
.at__gallery {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--xq-sp-3);
}
.at__work {
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.at__work img {
  display: block;
  width: 100%;
  height: auto;
}
.at__work-cap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--xq-sp-2);
  padding: 6px 8px;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  border-top: 2px solid var(--xq-text-disabled);
}
.at__work-del {
  color: var(--xq-danger);
  font-size: var(--xq-fs-xs);
}
@media (min-width: 640px) {
  .at__gallery {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
