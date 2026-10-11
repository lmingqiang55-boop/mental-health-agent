<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <span class="brand-logo">晴</span>
        <div>
          <h1 class="brand-title">心晴 · 管理端</h1>
          <p class="brand-sub">过程可解释的抑郁症多模态测评治愈和管理一体化平台</p>
        </div>
      </div>

      <p class="section-label">选择工作角色（当前后端无鉴权，身份用于角色差异化演示）</p>
      <div class="role-grid">
        <div
          v-for="r in ROLES"
          :key="r.key"
          class="role-card"
          :class="{ active: selected === r.key }"
          @click="selected = r.key"
        >
          <div class="role-name">{{ r.name }}</div>
          <div class="role-desc">{{ r.desc }}</div>
          <div class="role-scope">{{ r.scopeText }}</div>
        </div>
      </div>

      <el-input
        v-model="name"
        placeholder="显示名称（可留空，默认用角色名）"
        size="large"
        class="name-input"
        @keyup.enter="enter"
      />
      <el-button type="primary" size="large" class="enter-btn" :disabled="!selected" @click="enter">
        进入工作台
      </el-button>

      <p class="login-note">敏感页面操作将记录审计日志（待后端支持）；原始聊天与音视频不在管理端展示。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ROLES, useUserStore, type RoleKey } from '@/stores/user'

const router = useRouter()
const user = useUserStore()
const selected = ref<RoleKey | null>('psych')
const name = ref('')

function enter() {
  if (!selected.value) return
  user.login(selected.value, name.value.trim())
  router.push('/dashboard')
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(600px 300px at 15% 10%, var(--xq-primary-lighter), transparent),
    radial-gradient(500px 260px at 85% 90%, #ffe9d6, transparent),
    var(--xq-bg);
  padding: 24px;
}

.login-card {
  width: 560px;
  max-width: 100%;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 8px 40px rgba(240, 131, 60, 0.12);
  padding: 32px 36px;
}

.login-brand { display: flex; gap: 14px; align-items: center; margin-bottom: 24px; }
.brand-logo {
  width: 48px; height: 48px; border-radius: 14px;
  background: linear-gradient(135deg, var(--xq-primary), #f6a86b);
  color: #fff; font-size: 22px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.brand-title { margin: 0; font-size: 20px; }
.brand-sub { margin: 4px 0 0; font-size: 12px; color: var(--xq-text-secondary); }

.section-label { font-size: 13px; color: var(--xq-text-secondary); margin: 0 0 12px; }

.role-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 20px;
}

.role-card {
  border: 1.5px solid var(--xq-border);
  border-radius: 10px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.role-card:hover { border-color: var(--xq-primary); }
.role-card.active {
  border-color: var(--xq-primary);
  background: var(--xq-primary-lighter);
  box-shadow: 0 2px 10px rgba(240, 131, 60, 0.15);
}

.role-name { font-weight: 600; margin-bottom: 4px; }
.role-desc { font-size: 12px; color: var(--xq-text-secondary); }
.role-scope { font-size: 12px; color: var(--xq-primary-deep); margin-top: 6px; }

.name-input { margin-bottom: 14px; }
.enter-btn { width: 100%; }

.login-note {
  margin: 16px 0 0;
  font-size: 12px;
  color: var(--xq-text-secondary);
  text-align: center;
}
</style>
