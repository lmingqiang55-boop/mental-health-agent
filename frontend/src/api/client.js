// 统一 API 客户端。所有页面通过这里访问后端，不直接 fetch。

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await response.json()
  if (!response.ok) {
    const error = new Error(data.error?.message || '请求失败，请稍后重试。')
    error.code = data.error?.code
    error.status = response.status
    throw error
  }
  return data
}

export const api = {
  // Session
  createSession: () => request('/api/session', { method: 'POST' }),
  getSession: (id) => request(`/api/session/${id}`),
  deleteSession: (id) => request(`/api/session/${id}`, { method: 'DELETE' }),
  updateConsent: (id, granted, scope = []) =>
    request(`/api/session/${id}/consent`, {
      method: 'PUT',
      body: JSON.stringify({ session_id: id, granted, scope }),
    }),

  // Chat
  sendChat: (sessionId, text) =>
    request('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, text }),
    }),

  // Vision / Audio
  submitVision: (sessionId, state) =>
    request('/api/vision', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, state }),
    }),
  submitAudio: (sessionId, state) =>
    request('/api/audio', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, state }),
    }),

  // Assessment
  triggerAssessment: (sessionId) =>
    request('/api/assessment', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    }),
  getResult: (resultId, sessionId) =>
    request(`/api/assessment/result/${resultId}?session_id=${sessionId}`),

  // History
  getHistory: (studentRef) => request(`/api/history/${studentRef}`),

  // Teacher
  listRecords: () => request('/api/teacher/records'),
  getRecord: (id) => request(`/api/teacher/records/${id}`),
  getStudentHistory: (ref) => request(`/api/teacher/student/${ref}`),
  listHighRisk: () => request('/api/teacher/high-risk'),
  addNote: (recordId, counselorRef, content) =>
    request(`/api/teacher/records/${recordId}/notes`, {
      method: 'POST',
      body: JSON.stringify({ counselor_ref: counselorRef, content }),
    }),
  getGroupStats: () => request('/api/teacher/group-stats'),

  // Communication
  sendCommunication: (payload) =>
    request('/api/communication', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listCommunication: (studentRef) =>
    request(`/api/communication/${studentRef}`),
}
