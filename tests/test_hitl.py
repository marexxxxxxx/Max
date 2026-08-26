from max.router.hitl import HITL_QUESTION, is_confirmation


def test_yes_variants():
    assert is_confirmation("Ja")
    assert is_confirmation("ja, bitte")
    assert is_confirmation("Yes")
    assert is_confirmation("Natürlich")


def test_no_variants():
    assert not is_confirmation("Nein")
    assert not is_confirmation("nein, lass ihn aus")
    assert not is_confirmation("")
    assert not is_confirmation(None)


def test_question_is_german():
    assert "Server 2" in HITL_QUESTION


def test_stt_variants_are_confirmations():
    assert is_confirmation("jaja")
    assert is_confirmation("ja, ja")


def test_negation_after_yes_rejects():
    assert not is_confirmation("Ja, aber lass ihn aus")
    assert not is_confirmation("ja, nicht")
    assert not is_confirmation("ja, nein")
