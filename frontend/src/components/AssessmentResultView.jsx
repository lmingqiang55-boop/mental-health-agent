// 评估结果展示：维度得分、风险等级、重要关注点、个性化建议。

function RiskBadge({ level }) {
  const labels = { low: '低风险', medium: '中风险', high: '高风险' }
  return <span className={`risk-badge risk-${level}`}>{labels[level] || level}</span>
}

export default function AssessmentResultView({ result }) {
  if (!result) return null

  return (
    <section className="card assessment-result">
      <h3>本次筛查结果</h3>

      <div className="result-header">
        <RiskBadge level={result.risk.risk_level} />
        <span className="overall-score">
          综合指数 {result.overall_score.toFixed(2)}
        </span>
      </div>

      <div className="dimension-scores">
        {result.dimension_scores.map((ds) => (
          <div key={ds.dimension} className="score-row">
            <span className="score-label">{ds.dimension_label}</span>
            <div className="score-bar">
              <div className="score-fill" style={{ width: `${ds.score * 100}%` }} />
            </div>
            <span className="score-value">{ds.score.toFixed(2)}</span>
          </div>
        ))}
      </div>

      {result.key_concerns?.length > 0 && (
        <div className="concerns">
          <h4>重要关注点</h4>
          <ul>{result.key_concerns.map((c, i) => <li key={i}>{c}</li>)}</ul>
        </div>
      )}

      <div className="recommendations">
        <h4>个性化建议</h4>
        {result.recommendations.map((rec, i) => (
          <div key={i} className={`rec-item priority-${rec.priority}`}>
            <span className="rec-tag">
              {rec.category === 'emotion_regulation' ? '情绪调节'
                : rec.category === 'study_life' ? '学习生活' : '求助资源'}
            </span>
            <p>{rec.content}</p>
          </div>
        ))}
      </div>

      <p className="result-summary">{result.summary}</p>
      <p className="disclaimer">结果由 AI 初步生成（{result.assessment_method}），
        未经人工复核，不构成临床诊断。</p>
    </section>
  )
}
