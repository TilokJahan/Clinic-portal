export type Urgency = 'urgent' | 'soon' | 'routine'
export type QueueItem = { id: string; name: string; initials: string; reason: string; time: string; wait: number; urgency: Urgency; specialty: string; summary: string; redFlags: string[] }

export const queueSeed: QueueItem[] = [
  { id: 'APT-2048', name: 'Michael Jordan', initials: 'MJ', reason: 'Chest tightness, shortness of breath', time: '9:42 AM', wait: 4, urgency: 'urgent', specialty: 'Cardiology', summary: 'Reports tightness in the chest and shortness of breath beginning this morning. Symptoms worsen with activity.', redFlags: ['Chest discomfort', 'Shortness of breath'] },
  { id: 'APT-2047', name: 'Morgan Chen', initials: 'MC', reason: 'Persistent migraine', time: '9:35 AM', wait: 11, urgency: 'soon', specialty: 'Neurology', summary: 'Recurring headache for two days with light sensitivity. No sudden onset reported.', redFlags: [] },
  { id: 'APT-2046', name: 'Taylor Brooks', initials: 'TB', reason: 'Seasonal allergy symptoms', time: '9:28 AM', wait: 18, urgency: 'routine', specialty: 'General Practice', summary: 'Sneezing and itchy eyes over the past week, likely seasonal pattern.', redFlags: [] },
  { id: 'APT-2045', name: 'Alex Rivera', initials: 'AR', reason: 'Fever and cough', time: '9:16 AM', wait: 29, urgency: 'soon', specialty: 'General Practice', summary: 'Fever and dry cough for three days. Patient reports fatigue but is staying hydrated.', redFlags: ['Fever'] },
]

export const slots = ['9:30 AM', '10:15 AM', '11:00 AM', '1:30 PM', '2:15 PM', '3:00 PM']
