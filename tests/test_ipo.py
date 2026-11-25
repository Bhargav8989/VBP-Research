from app.services.ipo import analyze_ipo_report


def test_strong_mainboard_ipo_report():
    report = analyze_ipo_report(
        {
            "company_name": "Good Growth Tech Ltd",
            "segment": "MAINBOARD",
            "price_max": 200,
            "lot_size": 75,
            "issue_size_cr": 500,
            "fresh_issue_pct": 85,
            "eps": 10.0,
            "rev_fy1": 200,
            "rev_fy2": 260,
            "rev_fy3": 350,
            "pat_fy1": 25,
            "pat_fy2": 34,
            "pat_fy3": 48,
            "net_worth_cr": 200,
            "total_debt_cr": 30,
            "sub_qib": 35.0,
            "sub_nii": 20.0,
            "sub_retail": 12.0,
            "sub_total": 22.0,
            "peer_median_pe": 30.0,
        }
    )

    assert report["segment"] == "MAINBOARD"
    assert report["valuation"]["ipo_pe"] == 20.0
    assert report["valuation"]["valuation_tag"] == "Undervalued"
    assert report["valuation"]["implied_fair_price"] == 300.0
    assert report["valuation"]["min_investment"] == 15000
    assert report["fundamentals"]["margin_spike_flag"] is False
    assert report["scores"]["overall"] >= 80
    assert "Strong Listing" in report["verdict"]["listing"]
    assert "Good for Long Term" in report["verdict"]["long_term"]
    lp = report["listing_prediction"]
    assert lp["available"] is True
    assert lp["est_low"] > 200
    assert lp["gain_mid_pct"] > 15
    assert lp["lot_profit_mid"] > 0


def test_risky_sme_ipo_detects_red_flags():
    report = analyze_ipo_report(
        {
            "company_name": "Risky SME Ltd",
            "segment": "SME",
            "price_max": 120,
            "lot_size": 1200,
            "issue_size_cr": 35,
            "fresh_issue_pct": 30,  # 70% OFS
            "eps": 2.0,
            "rev_fy1": 50,
            "rev_fy2": 55,
            "rev_fy3": 60,
            "pat_fy1": 2.0,   # 4.0% margin
            "pat_fy2": 2.5,   # 4.5% margin
            "pat_fy3": 9.0,   # 15.0% margin -> >2x spike!
            "net_worth_cr": 20,
            "total_debt_cr": 40,  # D/E = 2.0x
            "sub_qib": 0.8,
            "sub_retail": 18.0,   # Retail trap
            "peer_median_pe": 25.0,
        }
    )

    assert report["segment"] == "SME"
    assert report["valuation"]["ipo_pe"] == 60.0
    assert report["valuation"]["valuation_tag"] == "Expensive"
    assert report["fundamentals"]["margin_spike_flag"] is True
    assert report["scores"]["overall"] < 40
    risks_joined = " ".join(report["risks"]).lower()
    assert "profit jump" in risks_joined
    assert "offer for sale" in risks_joined
    assert "retail trap" in risks_joined
    assert "sme ipo risk" in risks_joined
