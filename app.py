from __future__ import annotations

from io import BytesIO
from datetime import datetime
import secrets

import pandas as pd
import plotly.express as px
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
import streamlit as st

from auth import hash_password, verify_password
from company_api import fetch_public_company_financials
from db import (
    add_invoice_entry,
    create_auth_session,
    create_user,
    delete_auth_session,
    get_auth_session,
    get_company_by_gstin,
    get_companies,
    get_gst_entries,
    get_filing_event,
    get_invoice_entries,
    get_user_by_username,
    init_db,
    insert_company,
    record_filing_event,
    update_user_linked_gstin,
    upsert_gst_entry,
)
from demo_data import seed_demo_workspace
from govt_api import get_gstn_integration_status
from gst_engine import (
    build_auto_supporting_invoices,
    build_compliance_snapshot,
    build_due_date_calendar,
    build_auto_filing_plan,
    build_ai_ml_compliance_intelligence,
    build_invoice_dataframe,
    build_notice_center,
    build_reconciliation_report,
    build_return_dataframe,
    estimate_late_fee,
    answer_compliance_copilot,
    generate_otp,
    generate_reference,
    get_gstr1_summary,
    get_gstr3b_summary,
    get_year_summary,
    smart_insights,
)
from validators import validate_gstin

st.set_page_config(page_title="Smart GST & Compliance Management Portal", layout="wide")
init_db()
APP_BASE_URL = "http://127.0.0.1:8501"


def money(value):
    return f"Rs. {float(value):,.2f}"


def compact_money(value):
    value = float(value)
    if value >= 1_00_00_00_000:
        return f"Rs. {value / 1_00_00_00_000:.2f} Cr"
    if value >= 1_00_000:
        return f"Rs. {value / 1_00_000:.2f} L"
    return money(value)


def financial_year_options():
    current_year = datetime.now().year
    return [f"FY {year}-{str(year + 1)[-2:]}" for year in range(current_year - 5, current_year + 1)][::-1]


def monthly_periods():
    return ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]


def quarterly_periods():
    return ["Q1 (Apr-Jun)", "Q2 (Jul-Sep)", "Q3 (Oct-Dec)", "Q4 (Jan-Mar)"]


def period_options(filing_frequency):
    return quarterly_periods() if filing_frequency == "Quarterly" else monthly_periods()


def period_order_map():
    order = {}
    for idx, item in enumerate(monthly_periods()):
        order[item] = idx
    for idx, item in enumerate(quarterly_periods()):
        order[item] = idx
    return order


def sort_period_df(df):
    if df.empty:
        return df
    period_map = period_order_map()
    ordered = df.copy()
    ordered["_period_order"] = ordered["month"].map(period_map).fillna(99)
    ordered = ordered.sort_values("_period_order").drop(columns="_period_order")
    return ordered


def get_selected_company(companies_df, select_key, label):
    company_map = {f'{row["company_name"]} ({row["gstin"]})': row for _, row in companies_df.iterrows()}
    shared_label = st.session_state.get("shared_company_label")
    options = list(company_map.keys())
    index = options.index(shared_label) if shared_label in options else 0
    selected_label = st.selectbox(label, options, key=select_key, index=index)
    return company_map[selected_label]


def get_credit_row(gstin, financial_year, period):
    credit_df = build_return_dataframe(get_gst_entries(gstin, financial_year))
    if credit_df.empty:
        return None
    period_df = credit_df[credit_df["month"] == period]
    if period_df.empty:
        return None
    return period_df.iloc[-1]


def get_shared_fy_index():
    years = financial_year_options()
    shared_year = st.session_state.get("shared_financial_year")
    return years.index(shared_year) if shared_year in years else 0


def get_shared_period_index(filing_frequency):
    periods = period_options(filing_frequency)
    shared_period = st.session_state.get("shared_period")
    return periods.index(shared_period) if shared_period in periods else 0


def build_acknowledgement_payload(company, financial_year, period, filing_event, summary, signatory_name):
    filing_event = dict(filing_event) if filing_event is not None else {}
    return [
        ("GSTIN / UIN of Taxpayer", company["gstin"]),
        ("Legal Name", company["company_name"]),
        ("Trade Name", company.get("trade_name") or company["company_name"]),
        ("Return Type", "GSTR-3B"),
        ("Financial Year", financial_year),
        ("Tax Period", period),
        ("ARN", filing_event["ack_no"] or "Pending"),
        ("Challan Identification No. (CIN/CPIN)", filing_event["challan_no"] or "Pending"),
        ("Payment Mode", filing_event["payment_mode"] or "Not selected"),
        ("Payment Status", filing_event["payment_status"] or "Pending"),
        ("Net Tax Payable", money(summary["net_tax_payable"])),
        ("Filed On", filing_event["filed_at"] or "Pending"),
        ("Authorized Signatory", signatory_name or company.get("auth_signatory") or "Not captured"),
        ("Registered Mobile", filing_event.get("registered_mobile") or "Not available"),
    ]


def _draw_wrapped_text(pdf, text, x_pos, y_pos, max_width, font_name="Helvetica", font_size=10, leading=14):
    words = str(text).split()
    if not words:
        pdf.drawString(x_pos, y_pos, "")
        return y_pos - leading

    line = words[0]
    current_y = y_pos
    for word in words[1:]:
        trial = f"{line} {word}"
        if stringWidth(trial, font_name, font_size) <= max_width:
            line = trial
        else:
            pdf.drawString(x_pos, current_y, line)
            current_y -= leading
            line = word
    pdf.drawString(x_pos, current_y, line)
    return current_y - leading


def build_acknowledgement_pdf(company, financial_year, period, filing_event, summary, signatory_name):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pdf.setStrokeColor(colors.HexColor("#CBD5E1"))
    pdf.setLineWidth(1)
    pdf.rect(14 * mm, 14 * mm, width - 28 * mm, height - 28 * mm, stroke=1, fill=0)

    pdf.setFillColor(colors.HexColor("#0F172A"))
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(22 * mm, height - 26 * mm, "Goods and Services Tax")
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(22 * mm, height - 34 * mm, "Return Filing Acknowledgement")
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#475569"))
    pdf.drawString(22 * mm, height - 41 * mm, "Portal acknowledgement generated for taxpayer filing records")

    pdf.setStrokeColor(colors.HexColor("#0F4C81"))
    pdf.setLineWidth(2)
    pdf.line(22 * mm, height - 46 * mm, width - 22 * mm, height - 46 * mm)

    top_y = height - 60 * mm
    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(colors.HexColor("#0F172A"))
    pdf.drawString(22 * mm, top_y, "Acknowledgement Reference Number (ARN)")
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawRightString(width - 22 * mm, top_y, filing_event["ack_no"] or "Pending")

    rows = build_acknowledgement_payload(company, financial_year, period, filing_event, summary, signatory_name)
    y_pos = top_y - 10 * mm
    label_x = 22 * mm
    value_x = 88 * mm
    row_height = 10 * mm

    for label, value in rows:
        if y_pos < 48 * mm:
            pdf.showPage()
            y_pos = height - 30 * mm
            pdf.setFont("Helvetica", 10)
            pdf.setFillColor(colors.HexColor("#0F172A"))
        pdf.setStrokeColor(colors.HexColor("#E2E8F0"))
        pdf.line(22 * mm, y_pos + 2 * mm, width - 22 * mm, y_pos + 2 * mm)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.setFillColor(colors.HexColor("#334155"))
        pdf.drawString(label_x, y_pos - 2 * mm, str(label))
        pdf.setFont("Helvetica", 10)
        pdf.setFillColor(colors.HexColor("#0F172A"))
        next_y = _draw_wrapped_text(pdf, value, value_x, y_pos - 2 * mm, width - value_x - 22 * mm)
        y_pos = min(y_pos - row_height, next_y - 3 * mm)

    box_y = max(30 * mm, y_pos - 8 * mm)
    pdf.setFillColor(colors.whitesmoke)
    pdf.setStrokeColor(colors.HexColor("#CBD5E1"))
    pdf.roundRect(22 * mm, box_y, width - 44 * mm, 18 * mm, 3 * mm, stroke=1, fill=1)
    pdf.setFillColor(colors.HexColor("#0F172A"))
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(26 * mm, box_y + 11 * mm, "Digital Signature Declaration")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(
        26 * mm,
        box_y + 5 * mm,
        "This acknowledgement has been approved through OTP validation and authorized signatory confirmation.",
    )

    footer_y = 20 * mm
    pdf.setStrokeColor(colors.HexColor("#E2E8F0"))
    pdf.line(22 * mm, footer_y + 6 * mm, width - 22 * mm, footer_y + 6 * mm)
    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(colors.HexColor("#64748B"))
    pdf.drawString(22 * mm, footer_y, "This document is generated for academic demonstration of GST return workflow.")
    pdf.drawRightString(width - 22 * mm, footer_y, datetime.now().strftime("%d-%m-%Y %H:%M:%S"))

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


def render_acknowledgement_preview(company, financial_year, period, filing_event, summary, signatory_name, title):
    payload = build_acknowledgement_payload(company, financial_year, period, filing_event, summary, signatory_name)
    rows_html = "".join(
        f"<div class='ack-line'><div class='ack-label'>{label}</div><div class='ack-value'>{value}</div></div>"
        for label, value in payload
    )
    st.markdown(
        f"""
        <div class="ack-preview-wrap">
          <div class="ack-preview-page">
            <div class="ack-preview-topline">Goods and Services Tax</div>
            <div class="ack-preview-title">{title}</div>
            <div class="ack-preview-subtitle">Generated acknowledgement for taxpayer filing records</div>
            <div class="ack-arn-band">
              <span>Acknowledgement Reference Number (ARN)</span>
              <strong>{filing_event['ack_no'] or 'Pending'}</strong>
            </div>
            <div class="ack-lines">
              {rows_html}
            </div>
            <div class="ack-sign-block">
              <div class="ack-sign-title">Digital Signature Declaration</div>
              <div class="ack-sign-copy">OTP verification and authorized signatory confirmation have been captured for this filing.</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_portal_header(title, subtitle, path_text):
    st.markdown(
        f"""
        <div class="card">
          <div class="mono">{path_text}</div>
          <div class="section-title" style="margin-top: 8px;">{title}</div>
          <div class="section-copy">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def go_to_page(page_name):
    st.session_state["active_portal_page"] = page_name
    st.rerun()


def set_my_filing_step(step_name):
    st.session_state["my_flow_step_current"] = step_name
    st.rerun()


def go_to_return_page(page_name, company, financial_year, period):
    st.session_state["active_portal_page"] = page_name
    st.session_state["shared_company_label"] = f'{company["company_name"]} ({company["gstin"]})'
    st.session_state["shared_financial_year"] = financial_year
    st.session_state["shared_period"] = period
    st.rerun()


def render_return_navigation(company, financial_year, period, prefix):
    nav1, nav2, nav3 = st.columns(3)
    with nav1:
        if st.button("Back to Returns Dashboard", key=f"{prefix}_back_dashboard", use_container_width=True):
            go_to_return_page("Returns Dashboard", company, financial_year, period)
    with nav2:
        if st.button("Open GSTR-1", key=f"{prefix}_open_gstr1", use_container_width=True):
            go_to_return_page("GSTR-1", company, financial_year, period)
    with nav3:
        if st.button("Open GSTR-3B / Filing", key=f"{prefix}_open_gstr3b", use_container_width=True):
            go_to_return_page("GSTR-3B", company, financial_year, period)


def status_class(label):
    if label in {"Ready", "Paid and Filed", "Filed"}:
        return "status-good"
    if label in {"Pending", "Not Filed", "OTP Sent", "Challan Generated"}:
        return "status-warn"
    return "status-bad"


def render_shell_styles():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap');
        html, body, [class*="css"] {font-family: 'Manrope', sans-serif;}
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(15,118,110,0.14), transparent 26%),
                radial-gradient(circle at top right, rgba(194,133,29,0.16), transparent 18%),
                linear-gradient(180deg, #f5f7fb 0%, #edf2f7 100%);
        }
        .block-container {padding-top: 1.3rem; padding-bottom: 2rem;}
        .hero {
            background: linear-gradient(135deg, rgba(15,118,110,0.96), rgba(15,76,129,0.96));
            border-radius: 24px;
            padding: 28px 30px;
            color: #fff;
            box-shadow: 0 20px 60px rgba(15, 23, 42, 0.14);
            margin-bottom: 18px;
        }
        .hero-title {font-size: 34px; font-weight: 800; line-height: 1.08; margin: 0;}
        .hero-copy {margin-top: 10px; max-width: 860px; line-height: 1.6; font-size: 14px; opacity: 0.95;}
        .hero-grid {display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 18px;}
        .hero-stat {background: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.14); border-radius: 16px; padding: 14px 16px;}
        .hero-stat span {display: block; font-size: 12px; opacity: 0.82; margin-bottom: 6px;}
        .hero-stat strong {font-size: 20px; font-weight: 800;}
        .card {
            background: rgba(255,255,255,0.82);
            border: 1px solid rgba(15,23,42,0.08);
            border-radius: 18px;
            padding: 18px;
            box-shadow: 0 14px 50px rgba(15, 23, 42, 0.06);
            margin-bottom: 14px;
        }
        .section-title {font-size: 18px; font-weight: 800; color: #0f172a; margin-bottom: 10px;}
        .section-copy {font-size: 13px; color: #475569; line-height: 1.6;}
        .profile-title {font-size: 24px; font-weight: 800; color: #0f172a; margin-bottom: 6px;}
        .profile-copy {font-size: 13px; color: #475569; margin-bottom: 14px;}
        .profile-grid {display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px;}
        .profile-item {background: rgba(255,255,255,0.78); border: 1px solid rgba(15,23,42,0.08); border-radius: 14px; padding: 12px;}
        .profile-item span {display: block; font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; margin-bottom: 6px;}
        .profile-item strong {color: #0f172a; font-size: 14px;}
        .status-pill {display: inline-flex; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700;}
        .status-good {background: rgba(6,118,99,0.10); color: #047857;}
        .status-warn {background: rgba(194,133,29,0.12); color: #a16207;}
        .status-bad {background: rgba(180,35,24,0.10); color: #b42318;}
        .auth-shell {max-width: 980px; margin: 0 auto;}
        .mono {font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: #0f4c81;}
        .return-tile {
            border-radius: 18px;
            padding: 16px;
            min-height: 168px;
            color: #ffffff;
            box-shadow: 0 18px 40px rgba(15, 23, 42, 0.12);
            margin-bottom: 10px;
        }
        .tile-gstr1 {background: linear-gradient(135deg, #0f766e, #115e59);}
        .tile-gstr3b {background: linear-gradient(135deg, #0f4c81, #1d4ed8);}
        .tile-credit {background: linear-gradient(135deg, #9a6700, #c2851d);}
        .tile-payment {background: linear-gradient(135deg, #7c2d12, #b42318);}
        .tile-title {font-size: 18px; font-weight: 800; margin-bottom: 6px;}
        .tile-copy {font-size: 13px; opacity: 0.92; line-height: 1.5;}
        .tile-badge {
            display: inline-block;
            margin-top: 10px;
            padding: 4px 10px;
            border-radius: 999px;
            background: rgba(255,255,255,0.18);
            font-size: 11px;
            font-weight: 700;
        }
        .ack-shell {
            background: #ffffff;
            border: 1px solid rgba(15,23,42,0.10);
            border-radius: 18px;
            padding: 20px;
            box-shadow: 0 18px 40px rgba(15,23,42,0.06);
        }
        .ack-head {
            font-size: 20px;
            font-weight: 800;
            color: #0f172a;
            margin-bottom: 8px;
        }
        .ack-row {
            display: flex;
            justify-content: space-between;
            border-bottom: 1px solid rgba(15,23,42,0.06);
            padding: 10px 0;
            font-size: 14px;
            color: #334155;
        }
        .ack-preview-wrap {
            padding: 6px 0;
        }
        .ack-preview-page {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 10px;
            padding: 26px 28px;
            box-shadow: 0 10px 30px rgba(15,23,42,0.08);
            max-width: 820px;
            min-height: 1020px;
            margin: 0 auto;
        }
        .ack-preview-topline {
            font-size: 14px;
            font-weight: 700;
            color: #0f172a;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }
        .ack-preview-title {
            font-size: 26px;
            font-weight: 800;
            color: #0f172a;
            margin-top: 8px;
        }
        .ack-preview-subtitle {
            font-size: 13px;
            color: #475569;
            margin-top: 4px;
            padding-bottom: 14px;
            border-bottom: 2px solid #0f4c81;
        }
        .ack-arn-band {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #f8fafc;
            border: 1px solid #dbe4ee;
            border-radius: 10px;
            padding: 14px 16px;
            margin-top: 18px;
            color: #0f172a;
        }
        .ack-arn-band span {
            font-size: 12px;
            color: #475569;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .ack-arn-band strong {
            font-size: 17px;
            font-weight: 800;
        }
        .ack-lines {
            margin-top: 18px;
            border-top: 1px solid #e2e8f0;
        }
        .ack-line {
            display: grid;
            grid-template-columns: 280px 1fr;
            gap: 18px;
            border-bottom: 1px solid #e2e8f0;
            padding: 14px 0;
        }
        .ack-label {
            font-size: 13px;
            font-weight: 700;
            color: #334155;
        }
        .ack-value {
            font-size: 13px;
            color: #0f172a;
            word-break: break-word;
        }
        .ack-sign-block {
            margin-top: 24px;
            padding: 16px 18px;
            border: 1px solid #cbd5e1;
            border-radius: 10px;
            background: #f8fafc;
        }
        .ack-sign-title {
            font-size: 13px;
            font-weight: 800;
            color: #0f172a;
            margin-bottom: 4px;
        }
        .ack-sign-copy {
            font-size: 12px;
            color: #475569;
            line-height: 1.6;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_profile(company):
    st.markdown(
        f"""
        <div class="card">
          <div class="profile-title">{company["company_name"]}</div>
          <div class="profile-copy">GSTIN {company["gstin"]} • {company["state_name"] or company["state_code"]} • {company["business_type"] or "Registered Taxpayer"}</div>
          <div class="profile-grid">
            <div class="profile-item"><span>Trade Name</span><strong>{company["trade_name"] or company["company_name"]}</strong></div>
            <div class="profile-item"><span>Registration Status</span><strong>{company["registration_status"] or "Active"}</strong></div>
            <div class="profile-item"><span>Filing Frequency</span><strong>{company["filing_frequency"] or "Monthly"}</strong></div>
            <div class="profile-item"><span>Principal Place</span><strong>{company["principal_place"] or "Not updated"}</strong></div>
            <div class="profile-item"><span>Authorized Signatory</span><strong>{company["auth_signatory"] or "Not updated"}</strong></div>
            <div class="profile-item"><span>Market Ticker</span><strong>{company["ticker"] or "Manual account"}</strong></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def auth_view():
    st.markdown('<div class="auth-shell">', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="hero">
          <p class="hero-title">Smart GST & Compliance Management Portal</p>
          <div class="hero-copy">
            Secure taxpayer workspace for GSTR-1, GSTR-3B, GSTR-2A, ITC, TDS/TCS tracking,
            public-company financial enrichment and filing-period reporting.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    sign_in_tab, sign_up_tab = st.tabs(["Sign In", "Sign Up"])

    with sign_in_tab:
        st.markdown('<div class="card"><div class="section-title">User Sign In</div>', unsafe_allow_html=True)
        with st.form("sign_in_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In", use_container_width=True)
        if submitted:
            user = get_user_by_username(username.strip())
            if not user or not verify_password(password, user["password_hash"]):
                st.error("Invalid username or password.")
            else:
                auth_token = secrets.token_urlsafe(24)
                create_auth_session(auth_token, user["username"])
                st.session_state["auth_user"] = {
                    "username": user["username"],
                    "full_name": user["full_name"] or user["username"],
                    "role": user["role"],
                    "linked_gstin": user["linked_gstin"],
                }
                st.session_state["auth_token"] = auth_token
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with sign_up_tab:
        st.markdown('<div class="card"><div class="section-title">Create Portal Account</div>', unsafe_allow_html=True)
        with st.form("sign_up_form"):
            full_name = st.text_input("Full Name")
            username = st.text_input("Username", key="signup_username")
            password = st.text_input("Password", type="password", key="signup_password")
            confirm_password = st.text_input("Confirm Password", type="password")
            role = st.selectbox("Role", ["Taxpayer", "Accounts Manager", "Compliance Officer"])
            submitted = st.form_submit_button("Create Account", use_container_width=True)
        if submitted:
            if not username.strip() or not password:
                st.error("Username and password are required.")
            elif password != confirm_password:
                st.error("Passwords do not match.")
            elif get_user_by_username(username.strip()):
                st.error("Username already exists.")
            else:
                create_user(
                    username=username.strip(),
                    password_hash=hash_password(password),
                    full_name=full_name.strip(),
                    role=role,
                )
                st.success("Account created. Sign in with your new credentials.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


def portfolio_metrics(companies_df):
    total_entities = len(companies_df.index)
    active_registrations = int((companies_df["registration_status"] == "Active").sum()) if not companies_df.empty else 0
    quarterly_entities = int((companies_df["filing_frequency"] == "Quarterly").sum()) if not companies_df.empty else 0
    return total_entities, active_registrations, quarterly_entities


render_shell_styles()

companies = get_companies()
if not companies:
    seed_demo_workspace()
    companies = get_companies()

query_params = st.query_params
auth_token_param = query_params.get("auth_token")

if "auth_user" not in st.session_state and auth_token_param:
    auth_session = get_auth_session(auth_token_param)
    if auth_session:
        user = get_user_by_username(auth_session["username"])
        if user:
            st.session_state["auth_user"] = {
                "username": user["username"],
                "full_name": user["full_name"] or user["username"],
                "role": user["role"],
                "linked_gstin": user["linked_gstin"],
            }
            st.session_state["auth_token"] = auth_token_param

if "auth_user" not in st.session_state:
    auth_view()
    st.stop()

companies_df = pd.DataFrame([dict(row) for row in companies]) if companies else pd.DataFrame()
integration_status = get_gstn_integration_status()
total_entities, active_registrations, quarterly_entities = portfolio_metrics(companies_df)

if query_params.get("portal_page"):
    st.session_state["active_portal_page"] = query_params["portal_page"]
if query_params.get("company"):
    st.session_state["shared_company_label"] = query_params["company"]
if query_params.get("financial_year"):
    st.session_state["shared_financial_year"] = query_params["financial_year"]
if query_params.get("period"):
    st.session_state["shared_period"] = query_params["period"]

with st.sidebar:
    st.markdown(f"**User**: {st.session_state['auth_user']['full_name']}")
    st.markdown(f"**Role**: {st.session_state['auth_user']['role']}")
    if st.button("Log Out", use_container_width=True):
        if st.session_state.get("auth_token"):
            delete_auth_session(st.session_state["auth_token"])
        st.session_state.pop("auth_token", None)
        st.session_state.pop("auth_user", None)
        st.rerun()
    st.markdown("---")
    st.markdown("**GSTN Integration**")
    st.caption(integration_status["status_text"])
    if integration_status["configured"]:
        st.success("Credential placeholders detected")
    else:
        st.warning("Local filing mode")
    st.markdown("---")
    navigation_pages = [
        "My GST Filing",
        "Dashboard",
        "Returns Dashboard",
        "Automation Center",
        "AI/ML Intelligence",
        "Taxpayer Master",
        "Public Company API",
        "Credit Ledger",
        "GSTR-1",
        "GSTR-3B",
        "Filing & Payment",
        "Smart Insights",
        "GSTN Integration",
    ]
    if "active_portal_page" not in st.session_state:
        st.session_state["active_portal_page"] = "My GST Filing"
    if st.session_state["active_portal_page"] not in navigation_pages:
        st.session_state["active_portal_page"] = "My GST Filing"
    portal_page = st.radio(
        "Portal Navigation",
        navigation_pages,
        index=navigation_pages.index(st.session_state["active_portal_page"]),
        key="portal_navigation_widget",
    )
    st.session_state["active_portal_page"] = portal_page

st.markdown(
    f"""
    <div class="hero">
      <p class="hero-title">Smart GST & Compliance Management Portal</p>
      <div class="hero-copy">
        Filing workspace for monthly and quarterly returns with secured user access, registered taxpayer master,
        public-company data enrichment, GSTR reporting and compliance analytics.
      </div>
      <div class="hero-grid">
        <div class="hero-stat"><span>Registered Entities</span><strong>{total_entities}</strong></div>
        <div class="hero-stat"><span>Active Registrations</span><strong>{active_registrations}</strong></div>
        <div class="hero-stat"><span>Quarterly Filers</span><strong>{quarterly_entities}</strong></div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if portal_page == "My GST Filing":
    render_portal_header(
        "My GST Filing Journey",
        "Login -> verify my company -> prepare GSTR-1 -> validate and review GSTR-3B -> file return. This page is designed as a guided single-process workspace.",
        "Services > Returns > My GST Filing",
    )
    linked_gstin = st.session_state["auth_user"].get("linked_gstin")
    linked_company = get_company_by_gstin(linked_gstin) if linked_gstin else None
    st.markdown('<div class="card">', unsafe_allow_html=True)
    if not linked_company:
        st.warning("No filing company is linked to this login yet. Open Taxpayer Master and click 'Set As My Filing Company'.")
    else:
        linked_company = dict(linked_company)
        render_profile(linked_company)
        fy = st.selectbox("Financial Year", financial_year_options(), key="my_flow_fy")
        period = st.selectbox("Return Period", period_options(linked_company["filing_frequency"]), key="my_flow_period")
        filing_steps = ["1. Company", "2. GSTR-1", "3. GSTR-3B", "4. File Return"]
        current_step = st.session_state.get("my_flow_step_current", "1. Company")
        if current_step not in filing_steps:
            current_step = "1. Company"
            st.session_state["my_flow_step_current"] = current_step
        step_selector = st.radio(
            "Filing Process",
            filing_steps,
            horizontal=True,
            index=filing_steps.index(current_step),
            key="my_flow_step_selector",
        )
        if step_selector != current_step:
            st.session_state["my_flow_step_current"] = step_selector
            current_step = step_selector

        invoice_df = build_invoice_dataframe(get_invoice_entries(linked_company["gstin"], fy, period))
        credit_row = get_credit_row(linked_company["gstin"], fy, period)
        summary_gstr1 = get_gstr1_summary(invoice_df)
        summary_gstr3b = get_gstr3b_summary(invoice_df, credit_row)
        filing_event = get_filing_event(linked_company["gstin"], fy, period, "GSTR-3B")

        if current_step == "1. Company":
            st.markdown("#### Company Verification")
            st.info("This login will file GST only for the linked company shown below.")
            c1, c2, c3 = st.columns(3)
            c1.metric("Linked GSTIN", linked_company["gstin"])
            c2.metric("Filing Frequency", linked_company["filing_frequency"])
            c3.metric("Return Period", period)
            if st.button("Proceed to GSTR-1", key="flow_to_gstr1"):
                set_my_filing_step("2. GSTR-1")

        elif current_step == "2. GSTR-1":
            st.markdown("#### GSTR-1 Preparation")
            st.caption("Enter outward supply invoices for this filing period. After invoice entry and validation, proceed to GSTR-3B.")
            with st.form("my_flow_invoice_form"):
                a1, a2, a3 = st.columns(3)
                invoice_no = a1.text_input("Invoice No.", key="flow_invoice_no")
                invoice_date = a2.date_input("Invoice Date", key="flow_invoice_date")
                doc_type = a3.selectbox("Document Type", ["Tax Invoice", "Debit Note", "Credit Note"], key="flow_doc_type")
                b1, b2, b3 = st.columns(3)
                receiver_gstin = b1.text_input("Receiver GSTIN / UIN", key="flow_receiver_gstin")
                receiver_name = b2.text_input("Receiver Name", key="flow_receiver_name")
                place_of_supply = b3.text_input("Place of Supply", value=linked_company["state_name"] or linked_company["state_code"], key="flow_place_of_supply")
                c1, c2, c3 = st.columns(3)
                taxable_value = c1.number_input("Taxable Amount", min_value=0.0, step=100.0, key="flow_taxable_value")
                gst_rate = c2.selectbox("GST Rate", [5.0, 12.0, 18.0, 28.0], index=2, key="flow_gst_rate")
                inter_state = c3.checkbox("Supply Attracts IGST", key="flow_inter_state")
                save_invoice = st.form_submit_button("Add Invoice")
            if save_invoice:
                add_invoice_entry(
                    {
                        "gstin": linked_company["gstin"],
                        "financial_year": fy,
                        "period": period,
                        "invoice_no": invoice_no.strip(),
                        "invoice_date": str(invoice_date),
                        "doc_type": doc_type,
                        "counterparty_gstin": receiver_gstin.strip().upper(),
                        "counterparty_name": receiver_name.strip(),
                        "place_of_supply": place_of_supply.strip(),
                        "taxable_value": taxable_value,
                        "gst_rate": gst_rate,
                        "is_inter_state": 1 if inter_state else 0,
                        "source_type": "Manual",
                        "note": "",
                    }
                )
                st.success("Invoice added.")
                st.rerun()
            st.metric("Invoices Added", summary_gstr1["invoice_count"])
            if not invoice_df.empty:
                st.dataframe(
                    invoice_df[["invoice_no", "invoice_date", "counterparty_gstin", "counterparty_name", "taxable_value", "gst_rate", "output_tax"]],
                    use_container_width=True,
                    hide_index=True,
                )
            if st.button("Validate GSTR-1 and Continue", key="flow_validate_gstr1", disabled=summary_gstr1["invoice_count"] == 0):
                set_my_filing_step("3. GSTR-3B")

        elif current_step == "3. GSTR-3B":
            st.markdown("#### GSTR-3B Auto-Population and Validation")
            st.caption("Outward liability is auto-populated from GSTR-1 invoices. ITC, TDS and TCS are pulled from the credit ledger.")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Outward Supplies", compact_money(summary_gstr3b["outward_taxable_supplies"]))
            c2.metric("Output Tax", compact_money(summary_gstr3b["output_tax"]))
            c3.metric("Credits", compact_money(summary_gstr3b["itc_claimed"] + summary_gstr3b["tds_received"] + summary_gstr3b["tcs_received"]))
            c4.metric("Net Liability", compact_money(summary_gstr3b["net_tax_payable"]))

            comparison_df = pd.DataFrame(
                [
                    {"Particular": "GSTR-1 Taxable Value", "Amount": compact_money(summary_gstr1["taxable_value"])},
                    {"Particular": "GSTR-1 Output Tax", "Amount": compact_money(summary_gstr1["output_tax"])},
                    {"Particular": "ITC Claimed", "Amount": compact_money(summary_gstr3b["itc_claimed"])},
                    {"Particular": "TDS + TCS", "Amount": compact_money(summary_gstr3b["tds_received"] + summary_gstr3b["tcs_received"])},
                    {"Particular": "Final Net Tax Liability", "Amount": compact_money(summary_gstr3b["net_tax_payable"])},
                ]
            )
            st.dataframe(comparison_df, use_container_width=True, hide_index=True)
            if st.button("Validate GSTR-3B and Proceed to Filing", key="flow_validate_gstr3b"):
                set_my_filing_step("4. File Return")

        elif current_step == "4. File Return":
            st.markdown("#### Final Filing")
            st.caption("Final confirmation, OTP verification, challan generation and filing acknowledgement.")
            mobile = st.text_input("Registered Mobile Number", key="flow_mobile")
            signatory_name = st.text_input("Digital Signature / Authorized Signatory", value=linked_company["auth_signatory"] or "", key="flow_signatory")
            otp_key = f"flow_otp_{linked_company['gstin']}_{fy}_{period}"
            if st.button("Send OTP", key="flow_send_otp"):
                otp_code = generate_otp()
                st.session_state[otp_key] = otp_code
                record_filing_event(
                    {
                        "gstin": linked_company["gstin"],
                        "financial_year": fy,
                        "period": period,
                        "return_type": "GSTR-3B",
                        "registered_mobile": mobile,
                        "otp_code": otp_code,
                        "challan_no": "",
                        "payment_mode": "",
                        "payment_status": "OTP Sent",
                        "ack_no": "",
                        "filed_at": "",
                    }
                )
                st.info(f"OTP sent to registered mobile (demo OTP: {otp_code})")
            entered_otp = st.text_input("Enter OTP", key="flow_entered_otp")
            payment_mode = st.selectbox("Payment Mode", ["Net Banking", "NEFT / RTGS", "UPI", "OTC"], key="flow_payment_mode")
            if st.button("Complete Filing", key="flow_complete_filing"):
                if entered_otp != st.session_state.get(otp_key):
                    st.error("Invalid OTP.")
                elif not signatory_name.strip():
                    st.error("Authorized signatory is required.")
                else:
                    challan_no = generate_reference("CPIN")
                    ack_no = generate_reference("ARN")
                    filed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    record_filing_event(
                        {
                            "gstin": linked_company["gstin"],
                            "financial_year": fy,
                            "period": period,
                            "return_type": "GSTR-3B",
                            "registered_mobile": mobile,
                            "otp_code": entered_otp,
                            "challan_no": challan_no,
                            "payment_mode": payment_mode,
                            "payment_status": "Paid and Filed",
                            "ack_no": ack_no,
                            "filed_at": filed_at,
                        }
                    )
                    filing_event = get_filing_event(linked_company["gstin"], fy, period, "GSTR-3B")
                    st.success(f"GSTR-3B filed successfully. ARN: {filing_event['ack_no']}")
                    pdf_bytes = build_acknowledgement_pdf(
                        linked_company, fy, period, filing_event, summary_gstr3b, signatory_name.strip()
                    )
                    left_col, right_col = st.columns([2.4, 1], gap="large")
                    with left_col:
                        render_acknowledgement_preview(
                            linked_company,
                            fy,
                            period,
                            filing_event,
                            summary_gstr3b,
                            signatory_name.strip(),
                            "Return Filing Acknowledgement",
                        )
                    with right_col:
                        st.markdown("#### Acknowledgement Actions")
                        st.caption("Download or print the filing acknowledgement in a formal white-page format.")
                        st.download_button(
                            "Download PDF",
                            data=pdf_bytes,
                            file_name=f"{linked_company['gstin']}_{period}_gstr3b_acknowledgement.pdf",
                            mime="application/pdf",
                            key="my_filing_ack_pdf",
                            use_container_width=True,
                        )
    st.markdown("</div>", unsafe_allow_html=True)

elif portal_page == "Dashboard":
    st.markdown('<div class="card"><div class="section-title">Compliance Dashboard</div>', unsafe_allow_html=True)
    if companies_df.empty:
        st.info("No taxpayers registered.")
    else:
        dashboard_table = companies_df[
            ["company_name", "gstin", "state_name", "filing_frequency", "registration_status", "ticker"]
        ].rename(
            columns={
                "company_name": "Legal Name",
                "gstin": "GSTIN",
                "state_name": "State",
                "filing_frequency": "Frequency",
                "registration_status": "Status",
                "ticker": "Ticker",
            }
        )
        st.dataframe(dashboard_table, use_container_width=True, hide_index=True)
        st.caption(
            "The filing journey now follows a realistic sequence: Credit Ledger -> GSTR-1 invoice entry -> GSTR-3B auto-population -> OTP, challan and payment acknowledgement."
        )
    st.markdown("</div>", unsafe_allow_html=True)

elif portal_page == "Returns Dashboard":
    render_portal_header(
        "Returns Dashboard",
        "Select a return period and choose the tile you want to open. This page is designed to resemble a dedicated return dashboard rather than a generic menu.",
        "Services > Returns > Returns Dashboard",
    )
    st.markdown('<div class="card">', unsafe_allow_html=True)
    if companies_df.empty:
        st.warning("Create a taxpayer profile first.")
    else:
        selected = get_selected_company(companies_df, "returns_company", "Taxpayer")
        render_profile(selected)
        c1, c2 = st.columns(2)
        fy = c1.selectbox("Financial Year", financial_year_options(), key="returns_fy")
        period = c2.selectbox("Return Period", period_options(selected["filing_frequency"]), key="returns_period")

        credit_row = get_credit_row(selected["gstin"], fy, period)
        invoice_df = build_invoice_dataframe(get_invoice_entries(selected["gstin"], fy, period))
        gstr1_summary = get_gstr1_summary(invoice_df)
        gstr3b_summary = get_gstr3b_summary(invoice_df, credit_row)
        filing_event = get_filing_event(selected["gstin"], fy, period, "GSTR-3B")
        credit_values = credit_row.to_dict() if credit_row is not None else {}

        st.markdown("#### Return Tiles")
        st.caption("Use the large action buttons below. Each one opens the selected return function for the same taxpayer, financial year and period.")
        tile1, tile2, tile3, tile4 = st.columns(4)
        gstr1_status = "Ready" if gstr1_summary["invoice_count"] > 0 else "Pending"
        gstr3b_status = "Ready" if gstr1_summary["invoice_count"] > 0 else "Pending"
        credit_status = "Ready" if credit_values else "Pending"
        payment_status = filing_event["payment_status"] if filing_event else "Not Filed"
        with tile1:
            if st.button(
                f"GSTR-1\n\nInvoices: {gstr1_summary['invoice_count']}\nTaxable: {compact_money(gstr1_summary['taxable_value'])}\nStatus: {gstr1_status}",
                key="returns_open_gstr1",
                use_container_width=True,
            ):
                go_to_return_page("GSTR-1", selected, fy, period)
        with tile2:
            if st.button(
                f"GSTR-3B\n\nLiability: {compact_money(gstr3b_summary['net_tax_payable'])}\nOutput Tax: {compact_money(gstr3b_summary['output_tax'])}\nStatus: {gstr3b_status}",
                key="returns_open_gstr3b",
                use_container_width=True,
            ):
                go_to_return_page("GSTR-3B", selected, fy, period)
        with tile3:
            if st.button(
                f"Credit Ledger\n\nITC: {compact_money(credit_values.get('itc_claimed', 0.0) or 0.0)}\nTDS/TCS: {compact_money((credit_values.get('tds_received', 0.0) or 0.0) + (credit_values.get('tcs_received', 0.0) or 0.0))}\nStatus: {credit_status}",
                key="returns_open_credit",
                use_container_width=True,
            ):
                go_to_return_page("Credit Ledger", selected, fy, period)
        with tile4:
            if st.button(
                f"File Return\n\nStatus: {payment_status}\nARN: {(filing_event['ack_no'] if filing_event and filing_event['ack_no'] else 'Pending')}\nAction: Pay/File",
                key="returns_open_payment",
                use_container_width=True,
            ):
                go_to_return_page("Filing & Payment", selected, fy, period)

        st.markdown("#### Filing Readiness")
        readiness = pd.DataFrame(
            [
                {
                    "Return": "GSTR-1",
                    "Status": gstr1_status,
                    "Condition": "At least one invoice should be added",
                },
                {
                    "Return": "GSTR-3B",
                    "Status": gstr3b_status,
                    "Condition": "Invoice register and credit ledger should be available",
                },
                {
                    "Return": "Filing / Payment",
                    "Status": payment_status if filing_event else "Ready",
                    "Condition": "GSTR-3B preview should be reviewed before filing",
                },
            ]
        )
        st.dataframe(readiness, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

elif portal_page == "Automation Center":
    render_portal_header(
        "Automation Center",
        "AutoPilot prepares invoice records, credit ledger, return status and reconciliation-ready data for the selected taxpayer and period.",
        "Services > Smart Automation > AutoPilot Filing",
    )
    st.markdown('<div class="card">', unsafe_allow_html=True)
    if companies_df.empty:
        st.warning("Create a taxpayer profile first.")
    else:
        selected = get_selected_company(companies_df, "automation_company", "Taxpayer")
        render_profile(selected)
        a1, a2, a3 = st.columns(3)
        fy = a1.selectbox("Financial Year", financial_year_options(), key="automation_fy", index=get_shared_fy_index())
        period = a2.selectbox(
            "Return Period",
            period_options(selected["filing_frequency"]),
            key="automation_period",
            index=get_shared_period_index(selected["filing_frequency"]),
        )
        automation_mode = a3.selectbox("Automation Level", ["Draft Prepare", "Prepare + Reconcile", "Prepare + Draft Filing"])

        b1, b2, b3 = st.columns(3)
        base_taxable_value = b1.number_input("Estimated Taxable Turnover", min_value=10000.0, value=250000.0, step=10000.0)
        gst_rate = b2.selectbox("Default GST Rate", [5.0, 12.0, 18.0, 28.0], index=2)
        auto_mobile = b3.text_input("Registered Mobile", value="9999999999")

        st.markdown("#### What AutoPilot Will Do")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Step": "1", "Automation": "Create outward supply invoices automatically"},
                    {"Step": "2", "Automation": "Estimate ITC, TDS and TCS credit ledger values"},
                    {"Step": "3", "Automation": "Auto-prepare GSTR-1 and GSTR-3B return status"},
                    {"Step": "4", "Automation": "Run smart reconciliation checks"},
                    {"Step": "5", "Automation": "Optionally create a draft challan/filing package"},
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

        if st.button("Run AutoPilot Filing Automation", key="run_autopilot", use_container_width=True):
            plan = build_auto_filing_plan(selected, fy, period, base_taxable_value, gst_rate)
            for invoice in plan["invoices"]:
                add_invoice_entry(invoice)
            upsert_gst_entry(plan["gst_entry"])

            if automation_mode == "Prepare + Draft Filing":
                record_filing_event(
                    {
                        "gstin": selected["gstin"],
                        "financial_year": fy,
                        "period": period,
                        "return_type": "GSTR-3B",
                        "registered_mobile": auto_mobile,
                        "otp_code": "AUTO",
                        "challan_no": generate_reference("DRAFTCPIN"),
                        "payment_mode": "Automation Draft",
                        "payment_status": "Draft Prepared",
                        "ack_no": "",
                        "filed_at": "",
                    }
                )

            st.session_state["shared_company_label"] = f'{selected["company_name"]} ({selected["gstin"]})'
            st.session_state["shared_financial_year"] = fy
            st.session_state["shared_period"] = period
            st.success("AutoPilot completed. GSTR-1, credit ledger and GSTR-3B data are now prepared for review.")

        invoice_df = build_invoice_dataframe(get_invoice_entries(selected["gstin"], fy, period))
        credit_row = get_credit_row(selected["gstin"], fy, period)
        filing_event = get_filing_event(selected["gstin"], fy, period, "GSTR-3B")
        summary = get_gstr3b_summary(invoice_df, credit_row)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Invoices", len(invoice_df.index) if not invoice_df.empty else 0)
        c2.metric("Output Tax", compact_money(summary["output_tax"]))
        c3.metric("Net Payable", compact_money(summary["net_tax_payable"]))
        c4.metric("Filing Status", filing_event["payment_status"] if filing_event else "Not Started")

        st.markdown("#### AutoPilot Reconciliation")
        st.dataframe(
            pd.DataFrame(build_reconciliation_report(invoice_df, credit_row, filing_event)),
            use_container_width=True,
            hide_index=True,
        )

        nav1, nav2, nav3 = st.columns(3)
        with nav1:
            if st.button("Review Auto GSTR-1", key="automation_review_gstr1", use_container_width=True):
                go_to_return_page("GSTR-1", selected, fy, period)
        with nav2:
            if st.button("Review Auto GSTR-3B", key="automation_review_gstr3b", use_container_width=True):
                go_to_return_page("GSTR-3B", selected, fy, period)
        with nav3:
            if st.button("Proceed to Filing", key="automation_review_payment", use_container_width=True):
                go_to_return_page("Filing & Payment", selected, fy, period)
    st.markdown("</div>", unsafe_allow_html=True)

elif portal_page == "AI/ML Intelligence":
    render_portal_header(
        "AI/ML Compliance Intelligence",
        "A futuristic decision-support layer that uses local machine-learning style scoring, invoice anomaly detection, liability forecasting and explainable recommendations.",
        "Services > Smart Compliance > AI/ML Intelligence",
    )
    st.markdown('<div class="card">', unsafe_allow_html=True)
    if companies_df.empty:
        st.warning("Create a taxpayer profile first.")
    else:
        selected = get_selected_company(companies_df, "aiml_company", "Taxpayer")
        fy = st.selectbox("Financial Year", financial_year_options(), key="aiml_fy")
        df = sort_period_df(build_return_dataframe(get_gst_entries(selected["gstin"], fy)))
        invoice_rows = build_invoice_dataframe(get_invoice_entries(selected["gstin"], fy))
        notices = build_notice_center(df, invoice_rows, fy, selected["filing_frequency"])
        intelligence = build_ai_ml_compliance_intelligence(df, invoice_rows, notices)
        render_profile(selected)

        st.markdown(
            """
            <div class="card">
              <div class="section-title">Neural Compliance Command Center</div>
              <div class="section-copy">
                This module behaves like an explainable AI layer for GST compliance. It converts filing history, invoice quality,
                return status and notice pressure into model features, then produces risk classification, anomaly flags,
                forecasting and recommended actions.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("ML Risk Score", f"{intelligence['risk_score']} / 100")
        m2.metric("Risk Band", intelligence["risk_band"])
        m3.metric("Model Confidence", intelligence["confidence"])
        m4.metric("Predicted Next Liability", compact_money(intelligence["predicted_next_liability"]))

        card_col, explain_col = st.columns([1.1, 1], gap="large")
        with card_col:
            st.markdown("#### Model Pipeline")
            st.dataframe(pd.DataFrame(intelligence["model_cards"]), use_container_width=True, hide_index=True)
        with explain_col:
            st.markdown("#### Explainable AI Output")
            st.dataframe(pd.DataFrame({"Why the model decided this": intelligence["explanations"]}), use_container_width=True, hide_index=True)

        r1, r2 = st.columns([1, 1], gap="large")
        with r1:
            st.markdown("#### AI Recommendations")
            st.dataframe(pd.DataFrame({"Recommended Action": intelligence["recommendations"]}), use_container_width=True, hide_index=True)
        with r2:
            st.markdown("#### Feature Vector")
            feature_display = intelligence["feature_table"].T.reset_index()
            feature_display.columns = ["ML Feature", "Value"]
            st.dataframe(feature_display, use_container_width=True, hide_index=True)

        if not intelligence["invoice_anomalies"].empty:
            st.markdown("#### Invoice Anomaly Detection")
            st.dataframe(intelligence["invoice_anomalies"], use_container_width=True, hide_index=True)
            anomaly_chart = px.scatter(
                intelligence["invoice_anomalies"],
                x="invoice_no",
                y="taxable_value",
                color="ML Flag",
                size="Anomaly Score",
                title="Invoice Outlier Map",
                color_discrete_map={"Normal": "#0f766e", "Review": "#b42318"},
            )
            st.plotly_chart(anomaly_chart, use_container_width=True)
        else:
            st.info("No invoice rows available for anomaly detection yet. Run AutoPilot or add invoices to activate this model.")

        if not df.empty:
            trend_df = df.copy()
            trend_df["Total Credit"] = trend_df["itc_claimed"] + trend_df["tds_received"] + trend_df["tcs_received"]
            ml_fig = px.area(
                trend_df,
                x="month",
                y=["output_tax", "net_tax_payable", "Total Credit"],
                title="AI Forecast Context: Liability, Credits and Cash Tax",
                color_discrete_sequence=["#0f4c81", "#b42318", "#0f766e"],
            )
            st.plotly_chart(ml_fig, use_container_width=True)

        st.markdown("#### GST Compliance Copilot")
        copilot_question = st.text_input(
            "Ask the AI copilot",
            placeholder="Example: Why is this taxpayer risky? What should I fix first? What is next liability forecast?",
            key="copilot_question",
        )
        if copilot_question:
            st.info(answer_compliance_copilot(copilot_question, intelligence))

        st.markdown(
            """
            <div class="card">
              <div class="section-title">Viva Explanation</div>
              <div class="section-copy">
                This is an explainable AI/ML-inspired layer. It uses feature extraction, weighted risk classification,
                statistical anomaly detection and time-series style forecasting. It does not depend on external AI APIs,
                so it works offline and remains transparent for academic evaluation.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

elif portal_page == "Taxpayer Master":
    st.markdown('<div class="card"><div class="section-title">Taxpayer Master</div>', unsafe_allow_html=True)
    entity_category = st.radio(
        "Entity Type",
        ["Private / Non-listed", "Public / Listed"],
        horizontal=True,
        key="entity_category",
    )
    with st.form("company_form"):
        c1, c2 = st.columns(2)
        company_name = c1.text_input("Legal Name", placeholder="ABC Private Limited")
        trade_name = c2.text_input("Trade Name", placeholder="ABC Technologies")
        c3, c4, c5 = st.columns(3)
        if entity_category == "Public / Listed":
            ticker = c3.text_input("Public Market Ticker", placeholder="RELIANCE.NS")
        else:
            ticker = ""
            c3.text_input("Public Market Ticker", value="Not required for private entity", disabled=True)
        gstin = c4.text_input("GSTIN", placeholder="27ABCDE1234F1Z5")
        state_code = c5.text_input("State Code", placeholder="27")
        c6, c7, c8 = st.columns(3)
        state_name = c6.text_input("State Name", placeholder="Maharashtra")
        default_business_type = "Public Limited / Listed Entity" if entity_category == "Public / Listed" else "Private Limited / Proprietorship / LLP"
        business_type = c7.text_input("Business Type", value=default_business_type)
        filing_frequency = c8.selectbox("How will this taxpayer file?", ["Monthly", "Quarterly"])
        c9, c10, c11 = st.columns(3)
        registration_status = c9.selectbox("Registration Status", ["Active", "Suspended", "Cancelled"])
        principal_place = c10.text_input("Principal Place of Business", placeholder="Mumbai, Maharashtra")
        auth_signatory = c11.text_input("Authorized Signatory", placeholder="Director / CFO")
        submitted = st.form_submit_button("Save Taxpayer Profile")
    if submitted:
        normalized_gstin = gstin.strip().upper()
        valid_gstin, gstin_error = validate_gstin(normalized_gstin)
        if not company_name.strip():
            st.error("Legal Name is required.")
        elif not normalized_gstin:
            st.error("GSTIN is required.")
        elif not valid_gstin:
            st.error(gstin_error)
        elif entity_category == "Public / Listed" and not ticker.strip():
            st.error("Ticker is required for a listed entity.")
        else:
            try:
                insert_company(
                    company_name=company_name.strip(),
                    ticker=ticker.strip(),
                    gstin=normalized_gstin,
                    state_code=state_code.strip(),
                    trade_name=trade_name.strip(),
                    business_type=business_type.strip(),
                    state_name=state_name.strip(),
                    filing_frequency=filing_frequency,
                    registration_status=registration_status,
                    principal_place=principal_place.strip(),
                    auth_signatory=auth_signatory.strip(),
                )
                st.success("Taxpayer profile saved successfully.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save taxpayer profile. It may already exist or contain duplicate details: {exc}")
    st.markdown("</div>", unsafe_allow_html=True)

    if not companies_df.empty:
        selected_company = get_selected_company(companies_df, "profile_select", "Open Registered Profile")
        render_profile(selected_company)
        if st.button("Set As My Filing Company", key="set_my_company_btn"):
            update_user_linked_gstin(st.session_state["auth_user"]["username"], selected_company["gstin"])
            st.session_state["auth_user"]["linked_gstin"] = selected_company["gstin"]
            st.success(f"{selected_company['company_name']} is now linked as your filing company.")

elif portal_page == "Public Company API":
    st.markdown('<div class="card"><div class="section-title">Public Company API Integration</div>', unsafe_allow_html=True)
    st.caption("Try `INFY.NS`, `RELIANCE.NS`, or `TCS.NS`. If live lookup is unavailable, the portal will use built-in public company fallback data for demo reliability.")
    with st.form("fetch_api"):
        ticker_symbol = st.text_input("Ticker Symbol", placeholder="INFY.NS or TCS.NS or AAPL")
        fetch = st.form_submit_button("Fetch Public Data")
    if fetch:
        try:
            data = fetch_public_company_financials(ticker_symbol)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Latest Turnover", compact_money(data["turnover"]))
            c2.metric("Purchase Base", compact_money(data["purchase_value"]))
            c3.metric("Market Cap", compact_money(data["market_cap"]))
            c4.metric("Current Price", money(data["current_price"]))
            if data["source"] == "Yahoo Finance (public data)":
                st.success("Live public-company data fetched successfully.")
            else:
                st.warning("Live lookup is unavailable. Showing built-in public company fallback data for demo use.")
            st.json(data)
        except Exception as exc:
            st.error(str(exc))
    st.markdown("</div>", unsafe_allow_html=True)

elif portal_page == "Credit Ledger":
    st.markdown('<div class="card"><div class="section-title">Credit Ledger Input</div>', unsafe_allow_html=True)
    if companies_df.empty:
        st.warning("Create a taxpayer profile first.")
    else:
        selected = get_selected_company(companies_df, "credit_company", "Choose Taxpayer")
        render_profile(selected)
        st.caption("Capture ITC, TDS and TCS values for the selected month or quarter. These values will feed GSTR-3B.")
        c1, c2 = st.columns(2)
        fy = c1.selectbox("Financial Year", financial_year_options(), key="credit_fy", index=get_shared_fy_index())
        period = c2.selectbox(
            "Tax Period",
            period_options(selected["filing_frequency"]),
            key="credit_period",
            index=get_shared_period_index(selected["filing_frequency"]),
        )
        render_return_navigation(selected, fy, period, "credit_nav")
        with st.form("credit_ledger_form"):
            c3, c4, c5 = st.columns(3)
            itc_claimed = c3.number_input("ITC Claimed", min_value=0.0, step=500.0)
            tds_received = c4.number_input("TDS Credit Received", min_value=0.0, step=100.0)
            tcs_received = c5.number_input("TCS Credit Received", min_value=0.0, step=100.0)
            notes = st.text_area("Ledger Notes", placeholder="ITC basis, TDS certificates, TCS ledger remarks")
            save_credit = st.form_submit_button("Save Credit Ledger")
        if save_credit:
            upsert_gst_entry(
                {
                    "gstin": selected["gstin"],
                    "financial_year": fy,
                    "month": period,
                    "turnover": 0.0,
                    "purchase_value": 0.0,
                    "gst_rate": 18.0,
                    "is_inter_state": 0,
                    "itc_claimed": itc_claimed,
                    "tds_received": tds_received,
                    "tcs_received": tcs_received,
                    "gstr1_reported": 0,
                    "gstr3b_reported": 0,
                    "gstr2a_reported": 0,
                    "notes": notes,
                }
            )
            st.success("Credit ledger saved.")
    st.markdown("</div>", unsafe_allow_html=True)

elif portal_page == "GSTR-1":
    render_portal_header(
        "GSTR-1 - Details of Outward Supplies",
        "Returns Dashboard > Select Return Period > GSTR-1 > Prepare Online. Add B2B invoice details, debit notes, credit notes and generate the return summary for the selected period.",
        "Services > Returns > Returns Dashboard > GSTR-1",
    )
    st.markdown('<div class="card">', unsafe_allow_html=True)
    if companies_df.empty:
        st.warning("Create a taxpayer profile first.")
    else:
        selected = get_selected_company(companies_df, "gstr1_company", "Taxpayer")
        render_profile(selected)
        c1, c2 = st.columns(2)
        fy = c1.selectbox("Financial Year", financial_year_options(), key="gstr1_fy", index=get_shared_fy_index())
        period = c2.selectbox(
            "Return Period",
            period_options(selected["filing_frequency"]),
            key="gstr1_period",
            index=get_shared_period_index(selected["filing_frequency"]),
        )
        render_return_navigation(selected, fy, period, "gstr1_nav")
        credit_row = get_credit_row(selected["gstin"], fy, period)

        top1, top2, top3 = st.columns(3)
        top1.metric("Return Type", "GSTR-1")
        top2.metric("Filing Frequency", selected["filing_frequency"])
        top3.metric("Preparation Mode", "Prepare Online")

        g1a, g1b, g1c = st.columns(3)
        with g1a:
            st.markdown('<div class="card"><div class="section-title">4A, 4B, 4C, 6B, 6C</div><div class="section-copy">B2B Invoices</div></div>', unsafe_allow_html=True)
        with g1b:
            st.markdown('<div class="card"><div class="section-title">9B</div><div class="section-copy">Credit / Debit Notes</div></div>', unsafe_allow_html=True)
        with g1c:
            st.markdown('<div class="card"><div class="section-title">13</div><div class="section-copy">Documents Issued Summary</div></div>', unsafe_allow_html=True)

        st.markdown("#### B2B / Document Entry")
        with st.form("invoice_entry_form"):
            r1c1, r1c2, r1c3 = st.columns(3)
            invoice_no = r1c1.text_input("Invoice No.")
            invoice_date = r1c2.date_input("Invoice Date")
            doc_type = r1c3.selectbox("Document Type", ["Tax Invoice", "Debit Note", "Credit Note"])

            r2c1, r2c2, r2c3 = st.columns(3)
            seller_gstin = r2c1.text_input("Receiver GSTIN / UIN")
            buyer_name = r2c2.text_input("Receiver Name")
            place_of_supply = r2c3.text_input("Place of Supply", value=selected["state_name"] or selected["state_code"])

            r3c1, r3c2, r3c3 = st.columns(3)
            taxable_value = r3c1.number_input("Taxable Amount", min_value=0.0, step=100.0)
            gst_rate = r3c2.selectbox("GST Rate", [5.0, 12.0, 18.0, 28.0], index=2)
            inter_state = r3c3.checkbox("Supply Attracts IGST")

            save_invoice = st.form_submit_button("Add Invoice")

        if save_invoice:
            add_invoice_entry(
                {
                    "gstin": selected["gstin"],
                    "financial_year": fy,
                    "period": period,
                    "invoice_no": invoice_no.strip(),
                    "invoice_date": str(invoice_date),
                    "doc_type": doc_type,
                    "counterparty_gstin": seller_gstin.strip().upper(),
                    "counterparty_name": buyer_name.strip(),
                    "place_of_supply": place_of_supply.strip(),
                    "taxable_value": taxable_value,
                    "gst_rate": gst_rate,
                    "is_inter_state": 1 if inter_state else 0,
                    "source_type": "Manual",
                    "note": "",
                }
            )
            st.success("Invoice added to GSTR-1 register.")

        if st.button("Auto-add support rows from ITC / TDS / TCS", key="auto_support_btn"):
            for row in build_auto_supporting_invoices(selected["gstin"], fy, period, credit_row):
                add_invoice_entry(row)
            st.success("Support rows generated from credit ledgers. Manual invoices are still required for complete filing.")

        invoice_df = build_invoice_dataframe(get_invoice_entries(selected["gstin"], fy, period))
        invoice_df = invoice_df.sort_values(["invoice_date", "invoice_no"]) if not invoice_df.empty else invoice_df
        summary = get_gstr1_summary(invoice_df)
        st.markdown("#### Generate GSTR-1 Summary")
        csum1, csum2, csum3, csum4 = st.columns(4)
        csum1.metric("Invoices Added", summary["invoice_count"])
        csum2.metric("Taxable Value", compact_money(summary["taxable_value"]))
        csum3.metric("Total Tax", compact_money(summary["output_tax"]))
        csum4.metric("IGST + CGST/SGST", compact_money(summary["igst"] + summary["cgst"] + summary["sgst"]))

        if not invoice_df.empty:
            docs_issued = pd.DataFrame(
                [
                    {
                        "Nature of Document": "Invoices for outward supply",
                        "Total Number": int(len(invoice_df.index)),
                        "Cancelled": 0,
                        "Net Issued": int(len(invoice_df.index)),
                    }
                ]
            )
            st.dataframe(
                invoice_df[
                    [
                        "invoice_no",
                        "invoice_date",
                        "doc_type",
                        "counterparty_gstin",
                        "counterparty_name",
                        "taxable_value",
                        "gst_rate",
                        "cgst",
                        "sgst",
                        "igst",
                        "source_type",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.markdown("#### Document Issued")
            st.dataframe(docs_issued, use_container_width=True, hide_index=True)
        else:
            st.info("No invoice rows added for this period yet.")
        if st.button("Validate GSTR-1 and Proceed to GSTR-3B", key="gstr1_to_gstr3b", disabled=summary["invoice_count"] == 0, use_container_width=True):
            go_to_return_page("GSTR-3B", selected, fy, period)
    st.markdown("</div>", unsafe_allow_html=True)

elif portal_page == "GSTR-3B":
    render_portal_header(
        "GSTR-3B - Monthly / Quarterly Summary Return",
        "Returns Dashboard > Select Return Period > GSTR-3B. Liability is system-assisted using outward supplies and available credit values captured in the portal.",
        "Services > Returns > Returns Dashboard > GSTR-3B",
    )
    st.markdown('<div class="card">', unsafe_allow_html=True)
    if companies_df.empty:
        st.warning("Create a taxpayer profile first.")
    else:
        selected = get_selected_company(companies_df, "gstr3b_company", "Taxpayer")
        render_profile(selected)
        c1, c2 = st.columns(2)
        fy = c1.selectbox("Financial Year", financial_year_options(), key="gstr3b_fy", index=get_shared_fy_index())
        period = c2.selectbox(
            "Tax Period",
            period_options(selected["filing_frequency"]),
            key="gstr3b_period",
            index=get_shared_period_index(selected["filing_frequency"]),
        )
        invoice_df = build_invoice_dataframe(get_invoice_entries(selected["gstin"], fy, period))
        credit_row = get_credit_row(selected["gstin"], fy, period)
        filing_event = get_filing_event(selected["gstin"], fy, period, "GSTR-3B")
        summary = get_gstr3b_summary(invoice_df, credit_row)
        render_return_navigation(selected, fy, period, "gstr3b_nav")

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Outward Taxable Supplies", compact_money(summary["outward_taxable_supplies"]))
        s2.metric("Total Output Tax", compact_money(summary["output_tax"]))
        s3.metric("Available Credit", compact_money(summary["itc_claimed"] + summary["tds_received"] + summary["tcs_received"]))
        s4.metric("Net Tax Liability", compact_money(summary["net_tax_payable"]))

        preview1, preview2 = st.columns(2)
        with preview1:
            st.markdown(
                """
                <div class="card">
                  <div class="section-title">3.1 Details of Outward Supplies and inward supplies liable to reverse charge</div>
                  <div class="section-copy">System-calculated from GSTR-1 invoice register for the selected period.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with preview2:
            st.markdown(
                """
                <div class="card">
                  <div class="section-title">4 Eligible ITC</div>
                  <div class="section-copy">Auto-linked from the credit ledger maintained in the portal.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        gstr3b_table = pd.DataFrame(
            [
                ["3.1(a) Outward taxable supplies", summary["outward_taxable_supplies"], summary["output_tax"]],
                ["4(A)(5) All other ITC", summary["itc_claimed"], summary["itc_claimed"]],
                ["5.1 TDS Credit", summary["tds_received"], summary["tds_received"]],
                ["5.2 TCS Credit", summary["tcs_received"], summary["tcs_received"]],
                ["6.1 Tax payable", summary["net_tax_payable"], summary["net_tax_payable"]],
            ],
            columns=["GSTR-3B Column", "Value Base", "Amount"],
        )
        gstr3b_table["Value Base"] = gstr3b_table["Value Base"].map(compact_money)
        gstr3b_table["Amount"] = gstr3b_table["Amount"].map(compact_money)
        st.markdown("#### System Computed Return Table")
        st.dataframe(gstr3b_table, use_container_width=True, hide_index=True)

        liability_preview = pd.DataFrame(
            [
                {
                    "Tax Head": "Integrated Tax",
                    "Tax Payable": compact_money(summary["igst"]),
                    "Tax Paid Through ITC": compact_money(min(summary["igst"], summary["itc_claimed"])),
                    "Tax Paid in Cash": compact_money(max(summary["net_tax_payable"] - summary["cgst"] - summary["sgst"], 0.0)),
                },
                {
                    "Tax Head": "Central Tax",
                    "Tax Payable": compact_money(summary["cgst"]),
                    "Tax Paid Through ITC": compact_money(0.0),
                    "Tax Paid in Cash": compact_money(summary["cgst"]),
                },
                {
                    "Tax Head": "State / UT Tax",
                    "Tax Payable": compact_money(summary["sgst"]),
                    "Tax Paid Through ITC": compact_money(0.0),
                    "Tax Paid in Cash": compact_money(summary["sgst"]),
                },
            ]
        )
        st.markdown("#### 6.1 Payment of Tax")
        st.dataframe(liability_preview, use_container_width=True, hide_index=True)

        st.markdown("#### Smart Reconciliation Engine")
        reconciliation_df = pd.DataFrame(build_reconciliation_report(invoice_df, credit_row, filing_event))
        st.dataframe(reconciliation_df, use_container_width=True, hide_index=True)

        if st.button("Mark GSTR-1 and GSTR-3B as Prepared", key="mark_prepared_btn"):
            upsert_gst_entry(
                {
                    "gstin": selected["gstin"],
                    "financial_year": fy,
                    "month": period,
                    "turnover": summary["outward_taxable_supplies"],
                    "purchase_value": 0.0,
                    "gst_rate": 18.0,
                    "is_inter_state": 1 if summary["igst"] > 0 else 0,
                    "itc_claimed": summary["itc_claimed"],
                    "tds_received": summary["tds_received"],
                    "tcs_received": summary["tcs_received"],
                    "gstr1_reported": 1,
                    "gstr3b_reported": 1,
                    "gstr2a_reported": 0,
                    "notes": "Auto-prepared from invoice register and credit ledger.",
                }
            )
            st.success("Return status prepared. Proceed to Filing & Payment.")
        if st.button("Proceed to Filing & Payment", key="gstr3b_to_payment", disabled=summary["outward_taxable_supplies"] == 0, use_container_width=True):
            go_to_return_page("Filing & Payment", selected, fy, period)
    st.markdown("</div>", unsafe_allow_html=True)

elif portal_page == "Filing & Payment":
    st.markdown('<div class="card"><div class="section-title">OTP, Challan and Payment</div>', unsafe_allow_html=True)
    st.caption("This is a realistic filing simulation. Real OTP, challan and banking require official GSTN or GSP integration.")
    if companies_df.empty:
        st.warning("Create a taxpayer profile first.")
    else:
        selected = get_selected_company(companies_df, "payment_company", "Taxpayer")
        render_profile(selected)
        c1, c2 = st.columns(2)
        fy = c1.selectbox("Financial Year", financial_year_options(), key="payment_fy", index=get_shared_fy_index())
        period = c2.selectbox(
            "Return Filing Period",
            period_options(selected["filing_frequency"]),
            key="payment_period",
            index=get_shared_period_index(selected["filing_frequency"]),
        )
        render_return_navigation(selected, fy, period, "payment_nav")

        invoice_df = build_invoice_dataframe(get_invoice_entries(selected["gstin"], fy, period))
        credit_row = get_credit_row(selected["gstin"], fy, period)
        summary = get_gstr3b_summary(invoice_df, credit_row)
        filing_event = get_filing_event(selected["gstin"], fy, period, "GSTR-3B")
        st.markdown("#### Pre-Filing Reconciliation")
        st.dataframe(pd.DataFrame(build_reconciliation_report(invoice_df, credit_row, filing_event)), use_container_width=True, hide_index=True)
        mobile = st.text_input("Registered Mobile Number", placeholder="Enter taxpayer mobile number", key="mobile_input")
        signatory_name = st.text_input("Digital Signature / Authorized Signatory", value=selected["auth_signatory"] or "")
        signature_consent = st.checkbox("I confirm that the above information is true and digitally signed by the authorized signatory.")

        otp_key = f"otp_{selected['gstin']}_{fy}_{period}"
        if st.button("Send OTP", key="send_otp_btn"):
            otp_code = generate_otp()
            st.session_state[otp_key] = otp_code
            record_filing_event(
                {
                    "gstin": selected["gstin"],
                    "financial_year": fy,
                    "period": period,
                    "return_type": "GSTR-3B",
                    "registered_mobile": mobile,
                    "otp_code": otp_code,
                    "challan_no": "",
                    "payment_mode": "",
                    "payment_status": "OTP Sent",
                    "ack_no": "",
                    "filed_at": "",
                }
            )
            st.info(f"OTP sent to registered mobile (demo OTP: {otp_code})")

        entered_otp = st.text_input("Enter OTP", key="otp_input")
        payment_mode = st.selectbox("Payment Mode", ["Net Banking", "NEFT / RTGS", "UPI", "OTC"], key="payment_mode")
        if st.button("Verify OTP and Generate Challan", key="gen_challan_btn"):
            if entered_otp and entered_otp == st.session_state.get(otp_key):
                challan_no = generate_reference("CPIN")
                record_filing_event(
                    {
                        "gstin": selected["gstin"],
                        "financial_year": fy,
                        "period": period,
                        "return_type": "GSTR-3B",
                        "registered_mobile": mobile,
                        "otp_code": entered_otp,
                        "challan_no": challan_no,
                        "payment_mode": payment_mode,
                        "payment_status": "Challan Generated",
                        "ack_no": "",
                        "filed_at": "",
                    }
                )
                st.success(f"Challan generated successfully: {challan_no}")
            else:
                st.error("Invalid OTP. Please send OTP again and verify.")

        filing_event = get_filing_event(selected["gstin"], fy, period, "GSTR-3B")
        if filing_event and filing_event["challan_no"]:
            st.write(f"Challan No.: `{filing_event['challan_no']}`")
            st.write(f"Net tax payable: `{compact_money(summary['net_tax_payable'])}`")
            if st.button("Complete Payment and File Return", key="complete_payment_btn"):
                if not signatory_name.strip():
                    st.error("Authorized signatory name is required for digital signature confirmation.")
                elif not signature_consent:
                    st.error("Please confirm the digital signature declaration before filing.")
                else:
                    ack_no = generate_reference("ARN")
                    filed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    record_filing_event(
                        {
                            "gstin": selected["gstin"],
                            "financial_year": fy,
                            "period": period,
                            "return_type": "GSTR-3B",
                            "registered_mobile": filing_event["registered_mobile"],
                            "otp_code": filing_event["otp_code"],
                            "challan_no": filing_event["challan_no"],
                            "payment_mode": filing_event["payment_mode"],
                            "payment_status": "Paid and Filed",
                            "ack_no": ack_no,
                            "filed_at": filed_at,
                        }
                    )
                    filing_event = get_filing_event(selected["gstin"], fy, period, "GSTR-3B")
                    st.success(f"Payment successful. Return filed. ARN: {ack_no}")
                    st.info(
                        f"Message sent to {filing_event['registered_mobile'] or 'registered mobile'}: GSTR-3B for {period} has been filed successfully."
                    )
                    pdf_bytes = build_acknowledgement_pdf(selected, fy, period, filing_event, summary, signatory_name.strip())
                    preview_col, actions_col = st.columns([2.45, 1], gap="large")
                    with preview_col:
                        render_acknowledgement_preview(
                            selected,
                            fy,
                            period,
                            filing_event,
                            summary,
                            signatory_name.strip(),
                            "Return Filing Acknowledgement",
                        )
                    with actions_col:
                        st.markdown("#### Acknowledgement Actions")
                        st.caption("Use the PDF receipt for download or print submission during review.")
                        st.download_button(
                            "Download PDF",
                            data=pdf_bytes,
                            file_name=f"{selected['gstin']}_{period}_gstr3b_acknowledgement.pdf",
                            mime="application/pdf",
                            key="filing_ack_pdf",
                            use_container_width=True,
                        )
        elif filing_event and filing_event["ack_no"]:
            pdf_bytes = build_acknowledgement_pdf(selected, fy, period, filing_event, summary, selected.get("auth_signatory") or "")
            preview_col, actions_col = st.columns([2.45, 1], gap="large")
            with preview_col:
                render_acknowledgement_preview(
                    selected,
                    fy,
                    period,
                    filing_event,
                    summary,
                    selected.get("auth_signatory") or "",
                    "Previously Filed Return Acknowledgement",
                )
            with actions_col:
                st.markdown("#### Acknowledgement Actions")
                st.caption("The return is already filed. Download the acknowledgement again if needed.")
                st.download_button(
                    "Download PDF",
                    data=pdf_bytes,
                    file_name=f"{selected['gstin']}_{period}_gstr3b_acknowledgement.pdf",
                    mime="application/pdf",
                    key="existing_filing_ack_pdf",
                    use_container_width=True,
                )
    st.markdown("</div>", unsafe_allow_html=True)

elif portal_page == "Smart Insights":
    st.markdown('<div class="card"><div class="section-title">Smart Insights</div>', unsafe_allow_html=True)
    if companies_df.empty:
        st.warning("Create a taxpayer profile first.")
    else:
        selected = get_selected_company(companies_df, "insights_company", "Taxpayer")
        fy = st.selectbox("Financial Year", financial_year_options(), key="insights_fy")
        df = sort_period_df(build_return_dataframe(get_gst_entries(selected["gstin"], fy)))
        invoice_rows = build_invoice_dataframe(get_invoice_entries(selected["gstin"], fy))
        compliance_snapshot = build_compliance_snapshot(df, invoice_rows)
        smart_period = st.selectbox(
            "Compliance Review Period",
            period_options(selected["filing_frequency"]),
            key="smart_review_period",
        )
        due_calendar = build_due_date_calendar(fy, selected["filing_frequency"], smart_period)
        filing_event = get_filing_event(selected["gstin"], fy, smart_period, "GSTR-3B")
        late_fee = estimate_late_fee(
            fy,
            selected["filing_frequency"],
            smart_period,
            filing_event["filed_at"] if filing_event and filing_event["filed_at"] else None,
        )
        notice_center = build_notice_center(df, invoice_rows, fy, selected["filing_frequency"])
        render_profile(selected)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Compliance Score", f"{compliance_snapshot['score']} / 100")
        k2.metric("Risk Status", compliance_snapshot["status"])
        k3.metric("Pending Return Flags", compliance_snapshot["pending_returns"])
        k4.metric("Next Liability Forecast", compact_money(compliance_snapshot["forecast_tax"]))

        due1, due2, due3, due4 = st.columns(4)
        due1.metric("GSTR-1 Due", due_calendar["gstr1_due"].strftime("%d %b %Y"))
        due2.metric("GSTR-3B Due", due_calendar["gstr3b_due"].strftime("%d %b %Y"))
        due3.metric("Late Fee Exposure", compact_money(late_fee["estimated_fee"]))
        due4.metric("Delay Days", str(late_fee["delay_days"]))

        left_col, right_col = st.columns([1.1, 1], gap="large")
        with left_col:
            st.markdown(
                """
                <div class="card">
                  <div class="section-title">AI-Style Compliance Monitor</div>
                  <div class="section-copy">
                    The portal evaluates filing history, tax-credit usage, invoice quality and return completion to create
                    a live compliance score for the taxpayer.
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            alert_df = pd.DataFrame({"Smart Alert": compliance_snapshot["alerts"]})
            st.dataframe(alert_df, use_container_width=True, hide_index=True)
        with right_col:
            st.markdown(
                """
                <div class="card">
                  <div class="section-title">Recommended Compliance Actions</div>
                  <div class="section-copy">
                    This guidance layer helps the taxpayer decide what to fix before return filing, similar to decision-support
                    systems seen in advanced digital tax platforms.
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            recommendation_df = pd.DataFrame({"System Recommendation": compliance_snapshot["recommendations"]})
            st.dataframe(recommendation_df, use_container_width=True, hide_index=True)

        notice_col, fee_col = st.columns([1.25, 1], gap="large")
        with notice_col:
            st.markdown(
                """
                <div class="card">
                  <div class="section-title">Smart Notice Center</div>
                  <div class="section-copy">
                    The system automatically drafts internal compliance notices based on pending returns, credit risk, invoice quality
                    and likely late-filing exposure.
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            notice_df = pd.DataFrame(notice_center)
            st.dataframe(notice_df, use_container_width=True, hide_index=True)
        with fee_col:
            st.markdown(
                """
                <div class="card">
                  <div class="section-title">Penalty and Due-Date Monitor</div>
                  <div class="section-copy">
                    This module estimates delay exposure and keeps due dates visible so the taxpayer can act before non-compliance becomes costly.
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            fee_table = pd.DataFrame(
                [
                    ["Selected Period", smart_period],
                    ["Filing Frequency", selected["filing_frequency"]],
                    ["GSTR-1 Due Date", due_calendar["gstr1_due"].strftime("%d %b %Y")],
                    ["GSTR-3B Due Date", due_calendar["gstr3b_due"].strftime("%d %b %Y")],
                    ["Estimated Delay Days", str(late_fee["delay_days"])],
                    ["Estimated Late Fee", money(late_fee["estimated_fee"])],
                ],
                columns=["Compliance Indicator", "Value"],
            )
            st.dataframe(fee_table, use_container_width=True, hide_index=True)

        if not invoice_rows.empty:
            quality1, quality2, quality3 = st.columns(3)
            quality1.metric("Duplicate Invoice Rows", compliance_snapshot["duplicate_invoices"])
            quality2.metric("Missing GSTIN on Invoices", compliance_snapshot["invoice_gstin_gaps"])
            quality3.metric("Risky Period Flags", compliance_snapshot["risky_periods"])

            invoice_quality_table = invoice_rows.copy()
            invoice_quality_table["Risk Marker"] = "Normal"
            duplicate_mask = invoice_quality_table.duplicated(subset=["invoice_no"], keep=False)
            if "counterparty_gstin" in invoice_quality_table.columns:
                missing_gstin_mask = invoice_quality_table["counterparty_gstin"].fillna("").astype(str).str.strip().eq("")
            else:
                missing_gstin_mask = pd.Series([False] * len(invoice_quality_table.index))
            invoice_quality_table.loc[duplicate_mask, "Risk Marker"] = "Duplicate Invoice Number"
            invoice_quality_table.loc[missing_gstin_mask, "Risk Marker"] = "Missing GSTIN"

            display_cols = [
                "period",
                "invoice_no",
                "counterparty_name",
                "counterparty_gstin",
                "taxable_value",
                "gst_rate",
                "source_type",
                "Risk Marker",
            ]
            available_display_cols = [col for col in display_cols if col in invoice_quality_table.columns]
            st.markdown("#### Invoice Risk Review")
            st.dataframe(invoice_quality_table[available_display_cols], use_container_width=True, hide_index=True)

        if not df.empty:
            filing_compare = pd.DataFrame(
                {
                    "Period": df["month"],
                    "Output Tax": df["output_tax"].map(compact_money),
                    "ITC Claimed": df["itc_claimed"].map(compact_money),
                    "TDS + TCS": (df["tds_received"] + df["tcs_received"]).map(compact_money),
                    "Net Tax Payable": df["net_tax_payable"].map(compact_money),
                    "Compliance Flag": df.apply(
                        lambda row: "Attention Needed"
                        if row["gstr1_reported"] == 0 or row["gstr3b_reported"] == 0 or row["gstr2a_reported"] == 0
                        else "Compliant",
                        axis=1,
                    ),
                }
            )
            st.markdown("#### Period-wise Compliance Comparison")
            st.dataframe(filing_compare, use_container_width=True, hide_index=True)

        for insight in smart_insights(df):
            st.markdown(f'<div class="card"><div class="section-copy">{insight}</div></div>', unsafe_allow_html=True)

        if not invoice_rows.empty:
            invoice_chart = px.bar(
                invoice_rows,
                x="period",
                y="taxable_value",
                color="source_type",
                title="Invoice Contribution by Period",
                color_discrete_sequence=["#0f766e", "#0f4c81", "#c2851d", "#b42318"],
            )
            st.plotly_chart(invoice_chart, use_container_width=True)

        if not df.empty:
            trend_chart_df = df.copy()
            trend_chart_df["Total Credit"] = trend_chart_df["itc_claimed"] + trend_chart_df["tds_received"] + trend_chart_df["tcs_received"]
            trend_fig = px.line(
                trend_chart_df,
                x="month",
                y=["output_tax", "net_tax_payable", "Total Credit"],
                markers=True,
                title="Tax Liability vs Credit Utilization Trend",
                color_discrete_sequence=["#0f4c81", "#b42318", "#0f766e"],
            )
            trend_fig.update_layout(legend_title_text="Measure", xaxis_title="Period", yaxis_title="Amount")
            st.plotly_chart(trend_fig, use_container_width=True)

        st.markdown(
            """
            <div class="card">
              <div class="section-title">Why This Portal Is Smart</div>
              <div class="section-copy">
                This system does more than data entry. It predicts the next liability, scores compliance health, detects invoice risks,
                highlights missing return actions and gives pre-filing recommendations. That is why the portal can be presented as a
                Smart GST & Compliance Management System rather than a simple GST calculator.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

elif portal_page == "GSTN Integration":
    st.markdown('<div class="card"><div class="section-title">Official GSTN / Government Portal Integration</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="section-copy">
            Real GST filing integration is not an open public API. Production filing typically requires onboarding through
            an authorized GST Suvidha Provider (GSP) / Application Service Provider (ASP) or other government-approved channels.
        </div>
        <div class="section-copy">
            This project now simulates OTP verification, challan generation and payment acknowledgement. For real production filing,
            configure official credentials only after approved GSTN partner onboarding.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.json(integration_status)
    st.markdown("</div>", unsafe_allow_html=True)
