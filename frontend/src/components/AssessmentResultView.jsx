// 展示新评估 Agent 已实际生成的五维画像与关注指数。

function RiskBadge({ level }) {
  const labels = { low: '低风险', medium: '中风险', high: '高风险' }
  return <span className={`risk-badge risk-${level}`}>{labels[level] || level}</span>
}

export default function AssessmentResultView({ result }) {
  if (!result) return null
  const labels = {
    emotion: '情绪状态',
    interest_motivation: '兴趣与动力',
    sleep_energy: '睡眠与精力',
    attention_thinking: '专注与思考',
    social_daily: '社交与日常功能',
  }
  const levelLabels = {
    low_concern: '低关注',
    mild_concern: '轻度关注',
    moderate_concern: '中度关注',
    high_concern: '高度关注',
  }

  return (
    <section className="card assessment-result">
      <h3>本次筛查结果</h3>

      <div className="result-header">
        <RiskBadge level={result.risk.risk_level} />
        <span className="overall-score">
          关注指数 {result.concern_index} / 100
        </span>
      </div>

      <div className="dimension-scores">
        {Object.entries(result.psychological_profile).map(([dimension, score]) => (
          <div key={dimension} className="score-row">
            <span className="score-label">{labels[dimension] || dimension}</span>
            <div className="score-bar">
              <div className="score-fill" style={{ width: `${score}%` }} />
            </div>
            <span className="score-value">{score}</span>
          </div>
        ))}
      </div>
      <p className="disclaimer">关注等级：{levelLabels[result.overall_level] || result.overall_level}。本结果仅供初步了解，
        不构成临床诊断；报告文案、趋势与建议尚未接入。</p>
    </section>
  )
}
