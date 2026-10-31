# Triage service: PII redaction

Symptom text is redacted **before** it reaches any AI model. The implementation is
`services/triage-service/app/redaction.py` (Microsoft Presidio with a spaCy model, plus a small
regex fallback). Redaction reduces risk but does not guarantee anonymity.

## What is redacted

| Entity | Replaced with |
|---|---|
| Person names | `<PERSON>` |
| Phone numbers | `<PHONE_NUMBER>` |
| Email addresses | `<EMAIL_ADDRESS>` |
| Locations | `<LOCATION>` |
| US Social Security numbers (dashed, NNN-NN-NNNN) | `<US_SSN>` |

Dates and durations are deliberately **not** redacted. A broad date entity would also remove
clinically useful phrases such as "two days" or "since Tuesday".

## Model choice: `en_core_web_sm` vs `en_core_web_lg`

We compared both spaCy models on 10 synthetic sentences with
`services/triage-service/scripts/compare_models.py`. Each sentence lists text that must be
removed and text that must survive.

| | `en_core_web_sm` | `en_core_web_lg` |
|---|---|---|
| Private text leaked | 1 (the SSN) | 1 (the SSN) |
| Useful text wrongly removed | 0 | 0 |
| Model load time | 0.6 s | 2.0 s |
| Approx. size added to the image | ~12 MB | ~400 MB |

**Decision: `en_core_web_sm`.** Both models gave identical results on every sentence, so the
larger model buys no accuracy on our cases. The small model keeps the Docker image and the AKS
image pulls much smaller and loads faster.

The load times above were measured on a laptop after the large model had already been downloaded.
Per-call timings are not compared, because they are noisy and may include one-off warm-up work.

To reproduce:

```bash
cd services/triage-service
pip install -r requirements.txt
python -m spacy download en_core_web_lg     # local only, not in requirements.txt
python scripts/compare_models.py
```

### Raw output

```text
=== en_core_web_sm (load time 0.6s) ===
OK   My name is <PERSON> and I have a headache
OK   Call me at <PHONE_NUMBER> about my cough
OK   <PERSON> me at <EMAIL_ADDRESS>, my knee hurts
OK   Chest pain for two days
OK   I take 500 mg twice a day for back pain
OK   Dr. <PERSON> saw me in <LOCATION> last week
OK   this is <PERSON>, dizzy since monday
OK   My son <PERSON> has a fever of 102
OK   <PERSON> here, rash on my arm
FAIL SSN 678-00-1939, short of breath
     LEAKED (private text still present): ['678-00-1939']
--> leaks: 1, wrongly removed: 0, ~21 ms/call

=== en_core_web_lg (load time 2.0s) ===
OK   My name is <PERSON> and I have a headache
OK   Call me at <PHONE_NUMBER> about my cough
OK   <PERSON> me at <EMAIL_ADDRESS>, my knee hurts
OK   Chest pain for two days
OK   I take 500 mg twice a day for back pain
OK   Dr. <PERSON> saw me in <LOCATION> last week
OK   this is <PERSON>, dizzy since monday
OK   My son <PERSON> has a fever of 102
OK   <PERSON> here, rash on my arm
FAIL SSN 678-00-1939, short of breath
     LEAKED (private text still present): ['678-00-1939']
--> leaks: 1, wrongly removed: 0, ~7 ms/call
```

## SSN gap and fallback

Presidio's built-in `US_SSN` recognizer left the SSN in the text with **both** models, so the
problem is the recognizer, not the language model. `redaction.py` therefore runs a regex pass
(`\b\d{3}-\d{2}-\d{4}\b`) after Presidio and replaces matches with `<US_SSN>`.

The fallback has limits:

- It only matches the dashed format. A bare nine-digit number such as `123456789` is **not**
  caught, on purpose, because that would also flag unrelated numbers in symptom text.
- A phone number (`555-123-4567`) is not mistaken for an SSN. This is covered by a test.

## Known limits

- Only 10 comparison sentences and a small set of unit tests were used. This is a spot check, not
  a measured accuracy figure.
- Unusual names, lowercase names, and names that are also common words may be missed. The cases
  we tried passed, but they do not cover everything.
- Dates of birth are not redacted (see above), and other identifiers such as medical record
  numbers or insurance IDs are not covered.
- A missed name or number (a false negative) is the serious failure, so the AI is described as
  decision support and a clinician always reviews its output. Only synthetic data is used.
## Request flow

`POST /triage` runs `redact()` first and passes **only the redacted text** to the triage client
(`app/main.py`). The service logs metadata only: the urgency, which entity types were redacted
and how long it took. Symptom text is never logged, before or after redaction. Both rules are
covered by tests in `tests/test_triage.py`.

The client comes from `TRIAGE_CLIENT`: `fake` (default, canned answers, no network) or
`azure-openai` (below).

## AI prompt (issue #8)

- **System prompt:** `app/prompts.py` (`SYSTEM_PROMPT`). It sets the role ("decision support,
  not diagnosis"), defines `routine` / `soon` / `urgent` with examples, says to choose the more
  urgent level when unsure, and tells the model to ignore redaction tokens. The JSON Schema in
  the prompt is generated from `TriageResult`, so the prompt and the validator can't drift apart.
- **User turn:** `build_user_prompt(redacted_text)` wraps the redacted text in `<<<` `>>>`.
- **Validation:** the model's reply goes through `parse_llm_output()`. Invalid output falls back
  to `soon` plus "review manually".
- **Evaluation cases:** `tests/cases.json` has 15 synthetic descriptions with the expected urgency
  (6 urgent, 5 soon, 4 routine), including stroke, self-harm, a vague message, and one with
  personal details to check that redaction runs first. An `urgent` case scored lower is the
  failure that matters most.

The prompt was first written for Gemini; it is provider-neutral and is used unchanged with
Azure OpenAI.

## AI client (`app/ai_client.py`, Azure OpenAI)

- Calls the `gpt-5-mini` deployment (`AZURE_OPENAI_DEPLOYMENT`) on the Azure OpenAI resource
  (`AZURE_OPENAI_ENDPOINT`) with the `openai` SDK: system prompt from `app/prompts.py`, JSON
  output (`response_format=json_object`). For reasoning models (gpt-5, o-series) it sets a 2,000-token
  budget with `reasoning_effort=low`; for classic chat models, temperature 0 and 512 tokens.
- **Credentials:** Microsoft Entra ID only (`DefaultAzureCredential`). On AKS that's workload
  identity; on a laptop it's `az login`. The resource has key auth turned off, and the identity
  needs the **Cognitive Services OpenAI User** role (Terraform grants it).
- Every reply goes through `parse_llm_output()`. Invalid JSON, extra fields, or a model error
  (quota, network, content filter) return the safe fallback with `fallback: true`, so an intake
  never fails because of the AI.
- Logs metadata only: the exception type, the fallback reason, the token count. Never the prompt,
  the reply or the exception message, because those can echo the patient's words.
- `POST /triage` returns `tokens_used`; the appointment service stores it in
  `triage_results.tokens_used` next to `latency_ms`.

### Evaluating against the 15 cases

```bash
cd services/triage-service
az login
AZURE_OPENAI_ENDPOINT=$(terraform -chdir=../../infra/terraform output -raw openai_endpoint) \
  python scripts/evaluate_ai.py
```

It prints expected vs actual urgency per case and exits non-zero if any `urgent` case is scored
lower. Run it after any prompt or model change.
