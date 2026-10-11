<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxInput from '@/components/base/PxInput.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import { useStudentStore } from '@/stores/student'
import type { EmergencyContact } from '@/api/types'
import { toastError, toastSuccess, toastWarn } from '@/utils/toast'

const student = useStudentStore()

const name = ref('')
const relation = ref('')
const phone = ref('')
const adding = ref(false)

onMounted(() => {
  void student.loadContacts()
})

async function add() {
  const n = name.value.trim()
  const p = phone.value.trim()
  if (!n || !p) {
    toastWarn('请填写称呼和电话')
    return
  }
  if (!/^[\d\-+\s]{3,20}$/.test(p)) {
    toastWarn('电话格式看起来不太对')
    return
  }
  adding.value = true
  try {
    await student.addContact({ name: n, relation: relation.value.trim(), phone: p })
    name.value = ''
    relation.value = ''
    phone.value = ''
    toastSuccess('已添加联系人')
  } catch {
    toastError('添加失败，请稍后再试')
  } finally {
    adding.value = false
  }
}

async function remove(c: EmergencyContact) {
  try {
    await student.removeContact(c.id)
    toastSuccess('已删除')
  } catch {
    toastError('删除失败，请稍后再试')
  }
}

function tel(raw: string) {
  const digits = raw.replace(/[^\d]/g, '')
  if (digits) window.location.href = `tel:${digits}`
}
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="紧急联系人" sub="难受的时候，可以找到的人" back />

    <PxCard tone="primary" title="为什么需要">
      <p class="ct__lead">
        写下你信任、也愿意帮助你的成年人。当情绪很糟时，有他们在，你会更容易开口求助。
        这些联系方式会安全保存到服务器，之后重新打开也能看到。
      </p>
    </PxCard>

    <PxCard class="ct__block" title="添加联系人">
      <div class="ct__form">
        <PxInput v-model="name" label="称呼" placeholder="例如：妈妈 / 班主任王老师" :maxlength="20" />
        <PxInput v-model="relation" label="关系（选填）" placeholder="例如：家人 / 老师" :maxlength="20" />
        <PxInput v-model="phone" label="电话" placeholder="手机或座机号码" :maxlength="20" />
      </div>
      <div class="ct__submit">
        <PxButton block :loading="adding" @click="add">添加</PxButton>
      </div>
    </PxCard>

    <h2 class="xq-section-title">我的联系人</h2>
    <PxEmpty v-if="!student.contacts.length" text="还没有添加联系人" />
    <div v-else class="ct__list">
      <PxCard v-for="c in student.contacts" :key="c.id">
        <div class="ct__item">
          <div class="ct__item-info">
            <p class="ct__item-name">
              {{ c.name }}
              <span v-if="c.relation" class="ct__item-relation">{{ c.relation }}</span>
            </p>
            <p class="ct__item-phone">{{ c.phone }}</p>
          </div>
          <div class="ct__item-actions">
            <PxButton size="sm" variant="secondary" @click="tel(c.phone)">拨打</PxButton>
            <PxButton size="sm" variant="ghost" @click="remove(c)">删除</PxButton>
          </div>
        </div>
      </PxCard>
    </div>

    <PxCard class="ct__block" tone="warn" title="全国心理援助热线">
      <div class="ct__hotline">
        <a class="ct__hotline-num" href="tel:12356">12356</a>
        <span class="xq-muted">24 小时免费，可匿名拨打</span>
      </div>
    </PxCard>

    <p class="xq-disclaimer">
      紧急危险情况请立即拨打 110 / 120，并尽量待在人多的安全地方。
    </p>
  </div>
</template>

<style scoped>
.ct__lead {
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
}
.ct__block {
  margin-top: var(--xq-sp-3);
}
.ct__form {
  display: grid;
  gap: var(--xq-sp-3);
}
.ct__submit {
  margin-top: var(--xq-sp-4);
}
.ct__list {
  display: grid;
  gap: var(--xq-sp-3);
}
.ct__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--xq-sp-3);
}
.ct__item-info {
  min-width: 0;
}
.ct__item-name {
  font-size: var(--xq-fs-base);
}
.ct__item-relation {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  margin-left: 6px;
}
.ct__item-phone {
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
  margin-top: 2px;
}
.ct__item-actions {
  display: flex;
  gap: var(--xq-sp-2);
  flex: 0 0 auto;
}
.ct__hotline {
  display: flex;
  align-items: baseline;
  gap: var(--xq-sp-3);
}
.ct__hotline-num {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-2xl);
  color: var(--xq-hotline);
}
</style>
