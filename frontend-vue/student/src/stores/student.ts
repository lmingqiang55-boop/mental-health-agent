import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { ensureStudentRef, resetStudentRef } from '@/utils/studentRef'
import { STORAGE_KEYS, readLS, writeLS } from '@/utils/storage'
import { contactApi, profileApi } from '@/api'
import type { EmergencyContact, SchoolStage } from '@/api/types'

export type { EmergencyContact }

export interface ConsentPrefs {
  allowCamera: boolean
  allowMic: boolean
  allowStorage: boolean
}

const DEFAULT_PREFS: ConsentPrefs = {
  allowCamera: false,
  allowMic: true,
  allowStorage: true,
}

/**
 * 学生身份与档案：student_ref 是唯一真实身份（后端无鉴权）。
 * 昵称 / 学校阶段 / 班级 / 紧急联系人已后端化（按 student_ref 落库）；
 * 昵称在本地留一份缓存用于首屏即时显示，授权偏好仍为本机态。
 */
export const useStudentStore = defineStore('student', () => {
  const studentRef = ref(ensureStudentRef())
  const nickname = ref<string>(readLS<string>(STORAGE_KEYS.nickname, ''))
  const schoolStage = ref<SchoolStage | null>(null)
  const className = ref<string>('')
  const contacts = ref<EmergencyContact[]>([])
  const prefs = ref<ConsentPrefs>(readLS<ConsentPrefs>(STORAGE_KEYS.consentPrefs, DEFAULT_PREFS))
  const profileLoaded = ref(false)

  const displayName = computed(() => nickname.value.trim() || '小晴的朋友')

  watch(nickname, (v) => writeLS(STORAGE_KEYS.nickname, v))
  watch(prefs, (v) => writeLS(STORAGE_KEYS.consentPrefs, v), { deep: true })

  /** 从后端拉取档案；失败时沿用本地昵称缓存，不阻塞页面。 */
  async function loadProfile() {
    try {
      const p = await profileApi.get(studentRef.value)
      nickname.value = p.nickname
      schoolStage.value = p.school_stage
      className.value = p.class_name
    } catch {
      /* 后端不可用时沿用本地缓存 */
    } finally {
      profileLoaded.value = true
    }
  }

  /** 保存档案到后端；失败向上抛出，由页面提示。 */
  async function saveProfile() {
    const res = await profileApi.save({
      student_ref: studentRef.value,
      nickname: nickname.value.trim(),
      school_stage: schoolStage.value,
      class_name: className.value.trim(),
    })
    nickname.value = res.profile.nickname
    schoolStage.value = res.profile.school_stage
    className.value = res.profile.class_name
  }

  /** 从后端拉取紧急联系人列表；失败时保留当前列表。 */
  async function loadContacts() {
    try {
      const res = await contactApi.list(studentRef.value)
      contacts.value = res.contacts
    } catch {
      /* 后端不可用时保留当前列表 */
    }
  }

  async function addContact(c: Omit<EmergencyContact, 'id'>) {
    const res = await contactApi.add({
      student_ref: studentRef.value,
      name: c.name,
      relation: c.relation,
      phone: c.phone,
    })
    contacts.value = [...contacts.value, res.contact]
  }

  async function removeContact(id: string) {
    await contactApi.remove(studentRef.value, id)
    contacts.value = contacts.value.filter((c) => c.id !== id)
  }

  /** 重置为全新匿名身份（旧历史将无法再访问）。 */
  function resetIdentity() {
    studentRef.value = resetStudentRef()
    nickname.value = ''
    schoolStage.value = null
    className.value = ''
    contacts.value = []
    profileLoaded.value = false
  }

  return {
    studentRef,
    nickname,
    displayName,
    schoolStage,
    className,
    profileLoaded,
    contacts,
    prefs,
    loadProfile,
    saveProfile,
    loadContacts,
    addContact,
    removeContact,
    resetIdentity,
  }
})
