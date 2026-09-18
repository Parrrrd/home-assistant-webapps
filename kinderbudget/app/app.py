from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from flask import Flask, abort, redirect, render_template, request, send_file, url_for
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("KINDERBUDGET_DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = DATA_DIR / "kinderbudget.db"

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
APP_VERSION = "0.7.2"

CATEGORY_LABELS = {
    "allowance": "Auszuzahlendes Taschengeld",
    "gift": "Geldgeschenk offen",
    "debt": "Kind schuldet euch",
    "parent_owes_child": "Ihr schuldet Kind",
    "parent_settlement": "Eltern-Saldo ausgleichen",
    "pocket_income": "Einnahme Kind",
    "pocket_expense": "Ausgabe Kind",
    "pocket_adjustment": "Verfügbares Geld korrigieren",
    "correction": "Korrektur Eltern-Saldo",
}

PARENT_BALANCE_CATEGORIES = {"allowance", "gift", "debt", "parent_owes_child", "parent_settlement", "correction"}
POCKET_BALANCE_CATEGORIES = {"pocket_income", "pocket_expense", "pocket_adjustment"}
BOOKING_CATEGORIES = PARENT_BALANCE_CATEGORIES | POCKET_BALANCE_CATEGORIES
FORM_CATEGORIES = BOOKING_CATEGORIES | {"allowance_payout", "gift_payout"}
PAYOUT_TO_POCKET_CATEGORIES = {"allowance", "gift"}

WEEKDAYS = {
    0: "Montag",
    1: "Dienstag",
    2: "Mittwoch",
    3: "Donnerstag",
    4: "Freitag",
    5: "Samstag",
    6: "Sonntag",
}

CHILD_THEME = {
    "Emil": {"accent": "ocean", "avatar": "boy.svg", "hint": "Taschengeld aktiv"},
    "Luna": {"accent": "violet", "avatar": "girl.svg", "hint": "Flexibles Budget"},
}


def startup() -> None:
    init_db()
    migrate_schema()
    seed_defaults()
    migrate_existing_data()
    generate_due_allowances()


def load_child_row(child_id: int) -> sqlite3.Row:
    with get_conn() as conn:
        child = conn.execute("SELECT * FROM children WHERE id = ?", (child_id,)).fetchone()
    if child is None:
        abort(404, "Kind nicht gefunden")
    return child


def load_child_view(child_id: int) -> dict[str, Any]:
    child = load_child_row(child_id)
    summary = calculate_child_summary(child_id)
    month = calculate_month_summary(child_id)
    return {**dict(child), **summary, **month, **child_theme(child["name"])}


def load_child_transactions(child_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT *
            FROM transactions
            WHERE child_id = ?
            ORDER BY effective_date DESC, created_at DESC, id DESC
            """,
            (child_id,),
        ).fetchall()


@app.route("/")
def overview() -> str:
    generate_due_allowances()
    with get_conn() as conn:
        children = conn.execute("SELECT * FROM children ORDER BY name COLLATE NOCASE").fetchall()

    child_cards: list[dict[str, Any]] = []
    for child in children:
        summary = calculate_child_summary(child["id"])
        month = calculate_month_summary(child["id"])
        child_cards.append({**dict(child), **summary, **month, **child_theme(child["name"])})

    overall = calculate_overall_summary(child_cards)
    return render_template(
        "overview.html",
        children=child_cards,
        overall=overall,
        today_display=format_display_date(date.today().isoformat()),
        month_label=current_month_label(),
        active_page="overview",
    )


@app.route("/child/<int:child_id>")
def child_detail(child_id: int):
    return redirect(url_for("child_history", child_id=child_id))


@app.route("/child/<int:child_id>/history")
def child_history(child_id: int) -> str:
    generate_due_allowances()
    filters = normalize_filters(request.args)
    child = load_child_view(child_id)
    transactions = load_child_transactions(child_id)

    filtered = apply_transaction_filters(transactions, filters)
    view_transactions = [prepare_transaction_view(row) for row in filtered]
    filter_query = build_query_string(filters)

    return render_template(
        "child_history.html",
        child=child,
        transactions=view_transactions,
        weekdays=WEEKDAYS,
        today_iso=date.today().isoformat(),
        today_display=format_display_date(date.today().isoformat()),
        filters=filters,
        filter_query=filter_query,
        active_page="child",
        active_tab="history",
    )


@app.route("/child/<int:child_id>/booking")
def child_booking(child_id: int) -> str:
    generate_due_allowances()
    child = load_child_view(child_id)
    return render_template(
        "child_booking.html",
        child=child,
        today_iso=date.today().isoformat(),
        today_display=format_display_date(date.today().isoformat()),
        active_page="child",
        active_tab="booking",
    )


@app.route("/child/<int:child_id>/automation")
def child_automation(child_id: int) -> str:
    generate_due_allowances()
    child = load_child_view(child_id)
    return render_template(
        "child_automation.html",
        child=child,
        weekdays=WEEKDAYS,
        today_iso=date.today().isoformat(),
        today_display=format_display_date(date.today().isoformat()),
        active_page="child",
        active_tab="automation",
    )


@app.post("/transactions/create")
def create_transaction():
    child_id = int(request.form["child_id"])
    form_category = request.form["category"]
    amount_eur = request.form["amount_eur"]
    note = request.form.get("note", "")
    effective_date = parse_date_to_iso(request.form["effective_date"])

    if form_category not in FORM_CATEGORIES:
        abort(400, "Ungültige Kategorie")

    try:
        amount_cents = abs(parse_euro_to_cents(amount_eur))
    except ValueError:
        abort(400, "Ungültiger Betrag")

    if amount_cents == 0:
        abort(400, "Betrag darf nicht 0 sein")

    summary = calculate_child_summary(child_id)
    category = form_category
    signed_amount_cents = amount_cents

    if form_category == "pocket_income":
        signed_amount_cents = amount_cents
    elif form_category == "pocket_expense":
        signed_amount_cents = -amount_cents
    elif form_category == "pocket_adjustment":
        target_cents = parse_euro_to_cents(amount_eur)
        signed_amount_cents = target_cents - summary["pocket_balance_cents"]
        if signed_amount_cents == 0:
            return redirect(url_for("child_booking", child_id=child_id))
        if not note.strip():
            note = f"Verfügbares Geld auf {euro(target_cents)} gesetzt"
    elif form_category == "parent_settlement":
        current_parent_saldo = summary["parent_saldo_cents"]
        if current_parent_saldo == 0:
            return redirect(url_for("child_booking", child_id=child_id))
        settlement_cents = min(amount_cents, abs(current_parent_saldo))
        signed_amount_cents = -settlement_cents if current_parent_saldo > 0 else settlement_cents
        if not note.strip():
            note = "Eltern-Saldo ausgeglichen"
    elif form_category == "allowance_payout":
        category = "allowance"
        open_cents = summary["open_allowance_cents"]
        if open_cents <= 0:
            return redirect(url_for("child_booking", child_id=child_id))
        signed_amount_cents = -min(amount_cents, open_cents)
        if not note.strip():
            note = "Taschengeld ausgezahlt"
    elif form_category == "gift_payout":
        category = "gift"
        open_cents = summary["open_gifts_cents"]
        if open_cents <= 0:
            return redirect(url_for("child_booking", child_id=child_id))
        signed_amount_cents = -min(amount_cents, open_cents)
        if not note.strip():
            note = "Geldgeschenk ausgezahlt"
    elif form_category in {"allowance", "gift", "debt", "parent_owes_child", "correction"}:
        signed_amount_cents = amount_cents

    now = datetime.now().isoformat(timespec="seconds")
    linked_group = None
    should_add_pocket_income = category in PAYOUT_TO_POCKET_CATEGORIES and signed_amount_cents < 0
    if should_add_pocket_income:
        linked_group = f"payout:{child_id}:{now}:{category}"

    with get_conn() as conn:
        child = conn.execute("SELECT id FROM children WHERE id = ?", (child_id,)).fetchone()
        if child is None:
            abort(404, "Kind nicht gefunden")
        conn.execute(
            """
            INSERT INTO transactions (child_id, category, amount_cents, note, effective_date, created_at, linked_group)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                child_id,
                category,
                signed_amount_cents,
                note.strip(),
                effective_date,
                now,
                linked_group,
            ),
        )
        if should_add_pocket_income:
            payout_label = "Taschengeld ausgezahlt" if category == "allowance" else "Geldgeschenk ausgezahlt"
            pocket_note = note.strip() or payout_label
            conn.execute(
                """
                INSERT INTO transactions (child_id, category, amount_cents, note, effective_date, created_at, linked_group)
                VALUES (?, 'pocket_income', ?, ?, ?, ?, ?)
                """,
                (child_id, abs(signed_amount_cents), pocket_note, effective_date, now, linked_group),
            )
        conn.commit()

    return redirect(url_for("child_history", child_id=child_id))


@app.post("/children/<int:child_id>/payout-allowance")
def payout_allowance(child_id: int):
    child = load_child_view(child_id)
    amount_cents = child["open_allowance_cents"]
    if amount_cents <= 0:
        return redirect(url_for("child_history", child_id=child_id))

    effective_date = parse_date_to_iso(request.form.get("effective_date", date.today().isoformat()))
    note = request.form.get("note", "Taschengeld ausgezahlt").strip() or "Taschengeld ausgezahlt"
    now = datetime.now().isoformat(timespec="seconds")
    linked_group = f"payout:{child_id}:{now}:allowance-full"

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO transactions (child_id, category, amount_cents, note, effective_date, created_at, linked_group)
            VALUES (?, 'allowance', ?, ?, ?, ?, ?)
            """,
            (child_id, -amount_cents, note, effective_date, now, linked_group),
        )
        conn.execute(
            """
            INSERT INTO transactions (child_id, category, amount_cents, note, effective_date, created_at, linked_group)
            VALUES (?, 'pocket_income', ?, ?, ?, ?, ?)
            """,
            (child_id, amount_cents, note, effective_date, now, linked_group),
        )
        conn.commit()

    return redirect(url_for("child_history", child_id=child_id))


@app.post("/transactions/<int:transaction_id>/void")
def void_transaction(transaction_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, child_id, auto_key, voided_at, linked_group FROM transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()
        if row is None:
            abort(404, "Buchung nicht gefunden")
        if row["auto_key"]:
            abort(400, "Automatische Taschengeld-Buchungen bitte über die Einstellungen steuern.")
        if row["voided_at"]:
            return redirect(url_for("child_history", child_id=row["child_id"]))

        voided_at = datetime.now().isoformat(timespec="seconds")
        if row["linked_group"]:
            conn.execute(
                "UPDATE transactions SET voided_at = ? WHERE linked_group = ? AND voided_at IS NULL",
                (voided_at, row["linked_group"]),
            )
        else:
            conn.execute(
                "UPDATE transactions SET voided_at = ? WHERE id = ?",
                (voided_at, transaction_id),
            )
        conn.commit()

    return redirect(url_for("child_history", child_id=row["child_id"]))


@app.post("/children/<int:child_id>/settings")
def update_child_settings(child_id: int):
    enabled = 1 if request.form.get("allowance_enabled") == "on" else 0
    try:
        amount_cents = abs(parse_euro_to_cents(request.form.get("allowance_amount_eur", "0")))
    except ValueError:
        abort(400, "Ungültiger Betrag")
    allowance_weekday = int(request.form.get("allowance_weekday", 6))
    allowance_start_date = parse_date_to_iso(request.form["allowance_start_date"])

    if enabled and amount_cents <= 0:
        abort(400, "Taschengeld muss größer als 0 sein")
    if allowance_weekday not in WEEKDAYS:
        abort(400, "Ungültiger Wochentag")

    with get_conn() as conn:
        exists = conn.execute("SELECT id FROM children WHERE id = ?", (child_id,)).fetchone()
        if exists is None:
            abort(404, "Kind nicht gefunden")
        conn.execute(
            """
            UPDATE children
            SET allowance_enabled = ?, allowance_amount_cents = ?, allowance_weekday = ?, allowance_start_date = ?
            WHERE id = ?
            """,
            (enabled, amount_cents, allowance_weekday, allowance_start_date, child_id),
        )
        conn.commit()

    generate_due_allowances()
    return redirect(url_for("child_automation", child_id=child_id))


@app.post("/children/<int:child_id>/pocket-balance")
def set_pocket_balance(child_id: int):
    child = load_child_view(child_id)
    try:
        target_cents = parse_euro_to_cents(request.form.get("pocket_balance_eur", "0"))
    except ValueError:
        abort(400, "Ungültiges verfügbares Geld")
    effective_date = parse_date_to_iso(request.form.get("effective_date", date.today().isoformat()))
    note_extra = request.form.get("note", "").strip()
    current_cents = child["pocket_balance_cents"]
    diff_cents = target_cents - current_cents
    if diff_cents == 0:
        return redirect(url_for("child_automation", child_id=child_id))

    now = datetime.now().isoformat(timespec="seconds")
    note = f"Verfügbares Geld auf {euro(target_cents)} gesetzt"
    if note_extra:
        note = f"{note} · {note_extra}"

    with get_conn() as conn:
        exists = conn.execute("SELECT id FROM children WHERE id = ?", (child_id,)).fetchone()
        if exists is None:
            abort(404, "Kind nicht gefunden")
        conn.execute(
            """
            INSERT INTO transactions (child_id, category, amount_cents, note, effective_date, created_at)
            VALUES (?, 'pocket_adjustment', ?, ?, ?, ?)
            """,
            (child_id, diff_cents, note, effective_date, now),
        )
        conn.commit()

    return redirect(url_for("child_automation", child_id=child_id))


@app.route("/child/<int:child_id>/history.pdf")
def child_history_pdf(child_id: int):
    generate_due_allowances()
    filters = normalize_filters(request.args)
    with get_conn() as conn:
        child = conn.execute("SELECT * FROM children WHERE id = ?", (child_id,)).fetchone()
        if child is None:
            abort(404, "Kind nicht gefunden")
        transactions = conn.execute(
            """
            SELECT *
            FROM transactions
            WHERE child_id = ?
            ORDER BY effective_date DESC, created_at DESC, id DESC
            """,
            (child_id,),
        ).fetchall()

    filtered = apply_transaction_filters(transactions, filters)
    summary = calculate_child_summary(child_id)
    pdf_bytes = build_history_pdf(dict(child), summary, filtered, filters)
    filename = f"kinderbudget-{slugify(child['name'])}-verlauf-{date.today().isoformat()}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/child/<int:child_id>/history.csv")
def child_history_csv(child_id: int):
    generate_due_allowances()
    filters = normalize_filters(request.args)
    with get_conn() as conn:
        child = conn.execute("SELECT * FROM children WHERE id = ?", (child_id,)).fetchone()
        if child is None:
            abort(404, "Kind nicht gefunden")
        transactions = conn.execute(
            """
            SELECT *
            FROM transactions
            WHERE child_id = ?
            ORDER BY effective_date DESC, created_at DESC, id DESC
            """,
            (child_id,),
        ).fetchall()

    filtered = apply_transaction_filters(transactions, filters)
    csv_bytes = build_history_csv(filtered)
    filename = f"kinderbudget-{slugify(child['name'])}-verlauf-{date.today().isoformat()}.csv"
    return send_file(
        io.BytesIO(csv_bytes),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION, "feature": "verlauf-ohne-vorzeichen"}


@app.template_filter("display_date")
def display_date_filter(value: str | None) -> str:
    if not value:
        return "-"
    return format_display_date(value)


@app.template_filter("qs")
def qs_filter(values: dict[str, Any]) -> str:
    return build_query_string(values)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS children (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                allowance_enabled INTEGER NOT NULL DEFAULT 0,
                allowance_amount_cents INTEGER NOT NULL DEFAULT 0,
                allowance_weekday INTEGER NOT NULL DEFAULT 6,
                allowance_start_date TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                effective_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                auto_key TEXT UNIQUE,
                voided_at TEXT,
                FOREIGN KEY (child_id) REFERENCES children(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.commit()


def migrate_schema() -> None:
    with get_conn() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()}
        if "voided_at" not in columns:
            conn.execute("ALTER TABLE transactions ADD COLUMN voided_at TEXT")
        if "linked_group" not in columns:
            conn.execute("ALTER TABLE transactions ADD COLUMN linked_group TEXT")
        conn.commit()


def seed_defaults() -> None:
    with get_conn() as conn:
        child_count = conn.execute("SELECT COUNT(*) AS count FROM children").fetchone()["count"]
        if child_count == 0:
            today = date.today().isoformat()
            conn.execute(
                """
                INSERT INTO children (name, allowance_enabled, allowance_amount_cents, allowance_weekday, allowance_start_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("Emil", 1, 250, 6, today),
            )
            conn.execute(
                """
                INSERT INTO children (name, allowance_enabled, allowance_amount_cents, allowance_weekday, allowance_start_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("Luna", 0, 0, 6, today),
            )
            conn.commit()


def migrate_existing_data() -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE children SET allowance_amount_cents = 250 WHERE name = 'Emil' AND allowance_amount_cents = 300"
        )
        conn.execute("UPDATE transactions SET category = 'allowance' WHERE category IN ('allowance_auto', 'allowance_manual')")
        conn.execute("UPDATE transactions SET category = 'debt' WHERE category = 'expense'")
        conn.execute("UPDATE transactions SET category = 'allowance', amount_cents = -ABS(amount_cents) WHERE category = 'payout'")

        migration_done = conn.execute("SELECT value FROM app_meta WHERE key = 'debt_sign_fix_v041'").fetchone()
        if migration_done is None:
            conn.execute(
                "UPDATE transactions SET amount_cents = ABS(amount_cents) WHERE category = 'debt' AND amount_cents < 0 AND voided_at IS NULL"
            )
            conn.execute("INSERT INTO app_meta (key, value) VALUES ('debt_sign_fix_v041', 'done')")
        conn.commit()


def generate_due_allowances() -> None:
    today = date.today()
    with get_conn() as conn:
        children = conn.execute(
            "SELECT * FROM children WHERE allowance_enabled = 1 AND allowance_amount_cents > 0"
        ).fetchall()

        for child in children:
            try:
                start_date = date.fromisoformat(child["allowance_start_date"])
            except ValueError:
                start_date = today

            current = start_date + timedelta(days=(child["allowance_weekday"] - start_date.weekday()) % 7)
            while current <= today:
                auto_key = f"allowance:{child['id']}:{current.isoformat()}"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO transactions
                    (child_id, category, amount_cents, note, effective_date, created_at, auto_key)
                    VALUES (?, 'allowance', ?, ?, ?, ?, ?)
                    """,
                    (
                        child["id"],
                        child["allowance_amount_cents"],
                        "Automatisch erzeugt",
                        current.isoformat(),
                        datetime.now().isoformat(timespec="seconds"),
                        auto_key,
                    ),
                )
                current += timedelta(days=7)
        conn.commit()


def calculate_child_summary(child_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        child = conn.execute("SELECT * FROM children WHERE id = ?", (child_id,)).fetchone()
        rows = conn.execute(
            "SELECT category, amount_cents FROM transactions WHERE child_id = ? AND voided_at IS NULL",
            (child_id,),
        ).fetchall()

    allowance_open_cents = 0
    gift_open_cents = 0
    debt_open_cents = 0
    correction_total = 0
    parent_owes_child_total = 0
    parent_settlement_total = 0
    pocket_balance_cents = 0
    pocket_income_total = 0
    pocket_expense_total = 0

    for row in rows:
        category = row["category"]
        amount_cents = row["amount_cents"]
        if category == "allowance":
            allowance_open_cents += amount_cents
        elif category == "gift":
            gift_open_cents += amount_cents
        elif category == "debt":
            debt_open_cents += amount_cents
        elif category == "correction":
            correction_total += amount_cents
        elif category == "parent_owes_child":
            parent_owes_child_total += amount_cents
        elif category == "parent_settlement":
            parent_settlement_total += amount_cents
        elif category in POCKET_BALANCE_CATEGORIES:
            pocket_balance_cents += amount_cents
            if amount_cents >= 0:
                pocket_income_total += amount_cents
            else:
                pocket_expense_total += abs(amount_cents)

    # Eltern-Saldo aus Elternsicht:
    #   positiv  = Kind schuldet euch Geld
    #   negativ  = ihr schuldet dem Kind Geld
    parent_saldo_cents = debt_open_cents + correction_total + parent_settlement_total - allowance_open_cents - gift_open_cents - parent_owes_child_total
    after_settlement_cents = pocket_balance_cents - parent_saldo_cents
    net_balance_cents = parent_saldo_cents
    available_after_payout_cents = after_settlement_cents
    weekly_amount = child["allowance_amount_cents"] if child else 0
    open_allowance_weeks = ""
    if child and child["allowance_enabled"] and weekly_amount > 0 and allowance_open_cents > 0:
        full_weeks = allowance_open_cents // weekly_amount
        remainder = allowance_open_cents % weekly_amount
        parts: list[str] = []
        if full_weeks > 0:
            parts.append(f"{full_weeks} Woche{'n' if full_weeks != 1 else ''}")
        if remainder > 0:
            parts.append(f"{euro(remainder)} Rest")
        open_allowance_weeks = " + ".join(parts)

    debt_display_cents = display_amount_cents("debt", debt_open_cents)
    if parent_saldo_cents > 0:
        parent_saldo_hint = f"Kind schuldet euch {euro(parent_saldo_cents)}"
    elif parent_saldo_cents < 0:
        parent_saldo_hint = f"Ihr schuldet dem Kind {euro(abs(parent_saldo_cents))}"
    else:
        parent_saldo_hint = "Alles ausgeglichen"
    return {
        "open_allowance": signed_euro(allowance_open_cents, zero_unsigned=True),
        "open_allowance_cents": allowance_open_cents,
        "open_allowance_weeks": open_allowance_weeks,
        "open_gifts": signed_euro(gift_open_cents, zero_unsigned=True),
        "open_gifts_cents": gift_open_cents,
        "open_debts": signed_euro(debt_display_cents, zero_unsigned=True),
        "open_debts_cents": debt_open_cents,
        "net_balance": signed_euro(net_balance_cents, zero_unsigned=True),
        "net_balance_cents": net_balance_cents,
        "parent_saldo": signed_euro(parent_saldo_cents, zero_unsigned=True),
        "parent_saldo_cents": parent_saldo_cents,
        "parent_saldo_class": balance_class(parent_saldo_cents),
        "parent_saldo_hint": parent_saldo_hint,
        "saldo_class": balance_class(parent_saldo_cents),
        "pocket_balance": signed_euro(pocket_balance_cents, zero_unsigned=True),
        "pocket_balance_plain": euro(pocket_balance_cents),
        "pocket_balance_input": euro_input(pocket_balance_cents),
        "pocket_balance_cents": pocket_balance_cents,
        "pocket_balance_class": balance_class(pocket_balance_cents),
        "pocket_income_total": signed_euro(pocket_income_total, zero_unsigned=True),
        "pocket_income_total_cents": pocket_income_total,
        "pocket_expense_total": signed_euro(-pocket_expense_total, zero_unsigned=True),
        "pocket_expense_total_cents": pocket_expense_total,
        "after_settlement": signed_euro(after_settlement_cents, zero_unsigned=True),
        "after_settlement_cents": after_settlement_cents,
        "after_settlement_class": balance_class(after_settlement_cents),
        "available_after_payout": signed_euro(available_after_payout_cents, zero_unsigned=True),
        "available_after_payout_cents": available_after_payout_cents,
        "weekly_amount": euro(weekly_amount),
        "allowance_weekday_name": WEEKDAYS.get(child["allowance_weekday"], "-") if child else "-",
        "correction_total": signed_euro(correction_total, zero_unsigned=True),
    }


def calculate_month_summary(child_id: int) -> dict[str, Any]:
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, amount_cents, voided_at FROM transactions WHERE child_id = ? AND effective_date >= ? ORDER BY effective_date DESC",
            (child_id, month_start),
        ).fetchall()

    incoming = 0
    outgoing = 0
    pocket_income = 0
    pocket_expense = 0
    active_count = 0
    for row in rows:
        if row["voided_at"]:
            continue
        active_count += 1
        effect = saldo_effect_cents(row["category"], row["amount_cents"])
        if effect >= 0:
            incoming += effect
        else:
            outgoing += abs(effect)
        if row["category"] in POCKET_BALANCE_CATEGORIES:
            if row["amount_cents"] >= 0:
                pocket_income += row["amount_cents"]
            else:
                pocket_expense += abs(row["amount_cents"])

    return {
        "month_incoming": signed_euro(incoming, zero_unsigned=True),
        "month_incoming_cents": incoming,
        "month_outgoing": signed_euro(-outgoing, zero_unsigned=True),
        "month_outgoing_cents": outgoing,
        "month_net": signed_euro(incoming - outgoing, zero_unsigned=True),
        "month_net_cents": incoming - outgoing,
        "month_pocket_income": signed_euro(pocket_income, zero_unsigned=True),
        "month_pocket_income_cents": pocket_income,
        "month_pocket_expense": signed_euro(-pocket_expense, zero_unsigned=True),
        "month_pocket_expense_cents": pocket_expense,
        "month_pocket_net": signed_euro(pocket_income - pocket_expense, zero_unsigned=True),
        "month_pocket_net_cents": pocket_income - pocket_expense,
        "month_count": active_count,
    }


def calculate_overall_summary(children: list[dict[str, Any]]) -> dict[str, Any]:
    allowance = sum(child["open_allowance_cents"] for child in children)
    gifts = sum(child["open_gifts_cents"] for child in children)
    debts = sum(child["open_debts_cents"] for child in children)
    saldo = sum(child["parent_saldo_cents"] for child in children)
    after_settlement = sum(child["after_settlement_cents"] for child in children)
    pocket_balance = sum(child["pocket_balance_cents"] for child in children)
    month_net = sum(child["month_net_cents"] for child in children)
    month_incoming = sum(child["month_incoming_cents"] for child in children)
    month_outgoing = sum(child["month_outgoing_cents"] for child in children)
    month_pocket_income = sum(child["month_pocket_income_cents"] for child in children)
    month_pocket_expense = sum(child["month_pocket_expense_cents"] for child in children)
    return {
        "allowance": signed_euro(allowance, zero_unsigned=True),
        "gifts": signed_euro(gifts, zero_unsigned=True),
        "debts": signed_euro(display_amount_cents("debt", debts), zero_unsigned=True),
        "saldo": signed_euro(saldo, zero_unsigned=True),
        "saldo_class": balance_class(saldo),
        "after_settlement": signed_euro(after_settlement, zero_unsigned=True),
        "after_settlement_class": balance_class(after_settlement),
        "pocket_balance": signed_euro(pocket_balance, zero_unsigned=True),
        "pocket_balance_class": balance_class(pocket_balance),
        "month_net": signed_euro(month_net, zero_unsigned=True),
        "month_incoming": signed_euro(month_incoming, zero_unsigned=True),
        "month_outgoing": signed_euro(-month_outgoing, zero_unsigned=True),
        "month_pocket_income": signed_euro(month_pocket_income, zero_unsigned=True),
        "month_pocket_expense": signed_euro(-month_pocket_expense, zero_unsigned=True),
    }


def apply_transaction_filters(rows: list[sqlite3.Row], filters: dict[str, str]) -> list[sqlite3.Row]:
    period_cutoff = period_start(filters["period"])
    query = filters["q"].lower()
    filtered: list[sqlite3.Row] = []
    for row in rows:
        if filters["category"] != "all" and row["category"] != filters["category"]:
            continue
        if filters["status"] == "active" and row["voided_at"]:
            continue
        if filters["status"] == "voided" and not row["voided_at"]:
            continue
        if filters["status"] == "auto" and not row["auto_key"]:
            continue
        if filters["status"] == "manual" and row["auto_key"]:
            continue
        if period_cutoff is not None and row["effective_date"] < period_cutoff:
            continue
        if query:
            haystack = " ".join(
                [
                    row["note"] or "",
                    CATEGORY_LABELS.get(row["category"], row["category"]),
                    format_display_date(row["effective_date"]),
                ]
            ).lower()
            if query not in haystack:
                continue
        filtered.append(row)
    return filtered


def normalize_filters(args: Any) -> dict[str, str]:
    category = args.get("category", "all")
    status = args.get("status", "all")
    period = args.get("period", "all")
    query = args.get("q", "").strip()
    if category not in {"all", "allowance", "gift", "debt", "parent_owes_child", "parent_settlement", "pocket_income", "pocket_expense", "pocket_adjustment", "correction"}:
        category = "all"
    if status not in {"all", "active", "voided", "auto", "manual"}:
        status = "all"
    if period not in {"all", "current_month", "30", "90", "365"}:
        period = "all"
    return {"category": category, "status": status, "period": period, "q": query}


def period_start(value: str) -> str | None:
    today = date.today()
    if value == "current_month":
        return today.replace(day=1).isoformat()
    if value == "30":
        return (today - timedelta(days=30)).isoformat()
    if value == "90":
        return (today - timedelta(days=90)).isoformat()
    if value == "365":
        return (today - timedelta(days=365)).isoformat()
    return None


def prepare_transaction_view(row: sqlite3.Row) -> dict[str, Any]:
    raw_cents = row["amount_cents"]
    voided = bool(row["voided_at"])
    category_label = CATEGORY_LABELS.get(row["category"], row["category"])
    if row["category"] == "allowance" and raw_cents < 0:
        category_label = "Taschengeld ausgezahlt"
    elif row["category"] == "gift" and raw_cents < 0:
        category_label = "Geldgeschenk ausgezahlt"
    return {
        **dict(row),
        "category_label": category_label,
        "display_date": format_display_date(row["effective_date"]),
        "impact": euro(abs(raw_cents)),
        "impact_positive": raw_cents > 0 and not voided,
        "impact_negative": raw_cents < 0 and not voided,
        "impact_class": "positive-text" if raw_cents > 0 and not voided else "negative-text" if raw_cents < 0 and not voided else "muted",
        "voided": voided,
        "voided_display": format_display_date(row["voided_at"]) if row["voided_at"] else "",
        "status_label": "gestrichen" if voided else "auto" if row["auto_key"] else "aktiv",
        "status_class": "voided" if voided else "auto" if row["auto_key"] else "active",
        "note_display": row["note"] or "—",
        "linked": bool(row["linked_group"]) if "linked_group" in row.keys() else False,
    }


def display_amount_cents(category: str, amount_cents: int) -> int:
    return amount_cents


def saldo_effect_cents(category: str, amount_cents: int) -> int:
    return amount_cents


def build_history_pdf(
    child: dict[str, Any],
    summary: dict[str, Any],
    transactions: list[sqlite3.Row],
    filters: dict[str, str],
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Kinderbudget Verlauf - {child['name']}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "KBTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#18212f"),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "KBSubtitle",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "KBSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#18212f"),
        spaceBefore=4,
        spaceAfter=8,
    )
    small_style = ParagraphStyle(
        "KBSmall",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#18212f"),
    )
    small_muted_style = ParagraphStyle(
        "KBSmallMuted",
        parent=small_style,
        textColor=colors.HexColor("#6b7280"),
    )

    filter_text = describe_filters(filters)
    story: list[Any] = [
        Paragraph(f"Kinderbudget - {child['name']}", title_style),
        Paragraph(
            f"Stand {format_display_date(date.today().isoformat())} - {filter_text}.",
            subtitle_style,
        ),
    ]

    summary_data = [
        [
            Paragraph("<b>Verfügbares Geld</b>", small_muted_style),
            Paragraph("<b>Nach Verrechnung</b>", small_muted_style),
            Paragraph("<b>Auszuzahlendes Taschengeld</b>", small_muted_style),
            Paragraph("<b>Eltern-Saldo</b>", small_muted_style),
            Paragraph("<b>Offene Kaufschulden</b>", small_muted_style),
        ],
        [
            Paragraph(summary["pocket_balance"], small_style),
            Paragraph(summary["after_settlement"], small_style),
            Paragraph(summary["open_allowance"], small_style),
            Paragraph(summary["parent_saldo"], small_style),
            Paragraph(summary["open_debts"], small_style),
        ],
    ]
    summary_table = Table(summary_data, colWidths=[34 * mm, 34 * mm, 34 * mm, 34 * mm, 34 * mm])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3fb")),
                ("BACKGROUND", (0, 1), (-1, 1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#d9e0ea")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e0ea")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.extend([summary_table, Spacer(1, 12), Paragraph("Verlauf", section_style)])

    history_rows: list[list[Any]] = [[
        Paragraph("<b>Datum</b>", small_muted_style),
        Paragraph("<b>Typ</b>", small_muted_style),
        Paragraph("<b>Notiz</b>", small_muted_style),
        Paragraph("<b>Betrag</b>", small_muted_style),
        Paragraph("<b>Status</b>", small_muted_style),
    ]]

    if not transactions:
        history_rows.append(
            [
                Paragraph("-", small_style),
                Paragraph("-", small_style),
                Paragraph("Keine Buchungen im gewählten Filter.", small_style),
                Paragraph("-", small_style),
                Paragraph("-", small_style),
            ]
        )
    else:
        for tx in transactions:
            view = prepare_transaction_view(tx)
            note_style = small_muted_style if view["voided"] else small_style
            value_style = small_muted_style if view["voided"] else small_style
            history_rows.append(
                [
                    Paragraph(view["display_date"], note_style),
                    Paragraph(view["category_label"], note_style),
                    Paragraph(view["note_display"], note_style),
                    Paragraph(view["impact"], value_style),
                    Paragraph(view["status_label"], note_style),
                ]
            )

    history_table = Table(history_rows, repeatRows=1, colWidths=[26 * mm, 34 * mm, 72 * mm, 28 * mm, 22 * mm])
    table_style_commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3fb")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#d9e0ea")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e0ea")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for idx, tx in enumerate(transactions, start=1):
        if tx["voided_at"]:
            table_style_commands.extend(
                [
                    ("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#f8fafc")),
                    ("TEXTCOLOR", (0, idx), (-1, idx), colors.HexColor("#6b7280")),
                ]
            )
    history_table.setStyle(TableStyle(table_style_commands))
    story.append(history_table)

    doc.build(story)
    return buffer.getvalue()


def build_history_csv(transactions: list[sqlite3.Row]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Datum", "Typ", "Notiz", "Betrag", "Status"])
    for tx in transactions:
        view = prepare_transaction_view(tx)
        writer.writerow(
            [
                view["display_date"],
                view["category_label"],
                view["note_display"],
                view["impact"],
                view["status_label"],
            ]
        )
    return output.getvalue().encode("utf-8-sig")


def child_theme(name: str) -> dict[str, str]:
    theme = CHILD_THEME.get(name, {"accent": "sun", "emoji": "👧", "initials": name[:1].upper(), "hint": "Kinderbudget"})
    return theme


def current_month_label() -> str:
    months = [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ]
    today = date.today()
    return f"{months[today.month - 1]} {today.year}"


def describe_filters(filters: dict[str, str]) -> str:
    parts = ["gefilterter Verlauf"]
    if filters["category"] != "all":
        parts.append(CATEGORY_LABELS.get(filters["category"], filters["category"]))
    if filters["status"] != "all":
        status_map = {"active": "nur aktiv", "voided": "nur gestrichen", "auto": "nur automatisch", "manual": "nur manuell"}
        parts.append(status_map.get(filters["status"], filters["status"]))
    if filters["period"] != "all":
        period_map = {"current_month": "aktueller Monat", "30": "letzte 30 Tage", "90": "letzte 90 Tage", "365": "letzte 12 Monate"}
        parts.append(period_map.get(filters["period"], filters["period"]))
    if filters["q"]:
        parts.append(f"Suche: {filters['q']}")
    return " · ".join(parts)


def build_query_string(values: dict[str, Any]) -> str:
    clean = {key: value for key, value in values.items() if value and value != "all"}
    return urlencode(clean)


def balance_class(cents: int) -> str:
    if cents > 0:
        return "positive"
    if cents < 0:
        return "negative"
    return "neutral"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def parse_euro_to_cents(raw_value: str) -> int:
    normalized = raw_value.strip().replace("€", "").replace(" ", "")
    normalized = normalized.replace(".", "").replace(",", ".")
    if not normalized:
        raise ValueError("Betrag fehlt")
    value = float(normalized)
    return int(round(value * 100))


def parse_date_to_iso(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        raise ValueError("Datum fehlt")
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Ungültiges Datum")


def format_display_date(value: str) -> str:
    if not value:
        return "-"
    try:
        if "T" in value:
            return datetime.fromisoformat(value).strftime("%d.%m.%Y")
        return date.fromisoformat(value).strftime("%d.%m.%Y")
    except ValueError:
        return value


def euro(cents: int) -> str:
    euros = cents / 100
    formatted = f"{euros:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} €"


def signed_euro(cents: int, zero_unsigned: bool = False) -> str:
    if cents == 0 and zero_unsigned:
        return euro(0)
    prefix = "+" if cents > 0 else ""
    return f"{prefix}{euro(cents)}" if cents >= 0 else f"-{euro(abs(cents))}"


def euro_input(cents: int) -> str:
    euros = cents / 100
    return f"{euros:.2f}".replace(".", ",")


def slugify(value: str) -> str:
    simplified = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return simplified.strip("-") or "verlauf"


startup()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8128")))
