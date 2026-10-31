import { useEffect, useState } from 'react'
import { api } from './api'
import type { QueueEntry, StreamStatus } from './types'

/** The clinician queue, kept up to date by GET /queue/stream (Server-Sent Events). */
export function useQueue() {
  const [queue, setQueue] = useState<QueueEntry[] | null>(null)
  const [status, setStatus] = useState<StreamStatus>('connecting')
  useEffect(() => api.subscribeQueue(setQueue, setStatus), [])
  // Re-render every 30 s so wait times keep counting up between updates
  const [, setTick] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 30_000)
    return () => clearInterval(timer)
  }, [])
  return { queue, status, setQueue }
}
