import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "gst_portal.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS company_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            ticker TEXT,
            gstin TEXT UNIQUE NOT NULL,
            state_code TEXT NOT NULL,
            trade_name TEXT,
            business_type TEXT,
            state_name TEXT,
            filing_frequency TEXT DEFAULT 'Monthly',
            registration_status TEXT DEFAULT 'Active',
            principal_place TEXT,
            auth_signatory TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            role TEXT DEFAULT 'Taxpayer',
            linked_gstin TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_sessions (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS gst_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gstin TEXT NOT NULL,
            financial_year TEXT NOT NULL,
            month TEXT NOT NULL,
            turnover REAL NOT NULL DEFAULT 0,
            purchase_value REAL NOT NULL DEFAULT 0,
            gst_rate REAL NOT NULL DEFAULT 18,
            is_inter_state INTEGER NOT NULL DEFAULT 0,
            itc_claimed REAL NOT NULL DEFAULT 0,
            tds_received REAL NOT NULL DEFAULT 0,
            tcs_received REAL NOT NULL DEFAULT 0,
            gstr1_reported INTEGER NOT NULL DEFAULT 0,
            gstr3b_reported INTEGER NOT NULL DEFAULT 0,
            gstr2a_reported INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS invoice_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gstin TEXT NOT NULL,
            financial_year TEXT NOT NULL,
            period TEXT NOT NULL,
            invoice_no TEXT NOT NULL,
            invoice_date TEXT NOT NULL,
            doc_type TEXT NOT NULL DEFAULT 'Tax Invoice',
            counterparty_gstin TEXT NOT NULL,
            counterparty_name TEXT,
            place_of_supply TEXT,
            taxable_value REAL NOT NULL DEFAULT 0,
            gst_rate REAL NOT NULL DEFAULT 18,
            is_inter_state INTEGER NOT NULL DEFAULT 0,
            source_type TEXT NOT NULL DEFAULT 'Manual',
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (gstin, financial_year, period, invoice_no, source_type)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS filing_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gstin TEXT NOT NULL,
            financial_year TEXT NOT NULL,
            period TEXT NOT NULL,
            return_type TEXT NOT NULL,
            registered_mobile TEXT,
            otp_code TEXT,
            challan_no TEXT,
            payment_mode TEXT,
            payment_status TEXT DEFAULT 'Draft',
            ack_no TEXT,
            filed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (gstin, financial_year, period, return_type)
        )
        """
    )

    existing_cols = {
        row["name"]
        for row in cur.execute("PRAGMA table_info(company_profiles)").fetchall()
    }
    extra_columns = {
        "trade_name": "TEXT",
        "business_type": "TEXT",
        "state_name": "TEXT",
        "filing_frequency": "TEXT DEFAULT 'Monthly'",
        "registration_status": "TEXT DEFAULT 'Active'",
        "principal_place": "TEXT",
        "auth_signatory": "TEXT",
    }
    for column, definition in extra_columns.items():
        if column not in existing_cols:
            cur.execute(f"ALTER TABLE company_profiles ADD COLUMN {column} {definition}")

    user_cols = {
        row["name"]
        for row in cur.execute("PRAGMA table_info(users)").fetchall()
    }
    if "linked_gstin" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN linked_gstin TEXT")

    conn.commit()
    conn.close()


def insert_company(
    company_name: str,
    ticker: str,
    gstin: str,
    state_code: str,
    trade_name: str = "",
    business_type: str = "Private Limited / Listed Entity",
    state_name: str = "",
    filing_frequency: str = "Monthly",
    registration_status: str = "Active",
    principal_place: str = "",
    auth_signatory: str = "",
):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO company_profiles (
            company_name, ticker, gstin, state_code, trade_name, business_type,
            state_name, filing_frequency, registration_status, principal_place, auth_signatory
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_name,
            ticker,
            gstin,
            state_code,
            trade_name,
            business_type,
            state_name,
            filing_frequency,
            registration_status,
            principal_place,
            auth_signatory,
        ),
    )
    conn.commit()
    conn.close()


def get_companies():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT company_name, ticker, gstin, state_code, trade_name, business_type,
               state_name, filing_frequency, registration_status, principal_place, auth_signatory
        FROM company_profiles
        ORDER BY company_name
        """
    ).fetchall()
    conn.close()
    return rows


def company_exists(gstin: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM company_profiles WHERE gstin = ?",
        (gstin,),
    ).fetchone()
    conn.close()
    return row is not None


def create_user(username: str, password_hash: str, full_name: str = "", role: str = "Taxpayer"):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (username, password_hash, full_name, role)
        VALUES (?, ?, ?, ?)
        """,
        (username, password_hash, full_name, role),
    )
    conn.commit()
    conn.close()


def get_user_by_username(username: str):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT id, username, password_hash, full_name, role, linked_gstin, created_at
        FROM users
        WHERE username = ?
        """,
        (username,),
    ).fetchone()
    conn.close()
    return row


def create_auth_session(token: str, username: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO auth_sessions (token, username)
        VALUES (?, ?)
        """,
        (token, username),
    )
    conn.commit()
    conn.close()


def get_auth_session(token: str):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT token, username, created_at
        FROM auth_sessions
        WHERE token = ?
        """,
        (token,),
    ).fetchone()
    conn.close()
    return row


def update_user_linked_gstin(username: str, linked_gstin: str):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET linked_gstin = ? WHERE username = ?",
        (linked_gstin, username),
    )
    conn.commit()
    conn.close()


def get_company_by_gstin(gstin: str):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT company_name, ticker, gstin, state_code, trade_name, business_type,
               state_name, filing_frequency, registration_status, principal_place, auth_signatory
        FROM company_profiles
        WHERE gstin = ?
        """,
        (gstin,),
    ).fetchone()
    conn.close()
    return row


def delete_auth_session(token: str):
    conn = get_conn()
    conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def upsert_gst_entry(payload: dict):
    conn = get_conn()
    cur = conn.cursor()

    existing = cur.execute(
        """
        SELECT id FROM gst_entries
        WHERE gstin = ? AND financial_year = ? AND month = ?
        """,
        (payload["gstin"], payload["financial_year"], payload["month"]),
    ).fetchone()

    if existing:
        cur.execute(
            """
            UPDATE gst_entries
            SET turnover = ?, purchase_value = ?, gst_rate = ?, is_inter_state = ?,
                itc_claimed = ?, tds_received = ?, tcs_received = ?,
                gstr1_reported = ?, gstr3b_reported = ?, gstr2a_reported = ?, notes = ?
            WHERE id = ?
            """,
            (
                payload["turnover"],
                payload["purchase_value"],
                payload["gst_rate"],
                payload["is_inter_state"],
                payload["itc_claimed"],
                payload["tds_received"],
                payload["tcs_received"],
                payload["gstr1_reported"],
                payload["gstr3b_reported"],
                payload["gstr2a_reported"],
                payload["notes"],
                existing["id"],
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO gst_entries (
                gstin, financial_year, month, turnover, purchase_value, gst_rate, is_inter_state,
                itc_claimed, tds_received, tcs_received, gstr1_reported, gstr3b_reported, gstr2a_reported, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["gstin"],
                payload["financial_year"],
                payload["month"],
                payload["turnover"],
                payload["purchase_value"],
                payload["gst_rate"],
                payload["is_inter_state"],
                payload["itc_claimed"],
                payload["tds_received"],
                payload["tcs_received"],
                payload["gstr1_reported"],
                payload["gstr3b_reported"],
                payload["gstr2a_reported"],
                payload["notes"],
            ),
        )

    conn.commit()
    conn.close()


def get_gst_entries(gstin: str, financial_year: Optional[str] = None):
    conn = get_conn()
    if financial_year:
        rows = conn.execute(
            """
            SELECT * FROM gst_entries
            WHERE gstin = ? AND financial_year = ?
            ORDER BY month
            """,
            (gstin, financial_year),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM gst_entries
            WHERE gstin = ?
            ORDER BY financial_year, month
            """,
            (gstin,),
        ).fetchall()
    conn.close()
    return rows


def add_invoice_entry(payload: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO invoice_entries (
            gstin, financial_year, period, invoice_no, invoice_date, doc_type,
            counterparty_gstin, counterparty_name, place_of_supply, taxable_value,
            gst_rate, is_inter_state, source_type, note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["gstin"],
            payload["financial_year"],
            payload["period"],
            payload["invoice_no"],
            payload["invoice_date"],
            payload["doc_type"],
            payload["counterparty_gstin"],
            payload["counterparty_name"],
            payload["place_of_supply"],
            payload["taxable_value"],
            payload["gst_rate"],
            payload["is_inter_state"],
            payload["source_type"],
            payload["note"],
        ),
    )
    conn.commit()
    conn.close()


def get_invoice_entries(gstin: str, financial_year: Optional[str] = None, period: Optional[str] = None):
    conn = get_conn()
    query = "SELECT * FROM invoice_entries WHERE gstin = ?"
    params = [gstin]
    if financial_year:
        query += " AND financial_year = ?"
        params.append(financial_year)
    if period:
        query += " AND period = ?"
        params.append(period)
    query += " ORDER BY invoice_date, invoice_no"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def record_filing_event(payload: dict):
    conn = get_conn()
    cur = conn.cursor()
    existing = cur.execute(
        """
        SELECT id FROM filing_events
        WHERE gstin = ? AND financial_year = ? AND period = ? AND return_type = ?
        """,
        (
            payload["gstin"],
            payload["financial_year"],
            payload["period"],
            payload["return_type"],
        ),
    ).fetchone()

    values = (
        payload["registered_mobile"],
        payload["otp_code"],
        payload["challan_no"],
        payload["payment_mode"],
        payload["payment_status"],
        payload["ack_no"],
        payload["filed_at"],
    )

    if existing:
        cur.execute(
            """
            UPDATE filing_events
            SET registered_mobile = ?, otp_code = ?, challan_no = ?, payment_mode = ?,
                payment_status = ?, ack_no = ?, filed_at = ?
            WHERE id = ?
            """,
            values + (existing["id"],),
        )
    else:
        cur.execute(
            """
            INSERT INTO filing_events (
                gstin, financial_year, period, return_type, registered_mobile, otp_code,
                challan_no, payment_mode, payment_status, ack_no, filed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["gstin"],
                payload["financial_year"],
                payload["period"],
                payload["return_type"],
            ) + values,
        )

    conn.commit()
    conn.close()


def get_filing_event(gstin: str, financial_year: str, period: str, return_type: str):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT * FROM filing_events
        WHERE gstin = ? AND financial_year = ? AND period = ? AND return_type = ?
        """,
        (gstin, financial_year, period, return_type),
    ).fetchone()
    conn.close()
    return row
