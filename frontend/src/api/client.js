// 统一 API 客户端。所有页面通过这里访问后端，不直接 fetch。

async function request(path, options = {}) {
  const multipart = typeof FormData !== 'undefined' && options.body instanceof FormData
  const response = await fetch(path, {
    ...options,
    headers: { ...(multipart ? {} : { 'Content-Type': 'application/json' }), ...options.headers },
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
  createSession: (studentRef = null) => request('/api/session', {
    method: 'POST',
    ...(studentRef ? { body: JSON.stringify({ student_ref: studentRef }) } : {}),
  }),
  getSession: (id) => request(`/api/session/${id}`),
  deleteSession: (id) => request(`/api/session/${id}`, { method: 'DELETE' }),
  updateConsent: (id, granted, scope = []) =>
    request(`/api/session/${id}/consent`, {
      method: 'PUT',
      body: JSON.stringify({ session_id: id, granted, scope }),
    }),

  // Chat
  sendChat: (sessionId, text, metadata = {}, options = {}) =>
    request('/api/chat', {
      method: 'POST',
      ...options,
      body: JSON.stringify({ ...metadata, session_id: sessionId, text }),
    }),

  // Vision / Audio
  submitVision: (sessionId, state) =>
    request('/api/vision', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, state }),
    }),
  analyzeVisionFrame: (sessionId, imageBase64, timing = {}, options = {}) =>
    request('/api/vision/frame', {
      method: 'POST',
      ...options,
      body: JSON.stringify({ ...timing, session_id: sessionId, image_base64: imageBase64 }),
    }),
  setVisionCapture: (sessionId, captureId, generation, active) =>
    request('/api/vision/capture', {
      method: 'POST', body: JSON.stringify({ session_id: sessionId, capture_id: captureId, generation, active }),
    }),
  freezeVisionSegment: (payload, options = {}) =>
    request('/api/vision/segment', { method: 'POST', ...options, body: JSON.stringify(payload) }),
  audioStatus: () => request('/api/audio/status'),
  transcribe: (form, options = {}) =>
    request('/api/audio/transcribe', { method: 'POST', ...options, body: form }),
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
