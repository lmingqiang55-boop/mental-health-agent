import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

/**
 * 学生端路由。四大板块：
 * /home 首页 · /assess 测评 · /heal 心理自助 · /me 我的
 * 测评流程页（同意/设备/会话/安全）为沉浸式独立页，不套底部 Tab。
 */
const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/home' },

  // 登录落地启航页（仪式感，可选）
  { path: '/launch', name: 'launch', component: () => import('@/views/LaunchPage.vue'), meta: { title: '启航', bare: true } },

  // 沉浸式测评流程
  { path: '/assess/consent', name: 'assess-consent', component: () => import('@/views/assess/AssessConsent.vue'), meta: { title: '知情同意', bare: true } },
  { path: '/assess/check', name: 'assess-check', component: () => import('@/views/assess/DeviceCheck.vue'), meta: { title: '设备检查', bare: true } },
  { path: '/assess/session/:id', name: 'assess-session', component: () => import('@/views/assess/AssessSession.vue'), meta: { title: '对话测评', bare: true, immersive: true } },
  { path: '/assess/safety', name: 'assess-safety', component: () => import('@/views/assess/AssessSafety.vue'), meta: { title: '安全检查', bare: true } },

  // 主布局
  {
    path: '/',
    component: () => import('@/layouts/StudentLayout.vue'),
    children: [
      { path: 'home', name: 'home', component: () => import('@/views/home/HomePage.vue'), meta: { title: '首页' } },

      { path: 'assess', name: 'assess', component: () => import('@/views/assess/AssessCenter.vue'), meta: { title: '测评' } },
      { path: 'assess/report/:resultId', name: 'assess-report', component: () => import('@/views/assess/AssessReport.vue'), meta: { title: '测评报告' } },

      { path: 'heal', name: 'heal', component: () => import('@/views/heal/HealHome.vue'), meta: { title: '心理自助' } },
      { path: 'heal/chat', name: 'heal-chat', component: () => import('@/views/heal/HealChat.vue'), meta: { title: '治愈陪伴' } },
      { path: 'heal/mood', name: 'heal-mood', component: () => import('@/views/heal/MoodJournal.vue'), meta: { title: '心情日记' } },
      { path: 'heal/toolkit', name: 'heal-toolkit', component: () => import('@/views/heal/Toolkit.vue'), meta: { title: '练习工具箱' } },
      { path: 'heal/toolkit/meditate', name: 'tool-meditate', component: () => import('@/views/heal/toolkit/Meditate.vue'), meta: { title: '冥想正念' } },
      { path: 'heal/toolkit/sleep', name: 'tool-sleep', component: () => import('@/views/heal/toolkit/Sleep.vue'), meta: { title: '睡眠辅助' } },
      { path: 'heal/toolkit/body', name: 'tool-body', component: () => import('@/views/heal/toolkit/BodyScan.vue'), meta: { title: '身体觉察' } },
      { path: 'heal/toolkit/sound', name: 'tool-sound', component: () => import('@/views/heal/toolkit/SoundTherapy.vue'), meta: { title: '声音疗愈' } },
      { path: 'heal/toolkit/art', name: 'tool-art', component: () => import('@/views/heal/toolkit/ArtTherapy.vue'), meta: { title: '艺术表达' } },
      { path: 'heal/icbt', name: 'heal-icbt', component: () => import('@/views/heal/ICBT.vue'), meta: { title: 'iCBT 单元' } },
      { path: 'heal/habits', name: 'heal-habits', component: () => import('@/views/heal/Habits.vue'), meta: { title: '微光打卡' } },
      { path: 'heal/reframe', name: 'heal-reframe', component: () => import('@/views/heal/Reframe.vue'), meta: { title: '认知重构' } },
      { path: 'heal/focus', name: 'heal-focus', component: () => import('@/views/heal/Focus.vue'), meta: { title: '专注学习' } },
      { path: 'heal/support', name: 'heal-support', component: () => import('@/views/heal/Support.vue'), meta: { title: '同伴支持' } },
      { path: 'heal/growth', name: 'heal-growth', component: () => import('@/views/heal/Growth.vue'), meta: { title: '成长回顾' } },

      { path: 'me', name: 'me', component: () => import('@/views/me/MeHome.vue'), meta: { title: '我的' } },
      { path: 'me/profile', name: 'me-profile', component: () => import('@/views/me/Profile.vue'), meta: { title: '个人档案' } },
      { path: 'me/collaboration', name: 'me-collaboration', component: () => import('@/views/me/Collaboration.vue'), meta: { title: '专业协作' } },
      { path: 'me/appointment', name: 'me-appointment', component: () => import('@/views/me/Appointment.vue'), meta: { title: '咨询预约' } },
      { path: 'me/privacy', name: 'me-privacy', component: () => import('@/views/me/Privacy.vue'), meta: { title: '隐私与授权' } },
      { path: 'me/contacts', name: 'me-contacts', component: () => import('@/views/me/Contacts.vue'), meta: { title: '紧急联系人' } },
      { path: 'me/messages', name: 'me-messages', component: () => import('@/views/me/Messages.vue'), meta: { title: '消息中心' } },
      { path: 'me/settings', name: 'me-settings', component: () => import('@/views/me/Settings.vue'), meta: { title: '设置' } },
    ],
  },

  { path: '/:pathMatch(.*)*', redirect: '/home' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  const t = to.meta.title as string | undefined
  document.title = t ? `${t} · 心晴` : '心晴'
})
