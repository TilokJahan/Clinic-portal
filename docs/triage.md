## PII redaction model choice

Compared en_core_web_sm and en_core_web_lg on 10 synthetic sentences
(services/triage-service/scripts/compare_models.py).

| | sm | lg |
|---|---|---|
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
| Names/phones/emails leaked | 1 | 1 |
| Useful text wrongly removed | 0 | 0 |
| Load time | 0.6 s | 2.0 s |
| Approx. image size added | ~12 MB | ~500+ MB |

**Decision:** we use en_core_web_sm because both models failed to redact the SSN but en_core_web_sm loads the file quicker.
**Known limits:** lowercase names, unusual names, SSNs are sometimes missed.
Redaction reduces risk but does not guarantee anonymity.
Fallback code is added in redacton.py to catch SSN's that presidio might fail to catch