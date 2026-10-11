<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxSwitch from '@/components/base/PxSwitch.vue'
import PxModal from '@/components/base/PxModal.vue'
import { useUiStore } from '@/stores/ui'
import { useStudentStore } from '@/stores/student'
import { toastSuccess } from '@/utils/toast'

const router = useRouter()
const ui = useUiStore()
const student = useStudentStore()

const dark = computed({
  get: () => ui.theme === 'dark',
  set: (v: boolean) => ui.setTheme(v ? 'dark' : 'light'),
})

const resetOpen = ref(false)

function doReset() {
  student.resetIdentity()
  resetOpen.value = false
  toastSuccess('已获得新的匿名身份')
  router.push('/home')
}
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="设置" sub="调整属于你的样子" back />

    <PxCard title="外观">
      <ul class="st__rows">
        <li>
          <div class="st__row-text">
            <p class="st__row-title">夜间模式</p>
            <p class="xq-muted">暗夜蓝紫，睡前看起来更柔和。</p>
          </div>
          <PxSwitch v-model="dark" />
        </li>
      </ul>
    </PxCard>

    <PxCard class="st__block" title="账号与身份">
      <ul class="st__rows">
        <li>
          <div class="st__row-text">
            <p class="st__row-title">当前昵称</p>
            <p class="xq-muted">{{ student.displayName }}</p>
          </div>
          <PxButton size="sm" variant="ghost" @click="router.push('/me/profile')">修改</PxButton>
        </li>
        <li>
          <div class="st__row-text">
            <p class="st__row-title">重置匿名身份</p>
            <p class="xq-muted">获得一个全新的编号，旧记录将无法访问。</p>
          </div>
          <PxButton size="sm" variant="danger" @click="resetOpen = true">重置</PxButton>
        </li>
      </ul>
    </PxCard>

    <PxCard class="st__block" title="数据与隐私">
      <ul class="st__rows">
        <li>
          <div class="st__row-text">
            <p class="st__row-title">隐私与授权</p>
            <p class="xq-muted">相机 / 麦克风 / 数据导出与删除。</p>
          </div>
          <PxButton size="sm" variant="ghost" @click="router.push('/me/privacy')">进入</PxButton>
        </li>
      </ul>
    </PxCard>

    <PxCard class="st__block" title="关于心晴">
      <p class="st__about">
        心晴 · 学生端。这是一个帮助你了解情绪、练习自我照顾的陪伴工具。
      </p>
      <ul class="st__facts">
        <li>
          <span>版本</span>
          <b>学生端 v1.0</b>
        </li>
        <li>
          <span>心理援助热线</span>
          <a href="tel:12356">12356</a>
        </li>
      </ul>
    </PxCard>

    <p class="xq-disclaimer">
      心晴不能替代专业诊断与治疗。若你处于危机中，请立即联系身边的成年人或拨打 110 / 120。
    </p>

    <PxModal :open="resetOpen" title="重置匿名身份？" width="420px" @close="resetOpen = false">
      <p class="st__confirm">
        重置后，你之前的测评报告、日记与打卡都将与新身份断开，无法再找回。你确定要继续吗？
      </p>
      <template #footer>
        <PxButton variant="ghost" @click="resetOpen = false">取消</PxButton>
        <PxButton variant="danger" @click="doReset">确定重置</PxButton>
      </template>
    </PxModal>
  </div>
</template>

<style scoped>
.st__rows {
  display: grid;
  gap: var(--xq-sp-4);
}
.st__rows li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--xq-sp-3);
}
.st__row-text {
  min-width: 0;
}
.st__row-title {
  font-size: var(--xq-fs-base);
  margin-bottom: 2px;
}
.st__block {
  margin-top: var(--xq-sp-3);
}
.st__about {
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
  margin-bottom: var(--xq-sp-3);
}
.st__facts {
  display: grid;
  gap: var(--xq-sp-2);
}
.st__facts li {
  display: flex;
  justify-content: space-between;
  font-size: var(--xq-fs-sm);
  border-bottom: 1px dashed var(--xq-text-disabled);
  padding-bottom: var(--xq-sp-2);
}
.st__facts li:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.st__facts b {
  color: var(--xq-primary-deep);
}
.st__facts a {
  color: var(--xq-hotline);
  font-weight: 700;
}
.st__confirm {
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
}
</style>
