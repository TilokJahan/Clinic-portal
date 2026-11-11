import test from 'node:test'
import assert from 'node:assert/strict'
import { File } from 'node:buffer'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer, resolveConfig } from 'vite'

const tech = { token: 'synthetic-test-token', user: { id: 6, role: 'lab_tech', email: 'labtech1@example.com' } }
const pdf = () => new File(['%PDF synthetic fixture'], 'synthetic.pdf', { type: 'application/pdf' })

test('API dev mode selects the real backend without an untracked env file', async () => {
  const previous = process.env.VITE_API_MODE
  delete process.env.VITE_API_MODE
  try {
    const config = await resolveConfig({}, 'serve', 'api')
    assert.equal(config.define['import.meta.env.VITE_API_MODE'], '"http"')
    assert.equal(config.server.proxy['/api'].target, 'http://localhost:8001')
  } finally {
    if (previous === undefined) delete process.env.VITE_API_MODE
    else process.env.VITE_API_MODE = previous
  }
})

async function fixture(mode, run) {
  const previousFetch = globalThis.fetch
  const previousStorage = globalThis.localStorage
  const keys = ['VITE_API_MODE', 'VITE_AUTH_MODE', 'VITE_API_BASE']
  const previousEnv = Object.fromEntries(keys.map((key) => [key, process.env[key]]))
  const stored = new Map([['clinic-portal.session', JSON.stringify(tech)]])
  globalThis.localStorage = {
    getItem: (key) => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, String(value)),
    removeItem: (key) => stored.delete(key),
  }
  process.env.VITE_API_MODE = mode
  process.env.VITE_AUTH_MODE = 'dev'
  process.env.VITE_API_BASE = '/api'
  const server = await createServer({ configFile: false, optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true }, appType: 'custom' })
  try {
    const session = await server.ssrLoadModule('/src/session.ts')
    let controls
    function CaptureSession() { controls = session.useSession(); return null }
    renderToString(React.createElement(CaptureSession))
    await run({ server, session, setSession: controls.setSession, stored })
  } finally {
    await server.close()
    globalThis.fetch = previousFetch
    if (previousStorage === undefined) delete globalThis.localStorage
    else globalThis.localStorage = previousStorage
    for (const key of keys) {
      if (previousEnv[key] === undefined) delete process.env[key]
      else process.env[key] = previousEnv[key]
    }
  }
}

test('HTTP lab workflow uses authenticated backend contracts', async (t) => {
  await fixture('http', async ({ server, session, stored }) => {
    const { httpApi } = await server.ssrLoadModule('/src/api/http.ts')
    const { demoLogin } = await server.ssrLoadModule('/src/auth.ts')
    const { labFileError, MAX_LAB_FILE_BYTES } = await server.ssrLoadModule('/src/labUpload.ts')

    await t.test('demo sign-in sends email/passcode and trusts the returned ID', async () => {
      globalThis.fetch = async (url, init) => {
        assert.equal(url, '/api/auth/dev-login')
        assert.deepEqual(JSON.parse(init.body), { email: tech.user.email, passcode: 'synthetic-passcode' })
        return Response.json({ access_token: 'backend-test-token', user: { ...tech.user, id: 66 } })
      }
      const result = await demoLogin(tech.user.email, 'synthetic-passcode')
      assert.equal(result.ok, true)
      assert.equal(result.data.user.id, 66)
      assert.equal(result.data.token, 'backend-test-token')
    })

    await t.test('worklist request includes date and bearer token', async () => {
      globalThis.fetch = async (url, init) => {
        assert.equal(url, '/api/lab/worklist?date=2030-01-07')
        assert.equal(init.headers.Authorization, `Bearer ${tech.token}`)
        return Response.json([])
      }
      assert.deepEqual(await httpApi.labWorklist('2030-01-07'), { ok: true, data: [] })
    })

    await t.test('upload targets the appointment, sends a multipart file and preserves 202 receipt', async () => {
      globalThis.fetch = async (url, init) => {
        assert.equal(url, '/api/lab/appointments/42/reports')
        assert.equal(init.method, 'POST')
        assert.equal(init.headers.Authorization, `Bearer ${tech.token}`)
        assert.equal(init.headers['Content-Type'], undefined, 'the browser must add the multipart boundary')
        assert.ok(init.body instanceof FormData)
        assert.equal(init.body.get('file').name, 'synthetic.pdf')
        assert.equal(await init.body.get('file').text(), '%PDF synthetic fixture')
        return Response.json({ id: 99, appointment_id: 42, status: 'processing', results: [] }, { status: 202 })
      }
      const result = await httpApi.uploadLabReportAsTech(42, pdf())
      assert.equal(result.ok, true)
      assert.equal(result.data.appointment_id, 42)
      assert.equal(result.data.status, 'processing')
    })

    await t.test('file validation matches backend types and size boundaries', () => {
      for (const type of ['application/pdf', 'image/png', 'image/jpeg']) {
        assert.equal(labFileError(new File(['fixture'], 'fixture', { type })), null)
      }
      assert.match(labFileError(new File(['x'], 'results.csv', { type: 'text/csv' })), /PDF, PNG or JPEG/)
      assert.match(labFileError(new File([], 'empty.pdf', { type: 'application/pdf' })), /empty/)
      assert.equal(labFileError(new File([new Uint8Array(MAX_LAB_FILE_BYTES)], 'max.pdf', { type: 'application/pdf' })), null)
      assert.match(labFileError(new File([new Uint8Array(MAX_LAB_FILE_BYTES + 1)], 'large.pdf', { type: 'application/pdf' })), /over 10 MB/)
    })

    await t.test('upload errors are preserved and forbidden access does not sign the user out', async () => {
      for (const [status, detail] of [[403, 'Not allowed for your role'], [409, 'Appointment is already completed'], [413, 'The file is over 10 MB'], [415, 'Upload a PDF, PNG or JPEG']]) {
        globalThis.fetch = async () => Response.json({ detail }, { status })
        assert.deepEqual(await httpApi.uploadLabReportAsTech(42, pdf()), { ok: false, status, detail })
      }
      assert.equal(session.sessionUser().role, 'lab_tech')
    })

    await t.test('network failure gives a retryable error', async () => {
      globalThis.fetch = async () => { throw new Error('Offline fixture') }
      const result = await httpApi.labWorklist('2030-01-07')
      assert.equal(result.ok, false)
      assert.equal(result.status, 0)
    })

    await t.test('401 clears the signed-in session', async () => {
      globalThis.fetch = async () => Response.json({ detail: 'Token expired' }, { status: 401 })
      assert.equal((await httpApi.labWorklist('2030-01-07')).status, 401)
      assert.equal(session.sessionUser(), null)
      assert.equal(await session.sessionToken(), null)
      assert.equal(stored.has('clinic-portal.session'), false)
      assert.equal(stored.has('clinic-portal.lab-results'), false)
    })
  })
})

test('mock lab workflow mirrors role restrictions and clinician approval', async (t) => {
  await fixture('mock', async ({ server, setSession, stored }) => {
    const { mockApi } = await server.ssrLoadModule('/src/api/mock.ts')
    const { DEMO_ACCOUNTS } = await server.ssrLoadModule('/src/auth.ts')
    const day = new Date()
    do day.setUTCDate(day.getUTCDate() + 1); while ([0, 6].includes(day.getUTCDay()))
    const date = day.toISOString().slice(0, 10)
    const emptyDay = new Date(day)
    emptyDay.setUTCDate(emptyDay.getUTCDate() - 14)
    let visit
    let reportId

    await t.test('lab-tech demo uses ID 6 and worklist exposes appointment metadata only', async () => {
      assert.equal(DEMO_ACCOUNTS.find((user) => user.role === 'lab_tech').id, 6)
      const result = await mockApi.labWorklist(date)
      assert.equal(result.ok, true)
      assert.equal(result.data.length, 4)
      visit = result.data[0]
      assert.deepEqual(Object.keys(visit).sort(), ['appointment_id', 'patient_label', 'provider_name', 'reports', 'starts_at', 'status'])
    })

    await t.test('invalid dates/files/appointments fail without storing reports', async () => {
      assert.equal((await mockApi.labWorklist('bad-date')).status, 422)
      assert.equal((await mockApi.labWorklist(emptyDay.toISOString().slice(0, 10))).data.length, 0)
      assert.equal((await mockApi.uploadLabReportAsTech(999999, pdf())).status, 404)
      assert.equal((await mockApi.uploadLabReportAsTech(visit.appointment_id, new File(['x'], 'x.csv', { type: 'text/csv' }))).status, 415)
      assert.equal((await mockApi.uploadLabReportAsTech(visit.appointment_id, new File([], 'empty.pdf', { type: 'application/pdf' }))).status, 422)
      assert.equal((await mockApi.labWorklist(date)).data.flatMap((entry) => entry.reports).length, 0)
    })

    await t.test('tech can upload for another patient but cannot read or approve results', async () => {
      const result = await mockApi.uploadLabReportAsTech(visit.appointment_id, pdf())
      assert.equal(result.ok, true)
      assert.equal(result.data.status, 'processing')
      assert.deepEqual(result.data.results, [])
      reportId = result.data.id
      assert.equal((await mockApi.labReports(visit.appointment_id)).status, 403)
      assert.equal((await mockApi.labReportFile(reportId)).status, 403)
      assert.equal((await mockApi.approveLabExplanation(reportId, 'Forbidden')).status, 403)
      assert.equal((await mockApi.uploadLabReport(visit.appointment_id, pdf())).status, 403)
    })

    await t.test('processing completes and worklist still contains no extracted results', async () => {
      await new Promise((done) => setTimeout(done, 850))
      const report = (await mockApi.labWorklist(date)).data.find((entry) => entry.appointment_id === visit.appointment_id).reports[0]
      assert.equal(report.status, 'ready')
      assert.equal('results' in report, false)
      assert.equal('patient_explanation' in report, false)
    })

    await t.test('patient sees receipt only, then sees results after clinician approval', async () => {
      const patientId = Number(visit.patient_label.replace(/\D/g, ''))
      setSession({ token: 'mock', user: { id: patientId, role: 'patient', email: `patient${patientId}@example.com` } })
      assert.equal((await mockApi.labWorklist(date)).status, 403)
      assert.equal((await mockApi.uploadLabReportAsTech(visit.appointment_id, pdf())).status, 403)
      assert.deepEqual((await mockApi.labReports(visit.appointment_id)).data[0].results, [])
      setSession({ token: 'mock', user: { id: 4, role: 'clinician', email: 'clinician1@example.com' } })
      assert.equal((await mockApi.labWorklist(date)).status, 403)
      assert.ok((await mockApi.labReports(visit.appointment_id)).data[0].results.length > 0)
      assert.equal((await mockApi.approveLabExplanation(reportId, 'Reviewed synthetic explanation')).ok, true)
      setSession({ token: 'mock', user: { id: patientId, role: 'patient', email: `patient${patientId}@example.com` } })
      assert.equal((await mockApi.labReports(visit.appointment_id)).data[0].explanation_approved, true)
      assert.ok((await mockApi.labReports(visit.appointment_id)).data[0].results.length > 0)
      assert.equal(stored.has('clinic-portal.lab-results'), false)
    })

    await t.test('admin can use the worklist and signed-out users cannot', async () => {
      setSession({ token: 'mock', user: { id: 5, role: 'admin', email: 'admin1@example.com' } })
      assert.equal((await mockApi.labWorklist(date)).ok, true)
      assert.equal((await mockApi.uploadLabReportAsTech(visit.appointment_id, pdf())).ok, true)
      setSession(null)
      assert.equal((await mockApi.labWorklist(date)).status, 401)
      assert.equal((await mockApi.uploadLabReportAsTech(visit.appointment_id, pdf())).status, 401)
    })
  })
})
