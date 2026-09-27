// 心理老师端页面：个体管理、高风险预警、群体统计。
// 框架阶段从后端读取 Mock/真实生成的记录，无身份认证，仅作骨架。

import { useEffect, useState } from 'react'
import { api } from '../api/client'

const RISK_LABELS = { low: '低', medium: '中', high: '高' }

function RecordsTab() {
  const [records, setRecords] = useState([])
  const [selected, setSelected] = useState(null)

  async function load() {
    const data = await api.listRecords()
    setRecords(data.records)
  }
  useEffect(() => { load() }, [])

  async function openDetail(recordId) {
    const data = await api.getRecord(recordId)
    setSelected(data.record)
  }

  if (selected) {
    const r = selected.result
    return (
      <div className="detail-view">
        <button className="secondary" onClick={() => setSelected(null)}>← 返回列表</button>
        <h3>学生 {selected.student_ref} 的筛查详情</h3>
        <p><b>风险等级：</b>{RISK_LABELS[r.risk.risk_level]} ·
          综合指数 {r.overall_score.toFixed(2)}</p>
        <h4>维度得分</h4>
        <table className="data-table">
          <thead><tr><th>维度</th><th>得分</th><th>证据</th></tr></thead>
          <tbody>
            {r.dimension_scores.map(ds => (
              <tr key={ds.dimension}>
                <td>{ds.dimension_label}</td>
                <td>{ds.score.toFixed(2)}</td>
                <td>{ds.evidence.join('；') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <h4>个性化建议</h4>
        <ul>{r.recommendations.map((rec, i) => <li key={i}>{rec.content}</li>)}</ul>
        <p className="disclaimer">{r.summary}</p>
        <h4>跟进记录</h4>
        {selected.counselor_notes.length === 0 && <p className="muted">暂无跟进记录</p>}
        {selected.counselor_notes.map(n => (
          <p key={n.note_id} className="note-item">
            [{n.counselor_ref}] {n.content}
          </p>
        ))}
      </div>
    )
  }

  return (
    <div>
      <h3>个体筛查管理</h3>
      {records.length === 0 ? (
        <p className="muted">暂无筛查记录。请先在学生端完成一次对话评估。</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>学生标识</th><th>综合指数</th><th>风险</th><th>跟进状态</th><th>时间</th><th></th></tr>
          </thead>
          <tbody>
            {records.map(r => (
              <tr key={r.record_id}>
                <td>{r.student_ref}</td>
                <td>{r.overall_score.toFixed(2)}</td>
                <td className={`risk-text risk-${r.risk_level}`}>{RISK_LABELS[r.risk_level]}</td>
                <td>{r.follow_up_status}</td>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td><button className="secondary small" onClick={() => openDetail(r.record_id)}>查看</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function HighRiskTab() {
  const [data, setData] = useState(null)
  useEffect(() => { api.listHighRisk().then(setData) }, [])
  if (!data) return <p>加载中…</p>

  return (
    <div>
      <h3>高风险预警与干预（{data.high_risk_count} 人）</h3>
      {data.students.length === 0 ? <p className="muted">当前无中/高风险学生。</p> : (
        <table className="data-table">
          <thead>
            <tr><th>学生标识</th><th>风险等级</th><th>风险类型</th><th>原因</th><th>关键证据</th><th>状态</th></tr>
          </thead>
          <tbody>
            {data.students.map(s => (
              <tr key={s.record_id}>
                <td>{s.student_ref}</td>
                <td className={`risk-text risk-${s.risk_level}`}>{RISK_LABELS[s.risk_level]}</td>
                <td>{s.risk_types.join('、') || '—'}</td>
                <td>{s.risk_reasons.join('；')}</td>
                <td>{s.key_evidence.join('；')}</td>
                <td>{s.follow_up_status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function GroupStatsTab() {
  const [stats, setStats] = useState(null)
  useEffect(() => { api.getGroupStats().then(setStats) }, [])
  if (!stats) return <p>加载中…</p>

  return (
    <div>
      <h3>群体心理统计</h3>
      {stats.total_students === 0 ? <p className="muted">暂无数据。</p> : (
        <>
          <p>已筛查学生总数：<b>{stats.total_students}</b></p>
          <h4>风险分布</h4>
          <div className="stats-bars">
            {Object.entries(stats.risk_distribution).map(([level, count]) => (
              <div key={level} className="stats-row">
                <span className={`risk-text risk-${level}`}>{RISK_LABELS[level]}</span>
                <div className="bar">
                  <div className={`bar-fill risk-bg-${level}`}
                    style={{ width: `${(count / stats.total_students) * 100}%` }} />
                </div>
                <span>{count} 人</span>
              </div>
            ))}
          </div>
          <h4>各维度平均水平</h4>
          <table className="data-table">
            <thead><tr><th>维度</th><th>平均值</th></tr></thead>
            <tbody>
              {Object.entries(stats.dimension_averages).map(([dim, avg]) => (
                <tr key={dim}><td>{dim}</td><td>{avg}</td></tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

export default function TeacherPage() {
  const [tab, setTab] = useState('records')

  return (
    <div className="teacher-page">
      <header className="page-header">
        <div>
          <h1>心理老师工作台</h1>
          <p>个体筛查 · 风险预警 · 群体统计 · 框架演示版</p>
        </div>
      </header>
      <nav className="tabs">
        <button className={tab === 'records' ? 'active' : 'secondary'}
          onClick={() => setTab('records')}>个体筛查管理</button>
        <button className={tab === 'high-risk' ? 'active' : 'secondary'}
          onClick={() => setTab('high-risk')}>高风险预警</button>
        <button className={tab === 'stats' ? 'active' : 'secondary'}
          onClick={() => setTab('stats')}>群体统计</button>
      </nav>
      <section className="card tab-content">
        {tab === 'records' && <RecordsTab />}
        {tab === 'high-risk' && <HighRiskTab />}
        {tab === 'stats' && <GroupStatsTab />}
      </section>
    </div>
  )
}
