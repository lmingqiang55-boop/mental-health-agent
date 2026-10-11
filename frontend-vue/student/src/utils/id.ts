/**
 * 幂等标识生成器。
 * 后端约定：utterance_id（chat）、message_id（healing/chat）、request_id（healing/start）、
 * capture_id（vision/capture）、frame_id（vision/frame）——
 * 重试时必须复用同一个；内容变了会 409。前端在本轮内保持稳定即可。
 */

function rand(): string {
  return Math.random().toString(36).slice(2, 10)
}

export function uid(prefix = 'id'): string {
  return `${prefix}-${Date.now().toString(36)}-${rand()}`
}

export const newUtteranceId = () => uid('u')
export const newMessageId = () => uid('m')
export const newRequestId = () => uid('req')
export const newCaptureId = () => uid('cap')
export const newFrameId = () => uid('f')
