<template>
  <el-popover placement="bottom-end" :width="340" trigger="click" popper-class="notify-popper">
    <template #reference>
      <div class="bell" :title="`待办提醒：${notify.total} 项`">
        <el-badge :value="notify.total" :hidden="notify.total === 0" :max="99">
          <el-icon :size="19"><Bell /></el-icon>
        </el-badge>
      </div>
    </template>

    <div class="notify-panel">
      <div class="notify-head">
        <span class="notify-title">待办提醒</span>
        <el-button text size="small" :icon="Refresh" :loading="notify.loading" @click="notify.refresh()">刷新</el-button>
      </div>

      <div v-loading="notify.loading" class="notify-body">
        <template v-if="notify.todos.length">
          <div
            v-for="t in notify.todos"
            :key="t.id"
            class="todo-row"
            @click="go(t)"
          >
            <span class="todo-dot" :class="t.level" />
            <div class="todo-main">
              <div class="todo-line">
                <span class="todo-title">{{ t.title }}</span>
                <span class="todo-count">{{ t.count }}</span>
              </div>
              <div class="todo-desc">{{ t.desc }}</div>
            </div>
            <el-icon class="todo-arrow"><ArrowRight /></el-icon>
          </div>
        </template>
        <el-empty v-else-if="!notify.loading" description="暂无待办，一切正常" :image-size="60" />
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Bell, Refresh } from '@element-plus/icons-vue'
import { useNotifyStore, type TodoItem } from '@/stores/notify'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const notify = useNotifyStore()
const user = useUserStore()

function go(t: TodoItem) {
  router.push(t.to)
}

onMounted(() => notify.refresh())
// 切换角色后待办范围不同，重新拉取
watch(() => user.role, () => notify.refresh())
</script>

<style scoped>
.bell {
  display: flex;
  align-items: center;
  cursor: pointer;
  color: var(--xq-text-secondary);
  padding: 4px;
}
.bell:hover { color: var(--xq-primary); }

.notify-panel { margin: -6px -4px; }
.notify-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--xq-border);
}
.notify-title { font-weight: 600; font-size: 14px; }
.notify-body { max-height: 320px; overflow-y: auto; margin-top: 4px; }

.todo-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 6px;
  border-radius: 8px;
  cursor: pointer;
}
.todo-row:hover { background: var(--xq-primary-lighter); }

.todo-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.todo-dot.high { background: var(--xq-risk-high); }
.todo-dot.medium { background: var(--xq-risk-medium); }
.todo-dot.normal { background: var(--xq-primary); }

.todo-main { flex: 1; min-width: 0; }
.todo-line { display: flex; align-items: center; justify-content: space-between; }
.todo-title { font-size: 13px; font-weight: 500; }
.todo-count {
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: var(--xq-risk-high);
  border-radius: 10px;
  padding: 0 8px;
  line-height: 18px;
}
.todo-desc { font-size: 12px; color: var(--xq-text-secondary); margin-top: 2px; }
.todo-arrow { color: var(--xq-text-secondary); flex-shrink: 0; }
</style>
