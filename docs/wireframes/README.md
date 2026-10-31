# Screens (issue #12)

Screenshots of the four screens, taken from the running prototype with synthetic data
(`npm run dev:api` against the real backend). Use them as the layout to agree on; comment on
the pull request or in the team channel.

| Screen | File | What to check |
|---|---|---|
| Sign in | [1-login.png](1-login.png) | Prototype sign-in: choose patient or clinician demo account (no password until auth exists) |
| Patient booking | [2-booking.png](2-booking.png) | Date and provider pickers, time grid in local time, "That time was just taken" message on a 409 |
| Symptom intake with triage result | [3-intake-result.png](3-intake-result.png) | "AI suggestion · clinician decides" label, suggested priority, warning signs, emergency notice when urgent |
| Clinician queue | [4-clinician-queue.png](4-clinician-queue.png) | Urgency colours (red urgent, amber soon, green routine), wait time, live badge, accept/override buttons with the AI's choice marked |
| Clinician overview | [5-clinician-overview.png](5-clinician-overview.png) | Live counts, urgency mix, suggestions still to review |

To retake them, run the app and capture at 1440×900.
