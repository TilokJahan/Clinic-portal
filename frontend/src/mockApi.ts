import { queueSeed, slots, type QueueItem } from './data'

// Swap this adapter for fetch() calls to the documented appointment API later.
const pause = (ms = 250) => new Promise((resolve) => setTimeout(resolve, ms))
let queue = [...queueSeed]

export const mockApi = {
  async getQueue(): Promise<QueueItem[]> { await pause(); return [...queue] },
  async getSlots(): Promise<string[]> { await pause(150); return [...slots] },
  async submitIntake(input: { name: string; reason: string; symptoms: string }): Promise<QueueItem> {
    await pause(500)
    const item: QueueItem = { id: `APT-${Date.now().toString().slice(-4)}`, name: input.name || 'New patient', initials: (input.name || 'NP').split(' ').map((part) => part[0]).join('').slice(0, 2).toUpperCase(), reason: input.reason || 'Symptom intake', time: new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }), wait: 0, urgency: 'routine', specialty: 'General Practice', summary: input.symptoms || 'No additional details provided.', redFlags: [] }
    queue = [item, ...queue]
    return item
  },
  async review(id: string, urgency: QueueItem['urgency']): Promise<void> { await pause(200); queue = queue.map((item) => item.id === id ? { ...item, urgency } : item) },
}
