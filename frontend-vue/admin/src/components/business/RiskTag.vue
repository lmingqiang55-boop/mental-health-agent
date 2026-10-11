<template>
  <el-tag :type="RISK_MAP[level].type" effect="light" round>{{ RISK_MAP[level].text }}</el-tag>
</template>

<script setup lang="ts">
import { RISK_MAP } from '@/utils/format'
import type { RiskLevel } from '@/types'

defineProps<{ level: RiskLevel }>()
</script>
