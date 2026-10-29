<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">创建测评任务</h2>
        <p class="page-subtitle">选择量表与目标范围，设置时间与匿名策略后发布</p>
      </div>
      <el-button :icon="Back" @click="$router.push('/assessment/tasks')">返回列表</el-button>
    </div>

    <div class="xq-card">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px" style="max-width: 720px">
        <el-form-item label="任务名称" prop="title">
          <el-input v-model="form.title" placeholder="如：2026 秋季新生心理健康普测" maxlength="40" show-word-limit />
        </el-form-item>

        <el-form-item label="测评类型" prop="scale">
          <el-select v-model="form.scale" style="width: 100%">
            <el-option v-for="(label, k) in SCALE_MAP" :key="k" :label="label" :value="k" />
          </el-select>
          <div class="cell-sub" style="margin-top: 6px">
            量表题目与计分规则由后端提供；对话式测评为现有能力。
          </div>
        </el-form-item>

        <el-form-item label="目标范围" prop="targets">
          <el-select v-model="form.targets" multiple collapse-tags collapse-tags-tooltip placeholder="选择年级 / 班级" style="width: 100%">
            <el-option-group v-for="g in SCOPE_GROUPS" :key="g.label" :label="g.label">
              <el-option v-for="o in g.options" :key="o.value" :label="o.label" :value="o.value" />
            </el-option-group>
          </el-select>
          <div class="cell-sub" style="margin-top: 6px">预计参与 {{ estimatedStudents }} 人（范围口径待组织架构接口对齐）</div>
        </el-form-item>

        <el-form-item label="起止时间" prop="range">
          <el-date-picker
            v-model="form.range"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="截止时间"
            value-format="YYYY-MM-DD HH:mm"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="参与策略">
          <el-space wrap>
            <el-checkbox v-model="form.anonymous">匿名测评（不关联学生身份）</el-checkbox>
            <el-checkbox v-model="form.consentRequired">需监护人知情同意</el-checkbox>
          </el-space>
        </el-form-item>

        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="3" maxlength="120" show-word-limit placeholder="如：对上一轮中高风险学生开展复评" />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="saving" @click="submit('published')">保存并发布</el-button>
          <el-button :disabled="saving" @click="submit('draft')">存为草稿</el-button>
        </el-form-item>
      </el-form>
    </div>

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      style="margin-top: 16px"
      title="演示数据说明：当前任务实体由前端 mock 打底"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Back } from '@element-plus/icons-vue'
import { taskApi } from '@/api'
import { SCALE_MAP } from '@/utils/format'
import type { ScaleType, TaskStatus } from '@/types/admin'

const router = useRouter()
const formRef = ref<FormInstance>()
const saving = ref(false)

/** 演示用范围选项：正式版应由组织架构接口返回（见 /system 组织架构） */
const SCOPE_GROUPS = [
  { label: '年级', options: ['初一年级', '初二年级', '初三年级', '高一年级', '高二年级'].map((v) => ({ label: v, value: v })) },
  { label: '班级', options: ['初一1班', '初一2班', '初二1班', '初二3班', '初三1班', '初三4班', '高一2班', '高二5班'].map((v) => ({ label: v, value: v })) },
]

const form = reactive({
  title: '',
  scale: 'phq9' as ScaleType,
  targets: [] as string[],
  range: [] as string[],
  anonymous: false,
  consentRequired: true,
  remark: '',
})

const rules: FormRules = {
  title: [{ required: true, message: '请填写任务名称', trigger: 'blur' }],
  scale: [{ required: true, message: '请选择测评类型', trigger: 'change' }],
  targets: [{ type: 'array', required: true, min: 1, message: '请至少选择一个目标范围', trigger: 'change' }],
  range: [{ type: 'array', required: true, message: '请设置起止时间', trigger: 'change' }],
}

const estimatedStudents = computed(() =>
  form.targets.reduce((sum, t) => sum + (t.endsWith('年级') ? 6 : 3), 0),
)

async function submit(status: TaskStatus) {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    await taskApi.create({
      title: form.title,
      scale: form.scale,
      targetScope: form.targets.join('、'),
      startAt: form.range[0] ?? null,
      deadline: form.range[1] ?? null,
      status,
      anonymous: form.anonymous,
      consentRequired: form.consentRequired,
      total: estimatedStudents.value,
      creator: '心理中心',
      remark: form.remark,
    })
    ElMessage.success(status === 'draft' ? '已存为草稿' : '任务已发布')
    router.push('/assessment/tasks')
  } finally {
    saving.value = false
  }
}
</script>
