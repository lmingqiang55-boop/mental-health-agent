/**
 * 心理自助 13 项功能 + iCBT 单元的单一数据源。
 * 首页（取前 8）与心理自助主页共用，避免两处各写一份导致不一致。
 * 编号沿用《学生端规划》§4.3 的功能编号。
 */

export type HealGroup = '陪伴' | '工具' | '成长' | '联结'

export interface HealFunctionItem {
  key: string
  /** 功能编号（iCBT 无编号） */
  no?: number
  title: string
  desc: string
  path: string
  icon: string
  group: HealGroup
  /** 核心功能（治愈陪伴） */
  core?: boolean
}

export const HEAL_FUNCTIONS: HealFunctionItem[] = [
  {
    key: 'companion',
    no: 13,
    title: '治愈陪伴',
    desc: '先看小晴给你的报告，再自由聊聊当下的情绪',
    path: '/heal/chat',
    icon: '✦',
    group: '陪伴',
    core: true,
  },
  {
    key: 'mood',
    no: 1,
    title: '心情日记',
    desc: '每天一次情绪打卡，看看这段时间的变化',
    path: '/heal/mood',
    icon: '☁',
    group: '陪伴',
  },
  {
    key: 'meditate',
    no: 2,
    title: '冥想正念',
    desc: '跟着呼吸引导，把注意力放回此刻',
    path: '/heal/toolkit/meditate',
    icon: '❋',
    group: '工具',
  },
  {
    key: 'sleep',
    no: 3,
    title: '睡眠辅助',
    desc: '睡前放松引导与轻柔音景',
    path: '/heal/toolkit/sleep',
    icon: '☾',
    group: '工具',
  },
  {
    key: 'body',
    no: 6,
    title: '身体觉察',
    desc: '从头到脚扫描身体，松开紧绷的地方',
    path: '/heal/toolkit/body',
    icon: '♡',
    group: '工具',
  },
  {
    key: 'sound',
    no: 7,
    title: '声音疗愈',
    desc: '雨声、海浪、篝火等实时音景',
    path: '/heal/toolkit/sound',
    icon: '♪',
    group: '工具',
  },
  {
    key: 'art',
    no: 8,
    title: '艺术表达',
    desc: '随手涂鸦，让情绪有另一种出口',
    path: '/heal/toolkit/art',
    icon: '✎',
    group: '工具',
  },
  {
    key: 'reframe',
    no: 5,
    title: '认知重构',
    desc: '把「我很糟」拆开看看，找出更贴近事实的想法',
    path: '/heal/reframe',
    icon: '⇄',
    group: '工具',
  },
  {
    key: 'icbt',
    title: 'iCBT 单元',
    desc: '像课程一样，一小节一小节地了解情绪',
    path: '/heal/icbt',
    icon: '▤',
    group: '工具',
  },
  {
    key: 'habits',
    no: 4,
    title: '微光打卡',
    desc: '完成一件小事就点亮一颗星，累积连续天数',
    path: '/heal/habits',
    icon: '✧',
    group: '成长',
  },
  {
    key: 'focus',
    no: 9,
    title: '专注学习',
    desc: '番茄钟陪你进入状态，记下每次专注',
    path: '/heal/focus',
    icon: '◔',
    group: '成长',
  },
  {
    key: 'growth',
    no: 12,
    title: '成长回顾',
    desc: '把这段时间的心情与坚持汇总成一页',
    path: '/heal/growth',
    icon: '✿',
    group: '成长',
  },
  {
    key: 'support',
    no: 10,
    title: '同伴支持',
    desc: '给心理老师留言，也可以看看回复',
    path: '/heal/support',
    icon: '☺',
    group: '联结',
  },
  {
    key: 'collaboration',
    no: 11,
    title: '专业协作',
    desc: '需要更专业的帮助时，这里告诉你怎么办',
    path: '/me/collaboration',
    icon: '⚑',
    group: '联结',
  },
]

/** 首页只展示前 8 项入口，核心功能排在最前。 */
export const HEAL_HOME_ENTRIES: HealFunctionItem[] = HEAL_FUNCTIONS.slice(0, 8)
