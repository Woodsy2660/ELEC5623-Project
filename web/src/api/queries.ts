import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, streamTurns } from './client.ts'
import type { Schemas } from './client.ts'

export function useProjects() {
  return useQuery({ queryKey: ['projects'], queryFn: api.projects })
}

export function useRequirements(projectId: string) {
  return useQuery({
    queryKey: ['requirements', projectId],
    queryFn: () => api.requirements(projectId),
  })
}

export function useRequirement(projectId: string, requirementId: string) {
  return useQuery({
    queryKey: ['requirement', projectId, requirementId],
    queryFn: () => api.requirement(projectId, requirementId),
  })
}

export function useProposals(projectId: string) {
  return useQuery({
    queryKey: ['proposals', projectId],
    queryFn: () => api.proposals(projectId),
  })
}

export function useMeetings(projectId: string) {
  return useQuery({
    queryKey: ['meetings', projectId],
    queryFn: () => api.meetings(projectId),
  })
}

export function useTurns(meetingId: string) {
  return useQuery({
    queryKey: ['turns', meetingId],
    queryFn: () => api.turns(meetingId),
  })
}

export function useSettings(projectId: string) {
  return useQuery({
    queryKey: ['settings', projectId],
    queryFn: () => api.settings(projectId),
  })
}

export function useProject(projectId: string) {
  return useQuery({
    queryKey: ['projects'],
    queryFn: api.projects,
    select: (projects) => projects.find((project) => project.id === projectId),
  })
}

export function useDecide(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { proposalId: string; body: Schemas['DecisionRequest'] }) =>
      api.decide(input.proposalId, input.body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['proposals', projectId] })
    },
  })
}

export function useUpdateSettings(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['ProjectSettings']) => api.updateSettings(projectId, body),
    onSuccess: (data) => {
      queryClient.setQueryData(['settings', projectId], data)
    },
  })
}

export function useLiveTranscript(meetingId: string | null) {
  const [turns, setTurns] = useState<Schemas['StreamTurn'][]>([])
  const [error, setError] = useState<string | null>(null)
  const [seenId, setSeenId] = useState(meetingId)
  if (meetingId !== seenId) {
    setSeenId(meetingId)
    setTurns([])
    setError(null)
  }

  useEffect(() => {
    if (!meetingId) return
    const controller = new AbortController()
    const received: Schemas['StreamTurn'][] = []
    streamTurns(
      meetingId,
      (turn) => {
        if (controller.signal.aborted) return
        const index = received.findIndex((item) => item.turn_id === turn.turn_id)
        if (index >= 0) received[index] = turn
        else received.push(turn)
        setTurns(received.slice())
      },
      controller.signal,
    ).catch((err: unknown) => {
      if (controller.signal.aborted) return
      setError(err instanceof Error ? err.message : 'The transcript stream failed')
    })
    return () => controller.abort()
  }, [meetingId])

  return { turns, error }
}
