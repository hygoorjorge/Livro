from app.services.mention_detector import find_candidates


def test_detects_plp_with_year():
    text = "Conforme o PLP 108/2024, o Comitê Gestor do IBS terá..."
    cands = find_candidates(text)
    assert any(c.detected_ref == "PLP 108/2024" for c in cands)


def test_detects_full_form():
    text = "O Projeto de Lei Complementar nº 68 foi convertido em LC 214/2025."
    cands = find_candidates(text)
    refs = [c.detected_ref for c in cands]
    assert "PLP 68" in refs


def test_historical_hint_flagged():
    text = "Durante a tramitação do PLP 108, debateu-se a estrutura do IBS."
    cands = find_candidates(text)
    assert cands and cands[0].has_historical_hint_nearby


def test_dedupe_overlapping():
    text = "O PLP 108 e o PL 12345 mencionam pontos similares."
    cands = find_candidates(text)
    refs = sorted(c.detected_ref for c in cands)
    assert "PLP 108" in refs
    assert "PL 12345" in refs
    assert len(set(refs)) == len(refs)
