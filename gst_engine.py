import pandas as pd
from datetime import date, datetime
from random import randint
from typing import Optional


def calculate_row_tax(turnover: float, purchase_value: float, gst_rate: float, is_inter_state: int):
    output_tax = turnover * (gst_rate / 100)
    input_tax = purchase_value * (gst_rate / 100)

    if is_inter_state:
        igst = output_tax
        cgst = 0.0
        sgst = 0.0
    else:
        cgst = output_tax / 2
        sgst = output_tax / 2
        igst = 0.0

    return {
        "output_tax": round(output_tax, 2),
        "input_tax": round(input_tax, 2),
        "cgst": round(cgst, 2),
        "sgst": round(sgst, 2),
        "igst": round(igst, 2),
    }


def build_return_dataframe(rows):
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])

    tax_cols = df.apply(
        lambda r: calculate_row_tax(r["turnover"], r["purchase_value"], r["gst_rate"], r["is_inter_state"]),
        axis=1,
        result_type="expand",
    )
    df = pd.concat([df, tax_cols], axis=1)

    df["net_tax_payable"] = (
        df["output_tax"] - df["itc_claimed"] - df["tds_received"] - df["tcs_received"]
    ).round(2)
    df["net_tax_payable"] = df["net_tax_payable"].clip(lower=0.0)

    return df


def get_year_summary(df: pd.DataFrame):
    if df.empty:
        return {
            "turnover": 0.0,
            "purchases": 0.0,
            "output_tax": 0.0,
            "itc_claimed": 0.0,
            "tds_tcs_credit": 0.0,
            "net_tax_payable": 0.0,
        }

    return {
        "turnover": round(float(df["turnover"].sum()), 2),
        "purchases": round(float(df["purchase_value"].sum()), 2),
        "output_tax": round(float(df["output_tax"].sum()), 2),
        "itc_claimed": round(float(df["itc_claimed"].sum()), 2),
        "tds_tcs_credit": round(float(df["tds_received"].sum() + df["tcs_received"].sum()), 2),
        "net_tax_payable": round(float(df["net_tax_payable"].sum()), 2),
    }


def smart_insights(df: pd.DataFrame):
    insights = []
    if df.empty:
        return ["No records yet. Add at least one monthly entry to generate smart insights."]

    missing_returns = df[
        (df["gstr1_reported"] == 0) | (df["gstr3b_reported"] == 0) | (df["gstr2a_reported"] == 0)
    ]
    if not missing_returns.empty:
        insights.append(
            f"{len(missing_returns)} month(s) have incomplete return filing flags (GSTR-1/GSTR-3B/GSTR-2A)."
        )

    high_itc = df[df["itc_claimed"] > (df["output_tax"] * 0.9)]
    if not high_itc.empty:
        insights.append(
            f"{len(high_itc)} month(s) show ITC claims above 90% of output tax. Review supporting invoices."
        )

    low_tax = df[df["net_tax_payable"] < (df["output_tax"] * 0.1)]
    if not low_tax.empty:
        insights.append(
            f"{len(low_tax)} month(s) have net GST payable below 10% of output tax after credits."
        )

    if len(df) >= 3:
        avg_last_3 = df.sort_values("month")["net_tax_payable"].tail(3).mean()
        insights.append(
            f"Predicted next-month GST payable (simple moving average): Rs. {avg_last_3:,.2f}"
        )

    if not insights:
        insights.append("Compliance appears healthy for current records.")

    return insights


def build_compliance_snapshot(df: pd.DataFrame, invoice_df: pd.DataFrame):
    snapshot = {
        "score": 100,
        "status": "Excellent",
        "pending_returns": 0,
        "risky_periods": 0,
        "duplicate_invoices": 0,
        "invoice_gstin_gaps": 0,
        "forecast_tax": 0.0,
        "alerts": [],
        "recommendations": [],
    }

    if df.empty:
        snapshot["score"] = 0
        snapshot["status"] = "No Filing Data"
        snapshot["alerts"].append("No GST return history is available yet for compliance evaluation.")
        snapshot["recommendations"].append("Prepare at least one return period to activate smart compliance tracking.")
        return snapshot

    pending_mask = (df["gstr1_reported"] == 0) | (df["gstr3b_reported"] == 0) | (df["gstr2a_reported"] == 0)
    pending_returns = int(pending_mask.sum())
    snapshot["pending_returns"] = pending_returns
    if pending_returns:
        snapshot["score"] -= min(40, pending_returns * 8)
        snapshot["alerts"].append(
            f"{pending_returns} period(s) are missing one or more return confirmations across GSTR-1, GSTR-3B or GSTR-2A."
        )
        snapshot["recommendations"].append("Close pending filing flags first to improve compliance health.")

    risky_periods = int((df["itc_claimed"] > (df["output_tax"] * 0.85)).sum() + (df["net_tax_payable"] < (df["output_tax"] * 0.1)).sum())
    snapshot["risky_periods"] = risky_periods
    if risky_periods:
        snapshot["score"] -= min(20, risky_periods * 4)
        snapshot["alerts"].append(
            "Credit utilization pattern is aggressive in one or more periods. Review ITC support and output-tax offsets."
        )
        snapshot["recommendations"].append("Reconcile ITC-ledger values with supporting invoices before final filing.")

    if len(df.index) >= 3:
        sorted_df = df.copy()
        if "month" in sorted_df.columns:
            sorted_df = sorted_df.sort_values("month")
        forecast_tax = float(sorted_df["net_tax_payable"].tail(3).mean())
    else:
        forecast_tax = float(df["net_tax_payable"].mean())
    snapshot["forecast_tax"] = round(forecast_tax, 2)

    if not invoice_df.empty:
        duplicate_invoices = int(invoice_df.duplicated(subset=["invoice_no"], keep=False).sum())
        snapshot["duplicate_invoices"] = duplicate_invoices
        if duplicate_invoices:
            snapshot["score"] -= min(20, duplicate_invoices * 3)
            snapshot["alerts"].append(
                f"{duplicate_invoices} invoice row(s) share duplicate invoice numbers. This may create reconciliation issues."
            )
            snapshot["recommendations"].append("Review duplicate invoice numbers before preparing GSTR-1.")

        gstin_gaps = int(invoice_df["counterparty_gstin"].fillna("").astype(str).str.strip().eq("").sum())
        snapshot["invoice_gstin_gaps"] = gstin_gaps
        if gstin_gaps:
            snapshot["score"] -= min(15, gstin_gaps * 2)
            snapshot["alerts"].append(
                f"{gstin_gaps} invoice row(s) are missing seller or buyer GSTIN details needed for cleaner compliance records."
            )
            snapshot["recommendations"].append("Capture missing GSTIN values in invoice entry to strengthen audit readiness.")

        if "taxable_value" in invoice_df.columns and len(invoice_df.index) >= 5:
            high_value_threshold = float(invoice_df["taxable_value"].quantile(0.9))
            high_value_count = int((invoice_df["taxable_value"] >= high_value_threshold).sum())
            snapshot["alerts"].append(
                f"{high_value_count} high-value invoice(s) fall in the top 10% bracket and should be reviewed before submission."
            )
            snapshot["recommendations"].append("Use invoice-level review for high-value transactions before generating GSTR-3B.")

    snapshot["score"] = max(0, min(100, int(round(snapshot["score"]))))

    if snapshot["score"] >= 85:
        snapshot["status"] = "Excellent"
    elif snapshot["score"] >= 70:
        snapshot["status"] = "Good"
    elif snapshot["score"] >= 50:
        snapshot["status"] = "Watchlist"
    else:
        snapshot["status"] = "High Risk"

    if not snapshot["alerts"]:
        snapshot["alerts"].append("No major compliance anomaly is detected in the current filing data.")
    if not snapshot["recommendations"]:
        snapshot["recommendations"].append("Continue monthly or quarterly reconciliation to maintain a strong compliance score.")

    return snapshot


def _fy_start_year(financial_year: str):
    try:
        parts = financial_year.replace("FY", "").strip().split("-")
        return int(parts[0])
    except (ValueError, IndexError, AttributeError):
        return datetime.now().year


def _period_end_month(period: str, filing_frequency: str):
    monthly_map = {
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
    }
    quarterly_map = {
        "Q1 (Apr-Jun)": 6,
        "Q2 (Jul-Sep)": 9,
        "Q3 (Oct-Dec)": 12,
        "Q4 (Jan-Mar)": 3,
    }
    if filing_frequency == "Quarterly":
        return quarterly_map.get(period)
    return monthly_map.get(period)


def _month_year_for_period(financial_year: str, period: str, filing_frequency: str):
    end_month = _period_end_month(period, filing_frequency)
    start_year = _fy_start_year(financial_year)
    if end_month is None:
        return start_year, 4
    year = start_year if end_month >= 4 else start_year + 1
    return year, end_month


def build_due_date_calendar(financial_year: str, filing_frequency: str, period: str):
    year, end_month = _month_year_for_period(financial_year, period, filing_frequency)
    if filing_frequency == "Quarterly":
        gstr1_due = date(year, end_month, 13)
        gstr3b_due = date(year, end_month, 22)
    else:
        next_month = 1 if end_month == 12 else end_month + 1
        next_year = year + 1 if end_month == 12 else year
        gstr1_due = date(next_year, next_month, 11)
        gstr3b_due = date(next_year, next_month, 20)

    return {
        "gstr1_due": gstr1_due,
        "gstr3b_due": gstr3b_due,
        "itc_reco_due": gstr3b_due,
    }


def estimate_late_fee(financial_year: str, filing_frequency: str, period: str, filed_at: Optional[str] = None):
    due_dates = build_due_date_calendar(financial_year, filing_frequency, period)
    gstr3b_due = due_dates["gstr3b_due"]

    if filed_at:
        try:
            filing_date = datetime.strptime(filed_at, "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            filing_date = date.today()
    else:
        filing_date = date.today()

    delay_days = max((filing_date - gstr3b_due).days, 0)
    estimated_fee = min(delay_days * 50, 10000)
    return {
        "delay_days": delay_days,
        "estimated_fee": float(estimated_fee),
        "due_date": gstr3b_due,
        "filing_date": filing_date,
    }


def build_notice_center(df: pd.DataFrame, invoice_df: pd.DataFrame, financial_year: str, filing_frequency: str):
    notices = []

    if df.empty:
        notices.append(
            {
                "priority": "High",
                "notice_type": "Registration Alert",
                "message": "No return preparation data exists yet for the selected year. Compliance monitoring is inactive.",
                "recommended_action": "Prepare the first GST period to activate compliance controls.",
            }
        )
        return notices

    for _, row in df.iterrows():
        period = row.get("month", "")
        due_dates = build_due_date_calendar(financial_year, filing_frequency, period)
        if row.get("gstr1_reported", 0) == 0:
            notices.append(
                {
                    "priority": "High",
                    "notice_type": "GSTR-1 Pending",
                    "message": f"GSTR-1 appears pending for {period}. Due date reference is {due_dates['gstr1_due'].strftime('%d %b %Y')}.",
                    "recommended_action": "Complete invoice review and mark GSTR-1 prepared before filing.",
                }
            )
        if row.get("gstr3b_reported", 0) == 0:
            late_info = estimate_late_fee(financial_year, filing_frequency, period)
            notices.append(
                {
                    "priority": "High" if late_info["delay_days"] > 0 else "Medium",
                    "notice_type": "GSTR-3B Pending",
                    "message": (
                        f"GSTR-3B is not marked complete for {period}. "
                        f"Estimated late fee exposure as of today is Rs. {late_info['estimated_fee']:,.2f}."
                    ),
                    "recommended_action": "Validate liability and file GSTR-3B to avoid further delay exposure.",
                }
            )

        if row.get("itc_claimed", 0.0) > (row.get("output_tax", 0.0) * 0.85) and row.get("output_tax", 0.0) > 0:
            notices.append(
                {
                    "priority": "Medium",
                    "notice_type": "ITC Risk",
                    "message": f"ITC claimed for {period} is unusually high compared with output tax.",
                    "recommended_action": "Reconcile ITC with supplier invoices and GSTR-2A/2B support.",
                }
            )

    if not invoice_df.empty:
        duplicate_rows = invoice_df[invoice_df.duplicated(subset=["invoice_no"], keep=False)]
        if not duplicate_rows.empty:
            notices.append(
                {
                    "priority": "Medium",
                    "notice_type": "Duplicate Invoice Check",
                    "message": f"{len(duplicate_rows.index)} invoice row(s) have duplicate invoice numbers in the selected financial year.",
                    "recommended_action": "Review duplicates before final return generation.",
                }
            )
        missing_gstin_rows = invoice_df[invoice_df["counterparty_gstin"].fillna("").astype(str).str.strip().eq("")]
        if not missing_gstin_rows.empty:
            notices.append(
                {
                    "priority": "Low",
                    "notice_type": "Invoice Data Quality",
                    "message": f"{len(missing_gstin_rows.index)} invoice row(s) are missing counterparty GSTIN details.",
                    "recommended_action": "Fill missing GSTIN values to improve return quality and audit readiness.",
                }
            )

    return notices


def build_invoice_dataframe(rows):
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    taxes = df.apply(
        lambda r: calculate_row_tax(r["taxable_value"], 0.0, r["gst_rate"], r["is_inter_state"]),
        axis=1,
        result_type="expand",
    )
    df = pd.concat([df, taxes], axis=1)
    return df


def get_gstr1_summary(invoice_df: pd.DataFrame):
    if invoice_df.empty:
        return {
            "invoice_count": 0,
            "taxable_value": 0.0,
            "output_tax": 0.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "igst": 0.0,
        }

    return {
        "invoice_count": int(len(invoice_df.index)),
        "taxable_value": round(float(invoice_df["taxable_value"].sum()), 2),
        "output_tax": round(float(invoice_df["output_tax"].sum()), 2),
        "cgst": round(float(invoice_df["cgst"].sum()), 2),
        "sgst": round(float(invoice_df["sgst"].sum()), 2),
        "igst": round(float(invoice_df["igst"].sum()), 2),
    }


def get_gstr3b_summary(invoice_df: pd.DataFrame, credit_row: Optional[pd.Series] = None):
    gstr1 = get_gstr1_summary(invoice_df)
    credit_row = credit_row if credit_row is not None else {}

    itc_claimed = float(credit_row.get("itc_claimed", 0.0) or 0.0)
    tds_received = float(credit_row.get("tds_received", 0.0) or 0.0)
    tcs_received = float(credit_row.get("tcs_received", 0.0) or 0.0)

    net_payable = max(gstr1["output_tax"] - itc_claimed - tds_received - tcs_received, 0.0)

    return {
        "outward_taxable_supplies": gstr1["taxable_value"],
        "output_tax": gstr1["output_tax"],
        "cgst": gstr1["cgst"],
        "sgst": gstr1["sgst"],
        "igst": gstr1["igst"],
        "itc_claimed": round(itc_claimed, 2),
        "tds_received": round(tds_received, 2),
        "tcs_received": round(tcs_received, 2),
        "net_tax_payable": round(net_payable, 2),
    }


def build_reconciliation_report(invoice_df: pd.DataFrame, credit_row: Optional[pd.Series] = None, filing_event=None):
    gstr1 = get_gstr1_summary(invoice_df)
    gstr3b = get_gstr3b_summary(invoice_df, credit_row)
    filing_event = dict(filing_event) if filing_event is not None else {}
    total_credit = gstr3b["itc_claimed"] + gstr3b["tds_received"] + gstr3b["tcs_received"]

    checks = [
        {
            "Check": "GSTR-1 invoice availability",
            "System Finding": f"{gstr1['invoice_count']} invoice(s) available",
            "Status": "Pass" if gstr1["invoice_count"] > 0 else "Action Required",
            "Recommended Action": "Add at least one invoice before preparing GSTR-3B." if gstr1["invoice_count"] == 0 else "No action required.",
        },
        {
            "Check": "GSTR-1 to GSTR-3B taxable value match",
            "System Finding": f"GSTR-1 taxable value equals GSTR-3B outward supplies: Rs. {gstr3b['outward_taxable_supplies']:,.2f}",
            "Status": "Pass",
            "Recommended Action": "System-populated from invoice register.",
        },
        {
            "Check": "Credit utilization reasonableness",
            "System Finding": f"Credits claimed: Rs. {total_credit:,.2f} against output tax Rs. {gstr3b['output_tax']:,.2f}",
            "Status": "Review" if total_credit > gstr3b["output_tax"] and gstr3b["output_tax"] > 0 else "Pass",
            "Recommended Action": "Review ITC/TDS/TCS support documents." if total_credit > gstr3b["output_tax"] and gstr3b["output_tax"] > 0 else "No action required.",
        },
        {
            "Check": "Cash liability computation",
            "System Finding": f"Net tax payable after credits: Rs. {gstr3b['net_tax_payable']:,.2f}",
            "Status": "Pass",
            "Recommended Action": "Proceed to challan/payment if values are confirmed.",
        },
        {
            "Check": "Filing acknowledgement",
            "System Finding": filing_event.get("ack_no") or "ARN not generated yet",
            "Status": "Filed" if filing_event.get("ack_no") else "Pending",
            "Recommended Action": "Download acknowledgement PDF." if filing_event.get("ack_no") else "Complete OTP, challan and payment flow.",
        },
    ]
    return checks


def build_auto_filing_plan(company, financial_year: str, period: str, base_taxable_value: float, gst_rate: float):
    company_name = company["company_name"]
    gstin = company["gstin"]
    state_name = company["state_name"] or company["state_code"] or "Local"
    base_taxable_value = max(float(base_taxable_value or 0.0), 10000.0)
    gst_rate = float(gst_rate or 18.0)

    invoices = [
        {
            "gstin": gstin,
            "financial_year": financial_year,
            "period": period,
            "invoice_no": f"AUTO-{period.replace(' ', '').replace('(', '').replace(')', '').replace('-', '')}-001",
            "invoice_date": datetime.now().strftime("%Y-%m-%d"),
            "doc_type": "Tax Invoice",
            "counterparty_gstin": "08AAECA0001A1Z5",
            "counterparty_name": f"{company_name} Domestic Customer",
            "place_of_supply": state_name,
            "taxable_value": round(base_taxable_value * 0.55, 2),
            "gst_rate": gst_rate,
            "is_inter_state": 0,
            "source_type": "AutoPilot",
            "note": "Auto-created outward supply invoice from automation engine.",
        },
        {
            "gstin": gstin,
            "financial_year": financial_year,
            "period": period,
            "invoice_no": f"AUTO-{period.replace(' ', '').replace('(', '').replace(')', '').replace('-', '')}-002",
            "invoice_date": datetime.now().strftime("%Y-%m-%d"),
            "doc_type": "Tax Invoice",
            "counterparty_gstin": "27AAECA0002B1Z6",
            "counterparty_name": f"{company_name} Interstate Customer",
            "place_of_supply": "Interstate",
            "taxable_value": round(base_taxable_value * 0.45, 2),
            "gst_rate": gst_rate,
            "is_inter_state": 1,
            "source_type": "AutoPilot",
            "note": "Auto-created interstate outward supply invoice from automation engine.",
        },
    ]

    estimated_output_tax = round(base_taxable_value * gst_rate / 100, 2)
    itc_claimed = round(estimated_output_tax * 0.42, 2)
    tds_received = round(estimated_output_tax * 0.03, 2)
    tcs_received = round(estimated_output_tax * 0.01, 2)

    gst_entry = {
        "gstin": gstin,
        "financial_year": financial_year,
        "month": period,
        "turnover": round(base_taxable_value, 2),
        "purchase_value": round(base_taxable_value * 0.48, 2),
        "gst_rate": gst_rate,
        "is_inter_state": 1,
        "itc_claimed": itc_claimed,
        "tds_received": tds_received,
        "tcs_received": tcs_received,
        "gstr1_reported": 1,
        "gstr3b_reported": 1,
        "gstr2a_reported": 1,
        "notes": "AutoPilot prepared return data, credit ledger and filing readiness flags.",
    }

    net_payable = max(estimated_output_tax - itc_claimed - tds_received - tcs_received, 0.0)
    return {
        "invoices": invoices,
        "gst_entry": gst_entry,
        "estimated_output_tax": estimated_output_tax,
        "estimated_net_payable": round(net_payable, 2),
        "automation_notes": [
            "Created outward supply invoices automatically.",
            "Estimated ITC, TDS and TCS credits.",
            "Prepared GSTR-1 and GSTR-3B status flags.",
            "Generated reconciliation-ready filing data.",
        ],
    }


def _safe_ratio(numerator, denominator):
    denominator = float(denominator or 0.0)
    if denominator == 0:
        return 0.0
    return round(float(numerator or 0.0) / denominator, 4)


def _score_band(score):
    if score >= 80:
        return "Critical"
    if score >= 60:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def build_ai_ml_compliance_intelligence(df: pd.DataFrame, invoice_df: pd.DataFrame, notices: list):
    features = {
        "periods_analyzed": int(len(df.index)) if not df.empty else 0,
        "invoice_count": int(len(invoice_df.index)) if not invoice_df.empty else 0,
        "total_turnover": 0.0,
        "output_tax": 0.0,
        "net_tax_payable": 0.0,
        "credit_ratio": 0.0,
        "pending_return_ratio": 0.0,
        "duplicate_invoice_ratio": 0.0,
        "missing_gstin_ratio": 0.0,
        "invoice_volatility": 0.0,
        "notice_pressure": float(len(notices)),
    }

    risk_points = 0.0
    explanations = []
    recommendations = []

    if df.empty and invoice_df.empty:
        return {
            "risk_score": 35,
            "risk_band": "Medium",
            "confidence": "Low",
            "predicted_next_liability": 0.0,
            "features": features,
            "feature_table": pd.DataFrame([features]),
            "invoice_anomalies": pd.DataFrame(),
            "explanations": ["Insufficient historical return and invoice data. Model confidence is low."],
            "recommendations": ["Run AutoPilot or add real invoices to improve ML-style prediction quality."],
            "model_cards": [
                {"Model Layer": "Data Availability", "Output": "Low confidence due to limited data"},
                {"Model Layer": "Risk Classifier", "Output": "Medium default risk until data improves"},
            ],
        }

    if not df.empty:
        total_output_tax = float(df["output_tax"].sum())
        total_credit = float(df["itc_claimed"].sum() + df["tds_received"].sum() + df["tcs_received"].sum())
        pending_mask = (df["gstr1_reported"] == 0) | (df["gstr3b_reported"] == 0) | (df["gstr2a_reported"] == 0)
        pending_ratio = _safe_ratio(int(pending_mask.sum()), len(df.index))
        credit_ratio = _safe_ratio(total_credit, total_output_tax)

        features.update(
            {
                "total_turnover": round(float(df["turnover"].sum()), 2),
                "output_tax": round(total_output_tax, 2),
                "net_tax_payable": round(float(df["net_tax_payable"].sum()), 2),
                "credit_ratio": credit_ratio,
                "pending_return_ratio": pending_ratio,
            }
        )

        if pending_ratio > 0:
            risk_points += pending_ratio * 35
            explanations.append(f"Pending filing ratio is {pending_ratio:.2f}, increasing compliance risk.")
            recommendations.append("Close pending return flags before final filing.")
        if credit_ratio > 0.85:
            risk_points += min(25, (credit_ratio - 0.85) * 80)
            explanations.append("Credit utilization is very high compared with output tax.")
            recommendations.append("Validate ITC, TDS and TCS support documents before filing.")

        sorted_df = df.copy()
        if "month" in sorted_df.columns:
            sorted_df = sorted_df.sort_values("month")
        liabilities = sorted_df["net_tax_payable"].astype(float).tail(4).tolist()
        if len(liabilities) >= 2:
            weights = list(range(1, len(liabilities) + 1))
            weighted_forecast = sum(v * w for v, w in zip(liabilities, weights)) / sum(weights)
            trend_adjustment = (liabilities[-1] - liabilities[0]) / max(len(liabilities) - 1, 1)
            predicted_next_liability = max(weighted_forecast + (trend_adjustment * 0.35), 0.0)
        else:
            predicted_next_liability = liabilities[0] if liabilities else 0.0
    else:
        predicted_next_liability = 0.0

    invoice_anomalies = pd.DataFrame()
    if not invoice_df.empty:
        invoice_work = invoice_df.copy()
        taxable_mean = float(invoice_work["taxable_value"].mean()) if "taxable_value" in invoice_work else 0.0
        taxable_std = float(invoice_work["taxable_value"].std(ddof=0)) if len(invoice_work.index) > 1 else 0.0
        if taxable_std == 0:
            invoice_work["Anomaly Score"] = 0.0
        else:
            invoice_work["Anomaly Score"] = ((invoice_work["taxable_value"] - taxable_mean).abs() / taxable_std).round(2)
        invoice_work["ML Flag"] = invoice_work["Anomaly Score"].apply(lambda score: "Review" if score >= 1.5 else "Normal")

        duplicate_ratio = _safe_ratio(int(invoice_work.duplicated(subset=["invoice_no"], keep=False).sum()), len(invoice_work.index))
        missing_ratio = _safe_ratio(
            int(invoice_work["counterparty_gstin"].fillna("").astype(str).str.strip().eq("").sum()),
            len(invoice_work.index),
        )
        volatility = _safe_ratio(taxable_std, taxable_mean)
        features.update(
            {
                "duplicate_invoice_ratio": duplicate_ratio,
                "missing_gstin_ratio": missing_ratio,
                "invoice_volatility": round(volatility, 4),
            }
        )

        if duplicate_ratio > 0:
            risk_points += duplicate_ratio * 20
            explanations.append("Duplicate invoice number pattern detected by anomaly layer.")
            recommendations.append("Review duplicate invoice numbers before return finalization.")
        if missing_ratio > 0:
            risk_points += missing_ratio * 15
            explanations.append("Some invoice rows have missing counterparty GSTIN details.")
            recommendations.append("Complete missing GSTIN values for stronger audit readiness.")
        if volatility > 0.75:
            risk_points += min(15, volatility * 8)
            explanations.append("Invoice values show high volatility, which may need pre-filing review.")
            recommendations.append("Review high-value invoices and unusual taxable-value spikes.")

        keep_cols = [
            "period",
            "invoice_no",
            "counterparty_name",
            "taxable_value",
            "gst_rate",
            "source_type",
            "Anomaly Score",
            "ML Flag",
        ]
        invoice_anomalies = invoice_work[[col for col in keep_cols if col in invoice_work.columns]]

    notice_pressure = len(notices)
    if notice_pressure:
        risk_points += min(20, notice_pressure * 3)
        explanations.append(f"{notice_pressure} smart notice(s) are active for the taxpayer.")
        recommendations.append("Resolve high-priority smart notices before filing.")

    risk_score = max(0, min(100, int(round(risk_points))))
    confidence = "High" if features["periods_analyzed"] >= 4 and features["invoice_count"] >= 6 else "Medium"
    if features["periods_analyzed"] < 2 or features["invoice_count"] < 2:
        confidence = "Low"

    if not explanations:
        explanations.append("No major anomaly detected by the local AI/ML intelligence layer.")
    if not recommendations:
        recommendations.append("Proceed with normal review and filing workflow.")

    model_cards = [
        {"Model Layer": "Feature Extraction", "Output": f"{features['periods_analyzed']} period(s), {features['invoice_count']} invoice(s) analyzed"},
        {"Model Layer": "Risk Classifier", "Output": f"{_score_band(risk_score)} risk with score {risk_score}/100"},
        {"Model Layer": "Anomaly Detection", "Output": f"{int((invoice_anomalies['ML Flag'] == 'Review').sum()) if not invoice_anomalies.empty else 0} invoice(s) flagged"},
        {"Model Layer": "Forecasting", "Output": f"Predicted next liability Rs. {predicted_next_liability:,.2f}"},
        {"Model Layer": "Explainability", "Output": "Recommendations generated from risk factors and feature weights"},
    ]

    return {
        "risk_score": risk_score,
        "risk_band": _score_band(risk_score),
        "confidence": confidence,
        "predicted_next_liability": round(float(predicted_next_liability), 2),
        "features": features,
        "feature_table": pd.DataFrame([features]),
        "invoice_anomalies": invoice_anomalies,
        "explanations": explanations,
        "recommendations": recommendations,
        "model_cards": model_cards,
    }


def answer_compliance_copilot(question: str, intelligence: dict):
    question_text = (question or "").strip().lower()
    if not question_text:
        return "Ask a question such as 'why is this taxpayer risky?', 'what should I fix first?', or 'what is the next liability forecast?'."

    if "risk" in question_text or "risky" in question_text or "score" in question_text:
        reasons = "; ".join(intelligence.get("explanations", [])[:3])
        return (
            f"The taxpayer is classified as {intelligence['risk_band']} risk with score "
            f"{intelligence['risk_score']}/100. Main reasons: {reasons}"
        )

    if "fix" in question_text or "improve" in question_text or "action" in question_text:
        actions = "; ".join(intelligence.get("recommendations", [])[:4])
        return f"Recommended improvement path: {actions}"

    if "forecast" in question_text or "next" in question_text or "liability" in question_text:
        return (
            f"The predicted next GST liability is Rs. {intelligence['predicted_next_liability']:,.2f}. "
            f"Model confidence is {intelligence['confidence']}."
        )

    if "invoice" in question_text or "anomaly" in question_text or "fraud" in question_text:
        anomaly_df = intelligence.get("invoice_anomalies", pd.DataFrame())
        flagged = int((anomaly_df["ML Flag"] == "Review").sum()) if not anomaly_df.empty else 0
        return (
            f"The anomaly layer flagged {flagged} invoice(s) for review. It checks value outliers, duplicate patterns "
            "and missing GSTIN quality indicators."
        )

    if "ai" in question_text or "ml" in question_text or "model" in question_text:
        return (
            "This layer uses explainable ML-style logic: feature extraction, weighted risk classification, statistical "
            "invoice anomaly detection, forecasting and recommendation generation. It is transparent and offline."
        )

    return (
        "The copilot analyzed the taxpayer profile, filing history, invoices and notices. For this taxpayer, focus on "
        f"{intelligence['risk_band']} risk controls, forecasted liability of Rs. {intelligence['predicted_next_liability']:,.2f}, "
        "and the recommended actions shown in the AI recommendations table."
    )


def build_auto_supporting_invoices(gstin: str, financial_year: str, period: str, credit_row: Optional[pd.Series] = None):
    credit_row = credit_row if credit_row is not None else {}
    generated = []

    if float(credit_row.get("itc_claimed", 0.0) or 0.0) > 0:
        generated.append(
            {
                "gstin": gstin,
                "financial_year": financial_year,
                "period": period,
                "invoice_no": f"ITC-{period.replace(' ', '').replace('(', '').replace(')', '').replace('/', '')}",
                "invoice_date": "2026-03-18",
                "doc_type": "System ITC Support",
                "counterparty_gstin": "SUPPORTGST0001Z5",
                "counterparty_name": "ITC Auto Support",
                "place_of_supply": "Auto",
                "taxable_value": float(credit_row.get("itc_claimed", 0.0) or 0.0),
                "gst_rate": 18.0,
                "is_inter_state": 0,
                "source_type": "Auto-ITC",
                "note": "System-generated supporting row from ITC claimed ledger.",
            }
        )

    if float(credit_row.get("tds_received", 0.0) or 0.0) > 0:
        generated.append(
            {
                "gstin": gstin,
                "financial_year": financial_year,
                "period": period,
                "invoice_no": f"TDS-{period.replace(' ', '').replace('(', '').replace(')', '').replace('/', '')}",
                "invoice_date": "2026-03-18",
                "doc_type": "System TDS Support",
                "counterparty_gstin": "SUPPORTGST0002Z5",
                "counterparty_name": "TDS Auto Support",
                "place_of_supply": "Auto",
                "taxable_value": float(credit_row.get("tds_received", 0.0) or 0.0),
                "gst_rate": 18.0,
                "is_inter_state": 0,
                "source_type": "Auto-TDS",
                "note": "System-generated supporting row from TDS credit ledger.",
            }
        )

    if float(credit_row.get("tcs_received", 0.0) or 0.0) > 0:
        generated.append(
            {
                "gstin": gstin,
                "financial_year": financial_year,
                "period": period,
                "invoice_no": f"TCS-{period.replace(' ', '').replace('(', '').replace(')', '').replace('/', '')}",
                "invoice_date": "2026-03-18",
                "doc_type": "System TCS Support",
                "counterparty_gstin": "SUPPORTGST0003Z5",
                "counterparty_name": "TCS Auto Support",
                "place_of_supply": "Auto",
                "taxable_value": float(credit_row.get("tcs_received", 0.0) or 0.0),
                "gst_rate": 18.0,
                "is_inter_state": 0,
                "source_type": "Auto-TCS",
                "note": "System-generated supporting row from TCS credit ledger.",
            }
        )

    return generated


def generate_otp():
    return str(randint(100000, 999999))


def generate_reference(prefix: str):
    return f"{prefix}{randint(10000000, 99999999)}"
