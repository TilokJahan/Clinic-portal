"""Tests for PII redaction (app/redaction.py).

All names, phone numbers, and emails below are invented.

How to add a test case:
  * Private text that must disappear  -> add a row to MUST_REMOVE:
        (input sentence, the private text that must be gone, useful text that must remain)
  * Text with no private data that must pass through untouched -> add a row to MUST_SURVIVE.

Assumes app/redaction.py exposes redact(text) -> RedactionResult with:
  .text      the redacted string
  .entities  a list of entity TYPE names found (for example ["PERSON"]), never the raw values
"""

import pytest

from app.redaction import redact

# (sentence, private text that must be gone, clinically useful text that must remain)
MUST_REMOVE = [
    pytest.param(
        "My name is Jane Doe and I have a headache",
        "Jane Doe",
        "headache",
        id="full-name",
    ),
    pytest.param(
        "Call me at 555-123-4567 about my cough",
        "555-123-4567",
        "cough",
        id="phone-number",
    ),
    pytest.param(
        "Email me at jane.doe@example.com, my knee hurts",
        "jane.doe@example.com",
        "knee hurts",
        id="email-address",
    ),
    pytest.param(
        "Dr. Patel saw me in Detroit last week",
        "Detroit",
        "last week",
        id="location",
    ),
    pytest.param(
        "this is maria gonzalez, dizzy since monday",
        "maria gonzalez",
        "dizzy",
        id="lowercase-name",
    ),
    pytest.param(
        "My son Liam has a fever of 102",
        "Liam",
        "fever of 102",
        id="child-name-keeps-fever-number",
    ),
    pytest.param(
        "Raj Patel here, rash on my arm",
        "Raj Patel",
        "rash on my arm",
        id="name-at-start",
    ),
    pytest.param(
        "I'm Sam Lee, phone 555-987-6543, email sam.lee@example.com, sharp knee pain",
        "Sam Lee",
        "sharp knee pain",
        id="several-identifiers-at-once-name",
    ),
]

# Sentences with no private data: redaction must leave them exactly as written.
MUST_SURVIVE = [
    pytest.param("Chest pain for two days", id="duration-two-days"),
    pytest.param("I take 500 mg twice a day for back pain", id="dose-is-not-a-phone-number"),
    pytest.param("Sore throat since Tuesday, mild fever", id="weekday-kept"),
    pytest.param("Shortness of breath when climbing stairs", id="plain-symptoms"),
    pytest.param("Blood pressure was 140 over 90 this morning", id="vitals-numbers"),
]


@pytest.mark.parametrize(("text", "private", "useful"), MUST_REMOVE)
def test_private_text_is_removed_and_useful_text_kept(text, private, useful):
    result = redact(text)
    assert private.lower() not in result.text.lower(), f"leaked: {private!r} in {result.text!r}"
    assert useful.lower() in result.text.lower(), f"lost: {useful!r} from {result.text!r}"


@pytest.mark.parametrize("text", MUST_SURVIVE)
def test_text_without_private_data_is_unchanged(text):
    result = redact(text)
    assert result.text == text
    assert result.entities == []


def test_several_identifiers_in_one_message_are_all_removed():
    text = "I'm Sam Lee, phone 555-987-6543, email sam.lee@example.com, sharp knee pain"
    result = redact(text)
    assert "555-987-6543" not in result.text
    assert "sam.lee@example.com" not in result.text.lower()
    assert "PHONE_NUMBER" in result.entities
    assert "EMAIL_ADDRESS" in result.entities


def test_replacement_tokens_name_the_entity_type():
    result = redact("My name is Jane Doe and I have a headache")
    assert "<PERSON>" in result.text
    assert "PERSON" in result.entities


def test_entities_report_types_never_the_original_values():
    result = redact("My name is Jane Doe, call 555-123-4567, chest pain")
    reported = " ".join(result.entities)
    assert "Jane" not in reported
    assert "555" not in reported


def test_empty_and_whitespace_input_do_not_crash():
    assert redact("").text == ""
    assert redact("   ").entities == []


def test_long_input_does_not_crash():
    text = "I have had a headache and a cough. " * 100
    result = redact(text)
    assert "headache" in result.text
    assert "cough" in result.text


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("SSN 123-45-6789, short of breath", id="sample-style-ssn"),
        pytest.param("my ssn is 512-34-7890.", id="ssn-with-period"),
        pytest.param("ids 123-45-6789 and 987-65-4321", id="two-ssns"),
    ],
)
def test_ssn_pattern_is_removed(text):
    result = redact(text)
    assert not any(ch.isdigit() for ch in result.text.replace("<US_SSN>", ""))
    assert "US_SSN" in result.entities


def test_phone_number_is_not_mistaken_for_ssn():
    result = redact("Call me at 555-123-4567 about my cough")
    assert "US_SSN" not in result.entities
