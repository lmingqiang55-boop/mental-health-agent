<script setup lang="ts">
import { ref } from 'vue'
import PxModal from '@/components/base/PxModal.vue'
import PxButton from '@/components/base/PxButton.vue'

const open = ref(false)

const HOTLINE = '12356'
const CAMPUS = { name: '校内心理老师', phone: '请联系班主任或心理辅导室' }

function tel(phone: string) {
  const digits = phone.replace(/[^\d]/g, '')
  if (digits) window.location.href = `tel:${digits}`
}
</script>

<template>
  <div>
    <button class="xh-fab" type="button" aria-label="紧急求助" @click="open = true">
      <span class="xh-fab__icon">✚</span>
      <span class="xh-fab__text">求助</span>
    </button>

    <PxModal :open="open" title="紧急求助" width="420px" @close="open = false">
      <div class="xh-hot">
        <p class="xh-hot__lead">
          如果你此刻感到非常难受、难以独自应对，请马上联系下面的人。你并不孤单。
        </p>

        <div class="xh-hot__card">
          <div class="xh-hot__name">全国心理援助热线</div>
          <a class="xh-hot__num" href="tel:12356">12356</a>
          <div class="xh-hot__desc">24 小时免费，可匿名拨打</div>
        </div>

        <div class="xh-hot__card">
          <div class="xh-hot__name">{{ CAMPUS.name }}</div>
          <div class="xh-hot__num xh-hot__num--sm">{{ CAMPUS.phone }}</div>
          <div class="xh-hot__desc">上学时段可前往心理咨询室</div>
        </div>

        <p class="xh-hot__note">
          紧急危险情况请立即拨打 <b>110 / 120</b>，或告诉身边的家长、老师。
        </p>
      </div>

      <template #footer>
        <PxButton variant="ghost" @click="open = false">先关掉</PxButton>
        <PxButton variant="hotline" @click="tel(HOTLINE)">拨打 12356</PxButton>
      </template>
    </PxModal>
  </div>
</template>

<style scoped>
.xh-fab {
  position: fixed;
  right: var(--xq-sp-4);
  bottom: calc(var(--xq-tabbar-h) + var(--xq-sp-4) + env(safe-area-inset-bottom, 0px));
  z-index: 900;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
  width: 60px;
  height: 60px;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: linear-gradient(135deg, #ff8a6b 0%, var(--xq-hotline) 100%);
  color: #fff;
  box-shadow: 0 10px 24px rgba(255, 107, 74, 0.4);
  transition: transform var(--xq-dur-fast) var(--xq-ease-base),
    box-shadow var(--xq-dur-fast) var(--xq-ease-base);
}
.xh-fab:active {
  transform: scale(0.92);
}
.xh-fab__icon {
  font-size: 16px;
  line-height: 1;
}
.xh-fab__text {
  font-family: var(--xq-font-pixel);
  font-weight: 600;
  font-size: 12px;
  margin-top: 2px;
}
.xh-hot__lead {
  line-height: 1.7;
  margin-bottom: var(--xq-sp-4);
}
.xh-hot__card {
  border-radius: var(--xq-radius-m);
  padding: var(--xq-sp-3) var(--xq-sp-4);
  margin-bottom: var(--xq-sp-3);
  background: var(--xq-surface-2);
}
.xh-hot__name {
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
}
.xh-hot__num {
  display: block;
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-2xl);
  color: var(--xq-hotline);
  margin: 2px 0;
}
.xh-hot__num--sm {
  font-size: var(--xq-fs-lg);
  color: var(--xq-text);
}
.xh-hot__desc {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.xh-hot__note {
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
  line-height: 1.7;
  margin-top: var(--xq-sp-3);
}
@media (min-width: 1024px) {
  .xh-fab {
    bottom: var(--xq-sp-6);
  }
}
</style>
