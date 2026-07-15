from app.agent.warranty import classify_panel_warranty


def test_cutting_cell():
    r = classify_panel_warranty("RTM123P")
    assert r == {"product_years": 10, "performance_years": 20, "output_pct_en": "≥80.7%", "output_pct_fr": "≥80,7 %", "assumed": False}


def test_full_cell():
    r = classify_panel_warranty("RT6S-M")
    assert r == {"product_years": 12, "performance_years": 25, "output_pct_en": "≥80.7%", "output_pct_fr": "≥80,7 %", "assumed": False}


def test_half_cell_documented():
    r = classify_panel_warranty("RT8K-M")
    assert r == {"product_years": 15, "performance_years": 30, "output_pct_en": "≥83%", "output_pct_fr": "≥83 %", "assumed": False}


def test_half_cell_assumed():
    r = classify_panel_warranty("RT8H-M")
    assert r["assumed"] is True
    assert r["product_years"] == 15
    assert r["performance_years"] == 30


def test_bifacial_suffix():
    r = classify_panel_warranty("RT8I-M-DG")
    assert r == {"product_years": 15, "performance_years": 30, "output_pct_en": "≥84.95%", "output_pct_fr": "≥84,95 %", "assumed": False}


def test_bifacial_assumed():
    r = classify_panel_warranty("RT8H-M-BD")
    assert r["output_pct_en"] == "≥84.95%"
    assert r["assumed"] is True


def test_none_and_empty():
    assert classify_panel_warranty(None) is None
    assert classify_panel_warranty("") is None


def test_non_panel_model():
    assert classify_panel_warranty("HH3.6KS") is None
