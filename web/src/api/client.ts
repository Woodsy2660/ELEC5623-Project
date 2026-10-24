import type { components } from './schema'

export type Schemas = components['schemas']

// Dev talks to the local fixture API. A production build calls `/api` on the
// same host. Set VITE_API_BASE to override either one.
const baseUrl =
  import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '/api')

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, reason: string, body: unknown) {
    super(reason)
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      body = null
    }
    throw new ApiError(response.status, reasonFrom(body, response.statusText), body)
  }
  return (await response.json()) as T
}

export const api = {
  projects: () => request<Schemas['ProjectOut'][]>('/projects'),
  requirements: (projectId: string) =>
    request<Schemas['RegisterRow'][]>(`/projects/${projectId}/requirements`),
  requirement: (projectId: string, requirementId: string) =>
    request<Schemas['RequirementDetail']>(`/projects/${projectId}/requirements/${requirementId}`),
  proposals: (projectId: string) =>
    request<Schemas['ProposalList']>(`/projects/${projectId}/proposals`),
  // can_confirm and a 409 reason come from Python. Render them; do not recompute a transition.
  decide: (proposalId: string, body: Schemas['DecisionRequest']) =>
    request<Schemas['CommittedEvent']>(`/proposals/${proposalId}/decision`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  meetings: (projectId: string) =>
    request<Schemas['MeetingOut'][]>(`/projects/${projectId}/meetings`),
  createMeeting: (projectId: string, body: Schemas['MeetingCreate']) =>
    request<Schemas['MeetingOut']>(`/projects/${projectId}/meetings`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  turns: (meetingId: string) => request<Schemas['StreamTurn'][]>(`/meetings/${meetingId}/turns`),
  settings: (projectId: string) =>
    request<Schemas['ProjectSettings']>(`/projects/${projectId}/settings`),
  updateSettings: (projectId: string, body: Schemas['ProjectSettings']) =>
    request<Schemas['ProjectSettings']>(`/projects/${projectId}/settings`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
}

function reasonFrom(body: unknown, fallback: string): string {
  if (body !== null && typeof body === 'object' && 'reason' in body && typeof body.reason === 'string') {
    return body.reason
  }
  if (body !== null && typeof body === 'object' && 'detail' in body) {
    const detail = body.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const first = detail[0]
      if (first !== null && typeof first === 'object' && 'msg' in first && typeof first.msg === 'string') {
        return first.msg
      }
    }
  }
  return fallback
}

export async function streamTurns(
  meetingId: string,
  onTurn: (turn: Schemas['StreamTurn']) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${baseUrl}/meetings/${meetingId}/stream`, {
    headers: { Accept: 'text/event-stream' },
    signal,
  })
  if (!response.ok || response.body == null) {
    throw new ApiError(response.status, response.statusText, null)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const pieces = buffer.split('\n\n')
      buffer = pieces.pop() ?? ''
      for (const piece of pieces) {
        const line = piece.split('\n').find((item) => item.startsWith('data: '))
        if (!line) continue
        onTurn(JSON.parse(line.slice('data: '.length)) as Schemas['StreamTurn'])
      }
    }
  } catch (error) {
    if (signal?.aborted) return
    throw error
  }
}
