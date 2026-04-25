from __future__ import annotations

from db import add_invoice_entry, company_exists, insert_company, upsert_gst_entry


PUBLIC_COMPANY_DEMOS = [
    {
        "company_name": "Reliance Industries Limited",
        "trade_name": "Reliance Industries",
        "ticker": "RELIANCE.NS",
        "gstin": "27AABCR1718E1ZV",
        "state_code": "27",
        "state_name": "Maharashtra",
        "business_type": "Public Limited Company",
        "filing_frequency": "Monthly",
        "registration_status": "Active",
        "principal_place": "Mumbai, Maharashtra",
        "auth_signatory": "Mukesh D. Ambani",
        "financial_year": "FY 2024-25",
        "months": [
            ("Apr", 2280000000, 1670000000, 126000000, 12000000, 5000000, 1, 1, 1),
            ("May", 2310000000, 1705000000, 128500000, 11000000, 5200000, 1, 1, 1),
            ("Jun", 2260000000, 1660000000, 121000000, 11800000, 5100000, 1, 1, 1),
            ("Jul", 2390000000, 1765000000, 135500000, 11900000, 5200000, 1, 1, 1),
        ],
        "invoices": [
            ("Apr", "RIL-APR-001", "2025-04-09", "27AAACR5055K1Z8", "Alpha Retail LLP", 8400000, 18.0, 0),
            ("Apr", "RIL-APR-002", "2025-04-15", "29AAECT1001N1Z1", "Tech Hub India", 6200000, 18.0, 1),
            ("May", "RIL-MAY-001", "2025-05-07", "24AAACE2035Q1ZV", "Energy Connect Pvt Ltd", 7600000, 18.0, 0),
            ("Jun", "RIL-JUN-001", "2025-06-19", "07AADCB2230M1ZU", "Metro Infra Traders", 7100000, 18.0, 1),
        ],
    },
    {
        "company_name": "Infosys Limited",
        "trade_name": "Infosys",
        "ticker": "INFY.NS",
        "gstin": "29AAACI1195H1ZK",
        "state_code": "29",
        "state_name": "Karnataka",
        "business_type": "Public Limited Company",
        "filing_frequency": "Monthly",
        "registration_status": "Active",
        "principal_place": "Bengaluru, Karnataka",
        "auth_signatory": "Salil S. Parekh",
        "financial_year": "FY 2024-25",
        "months": [
            ("Apr", 563000000, 118000000, 31200000, 1800000, 900000, 1, 1, 1),
            ("May", 578000000, 122000000, 32900000, 1900000, 950000, 1, 1, 1),
            ("Jun", 571000000, 119500000, 32100000, 1850000, 975000, 1, 1, 1),
            ("Jul", 589000000, 124000000, 33600000, 1950000, 980000, 1, 1, 1),
        ],
        "invoices": [
            ("Apr", "INFY-APR-001", "2025-04-05", "29AADCT2010R1ZX", "Cloud Shift Solutions", 2450000, 18.0, 0),
            ("Apr", "INFY-APR-002", "2025-04-18", "27AAECS4900L1ZH", "Data Edge Systems", 1980000, 18.0, 1),
            ("May", "INFY-MAY-001", "2025-05-12", "33AAACH4444Q1ZQ", "Northstar Analytics", 2260000, 18.0, 0),
            ("Jun", "INFY-JUN-001", "2025-06-24", "06AACCP9999H1ZZ", "Digital Process Labs", 2410000, 18.0, 1),
        ],
    },
]


def seed_demo_workspace():
    inserted = 0
    for company in PUBLIC_COMPANY_DEMOS:
        if not company_exists(company["gstin"]):
            insert_company(
                company_name=company["company_name"],
                ticker=company["ticker"],
                gstin=company["gstin"],
                state_code=company["state_code"],
                trade_name=company["trade_name"],
                business_type=company["business_type"],
                state_name=company["state_name"],
                filing_frequency=company["filing_frequency"],
                registration_status=company["registration_status"],
                principal_place=company["principal_place"],
                auth_signatory=company["auth_signatory"],
            )
            inserted += 1

        for month, turnover, purchase_value, itc_claimed, tds_received, tcs_received, g1, g3, g2 in company["months"]:
            upsert_gst_entry(
                {
                    "gstin": company["gstin"],
                    "financial_year": company["financial_year"],
                    "month": month,
                    "turnover": turnover,
                    "purchase_value": purchase_value,
                    "gst_rate": 18.0,
                    "is_inter_state": 0,
                    "itc_claimed": itc_claimed,
                    "tds_received": tds_received,
                    "tcs_received": tcs_received,
                    "gstr1_reported": g1,
                    "gstr3b_reported": g3,
                    "gstr2a_reported": g2,
                    "notes": "Board review dataset based on public listed company profile and demo filing values.",
                }
            )

        for period, invoice_no, invoice_date, counterparty_gstin, counterparty_name, taxable_value, gst_rate, inter_state in company["invoices"]:
            add_invoice_entry(
                {
                    "gstin": company["gstin"],
                    "financial_year": company["financial_year"],
                    "period": period,
                    "invoice_no": invoice_no,
                    "invoice_date": invoice_date,
                    "doc_type": "Tax Invoice",
                    "counterparty_gstin": counterparty_gstin,
                    "counterparty_name": counterparty_name,
                    "place_of_supply": company["state_name"],
                    "taxable_value": taxable_value,
                    "gst_rate": gst_rate,
                    "is_inter_state": inter_state,
                    "source_type": "Manual",
                    "note": "Demo invoice seeded for major project presentation.",
                }
            )

    return inserted
