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
