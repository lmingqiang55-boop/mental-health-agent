// 六维评估进度：显示每个维度的 pending/in_progress/covered 状态。

const DIMENSION_LABELS = {
  mood: '情绪',
  pressure: '压力',
  interpersonal: '人际关系',
  self_cognition: '自我认知',
  study_life: '学习生活',
  duration: '持续时间',
}

const STATUS_TEXT = {
  pending: '待询问',
  in_progress: '询问中',
  covered: '已了解',
}

export default function DimensionProgress({ assessmentState }) {
  const entries = Object.entries(assessmentState || {})
  const covered = entries.filter(([, s]) => s === 'covered').length

  return (
    <section className="card dimension-progress">
      <h3>评估进度 ({covered}/{entries.length})</h3>
      <ul>
        {entries.map(([dim, status]) => (
          <li key={dim} className={`dim-${status}`}>
            <span className="dim-name">{DIMENSION_LABELS[dim] || dim}</span>
            <span className="dim-status">{STATUS_TEXT[status] || status}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
