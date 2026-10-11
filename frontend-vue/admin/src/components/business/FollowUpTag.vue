<template>
  <el-tag :type="FOLLOW_UP_MAP[status].type" effect="plain" round>{{ FOLLOW_UP_MAP[status].text }}</el-tag>
</template>

<script setup lang="ts">
import { FOLLOW_UP_MAP } from '@/utils/format'
import type { FollowUpStatus } from '@/types'

defineProps<{ status: FollowUpStatus }>()
</script>
