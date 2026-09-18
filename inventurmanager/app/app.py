import difflib
import json
import logging
import os
import re
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path
from flask import Flask, flash, g, jsonify, redirect, render_template, request, send_file, url_for
APP_DIR = Path('/app')
DATA_DIR = Path('/data')
DB_PATH = DATA_DIR / 'inventurmanager.db'
LOG_PATH = DATA_DIR / 'inventurmanager.log'

SHOPPING_DEFAULTS = [
    ('maiwoche', 'Maiwoche', [
        ('Verpackung & Ausgabe', 'Flaschenbürste', ''),
        ('Verpackung & Ausgabe', 'Schaschlikspieße 20 cm', ''),
        ('Verpackung & Ausgabe', 'Servietten', ''),
        ('Verpackung & Ausgabe', 'Spülmittel', ''),
        ('Verpackung & Ausgabe', 'Gabeln Crêpes', ''),
        ('Verpackung & Ausgabe', 'Strohhalme', ''),
        ('Verpackung & Ausgabe', 'Mutzentüte mit Dip Groß 27 cm x 21,5 cm', ''),
        ('Verpackung & Ausgabe', 'Tabletts 11 x 17,5', ''),
        ('Verpackung & Ausgabe', 'Mutzentüte mit Dip Klein 23,5 cm x 19 cm', ''),
        ('Verpackung & Ausgabe', 'Papiertragetüten', ''),
        ('Verpackung & Ausgabe', 'Krapfentüten', ''),
        ('Verpackung & Ausgabe', 'Doppeltüten', ''),
        ('Verpackung & Ausgabe', 'Spitztüten', ''),
        ('Verpackung & Ausgabe', 'Sahnepapier', ''),
        ('Süßwaren', 'Kinderschokolade', ''),
        ('Süßwaren', 'Yogurette', ''),
        ('Süßwaren', 'Weiße Schokolade', ''),
        ('Süßwaren', 'Duplo', ''),
        ('Süßwaren', 'Dickmanns', ''),
        ('Reinigung & Verbrauch', 'Kratzschwamm', ''),
        ('Reinigung & Verbrauch', 'Zewa', ''),
        ('Reinigung & Verbrauch', 'Alufolie', ''),
        ('Reinigung & Verbrauch', 'Müllbeutel', ''),
        ('Reinigung & Verbrauch', 'Seife', ''),
        ('Spirituosen', 'Vodka', ''),
        ('Spirituosen', 'Eierlikör', ''),
        ('Spirituosen', 'Grand Marnier', ''),
        ('Spirituosen', 'Amaretto', ''),
        ('Obst & Füllungen', 'Erdbeersirup', ''),
        ('Obst & Füllungen', 'Apfelmus', ''),
        ('Obst & Füllungen', 'Kirschen', ''),
        ('Obst & Füllungen', 'Erdbeeren', ''),
        ('Obst & Füllungen', 'Bananen', ''),
        ('Backen & Würzen', 'Zucker', ''),
        ('Backen & Würzen', 'Haselnuss-Krokant', ''),
        ('Backen & Würzen', 'Schokostreusel', ''),
        ('Backen & Würzen', 'Nutella', ''),
        ('Backen & Würzen', 'Salz', ''),
        ('Backen & Würzen', 'Kräutersalz', ''),
        ('Backen & Würzen', 'Erdbeermarmelade Schwartau', ''),
        ('Backen & Würzen', 'Paprika', ''),
        ('Backen & Würzen', 'Zimt', ''),
        ('Backen & Würzen', 'Kakaopulver', ''),
        ('Backen & Würzen', 'Mehl', ''),
        ('Backen & Würzen', 'Kartoffelpuder', ''),
        ('Herzhaft', 'Salami', ''),
        ('Herzhaft', 'Kochschinken', ''),
        ('Kühlung & Molkerei', 'Käse 1 kg', ''),
        ('Kühlung & Molkerei', 'H-Milch', ''),
        ('Kühlung & Molkerei', 'Öl', ''),
        ('Kühlung & Molkerei', 'Debic Sprühsahne', ''),
        ('Kühlung & Molkerei', 'Hafermilch Edeka', ''),
        ('Kühlung & Molkerei', 'Butter Edeka', ''),
        ('Kühlung & Molkerei', 'Vanillesauce', ''),
        ('Kühlung & Molkerei', 'Eier 180er', ''),
    ]),
    ('plaetze', 'Plätze', [
        ('Verpackung & Ausgabe', 'Servietten', ''),
        ('Verpackung & Ausgabe', 'Pommesgabeln', ''),
        ('Verpackung & Ausgabe', 'Tabletts 11 x 17,5', ''),
        ('Verpackung & Ausgabe', 'Papiertragetüten', ''),
        ('Verpackung & Ausgabe', 'Bäckerfalttüten', ''),
        ('Verpackung & Ausgabe', 'Doppeltüten', ''),
        ('Verpackung & Ausgabe', 'Spitztüten', ''),
        ('Verpackung & Ausgabe', 'Mutzen-Saucenbehälter', ''),
        ('Verpackung & Ausgabe', 'Gabeln', ''),
        ('Süßwaren', 'Weiße Schokolade', ''),
        ('Süßwaren', 'Duplo', ''),
        ('Süßwaren', 'Kinderschokolade', ''),
        ('Süßwaren', 'Dickmanns', ''),
        ('Süßwaren', 'Yogurette', ''),
        ('Reinigung & Verbrauch', 'Alufolie einpacken', ''),
        ('Reinigung & Verbrauch', 'Spülmittel', ''),
        ('Reinigung & Verbrauch', 'Zewa', ''),
        ('Reinigung & Verbrauch', 'Müllbeutel', ''),
        ('Reinigung & Verbrauch', 'Kratzschwamm', ''),
        ('Reinigung & Verbrauch', 'Alufolie Pely', ''),
        ('Reinigung & Verbrauch', 'Seife', ''),
        ('Getränke', 'Amaretto', ''),
        ('Getränke', 'Capri-Sun', ''),
        ('Getränke', 'Eierlikör', ''),
        ('Getränke', 'Grand Marnier', ''),
        ('Obst & Füllungen', 'Debic Sahne', ''),
        ('Obst & Füllungen', 'Apfelmus', ''),
        ('Obst & Füllungen', 'Kirschen', ''),
        ('Obst & Füllungen', 'Bananen', ''),
        ('Obst & Füllungen', 'Erdbeeren', ''),
        ('Backen & Würzen', 'Backstärke', ''),
        ('Backen & Würzen', 'Mehl', ''),
        ('Backen & Würzen', 'Öl', ''),
        ('Backen & Würzen', 'Zucker', ''),
        ('Backen & Würzen', 'Kakaopulver', ''),
        ('Backen & Würzen', 'Marmelade vorne', ''),
        ('Backen & Würzen', 'Marmelade', ''),
        ('Backen & Würzen', 'Salz', ''),
        ('Backen & Würzen', 'Vanillesauce', ''),
        ('Backen & Würzen', 'Rosinen', ''),
        ('Backen & Würzen', 'Nutella', ''),
        ('Backen & Würzen', 'Eier', ''),
        ('Backen & Würzen', 'Karamellsauce', ''),
        ('Backen & Würzen', 'Haselnuss-Krokant', ''),
        ('Backen & Würzen', 'Zimt', ''),
        ('Backen & Würzen', 'Paprika', ''),
        ('Backen & Würzen', 'Kräutersalz', ''),
        ('Backen & Würzen', 'Schokostreusel', ''),
        ('Herzhaft', 'Salami', ''),
        ('Herzhaft', 'Kochschinken', ''),
        ('Kühlung & Molkerei', 'H-Milch', ''),
        ('Kühlung & Molkerei', 'Käse', ''),
        ('Kühlung & Molkerei', 'Butter', ''),
        ('Kühlung & Molkerei', 'Hafermilch', ''),
        ('Kaffee', 'Kaffeepulver', ''),
    ]),
    ('weihnachtsmarkt', 'Weihnachtsmarkt', [
        ('Kaffee', 'Espresso', ''),
        ('Kaffee', 'Café Crema', ''),
        ('Spirituosen & Wein', 'Holiday', ''),
        ('Spirituosen & Wein', 'Eierlikör', ''),
        ('Spirituosen & Wein', 'italienischer Bauernwein Weiß', ''),
        ('Spirituosen & Wein', 'Amaretto billig', ''),
        ('Spirituosen & Wein', 'Whiskey', ''),
        ('Spirituosen & Wein', 'Likör 43', ''),
        ('Spirituosen & Wein', 'Rum', ''),
        ('Spirituosen & Wein', 'Kinderpunsch Flasche', ''),
        ('Spirituosen & Wein', 'Maria Krohn', ''),
        ('Spirituosen & Wein', 'Vodka', ''),
        ('Spirituosen & Wein', 'Cointreau billig', ''),
        ('Spirituosen & Wein', 'Aperol', ''),
        ('Spirituosen & Wein', 'Jagertee', ''),
        ('Spirituosen & Wein', 'Tunnel', ''),
        ('Spirituosen & Wein', 'Calvado', ''),
        ('Spirituosen & Wein', 'Baileys', ''),
        ('Spirituosen & Wein', 'Pfefferminz', ''),
        ('Molkerei', 'H-Milch', ''),
        ('Molkerei', 'Sahne', ''),
        ('Betrieb', 'Gas', ''),
        ('Gebäck', 'Spritzgebäck', ''),
        ('Gebäck', 'Spekulatius', ''),
        ('Heißgetränke', 'Heiße Zitrone', ''),
        ('Heißgetränke', 'Heißer Holunder', ''),
        ('Heißgetränke', 'Vanille Aroma', ''),
        ('Heißgetränke', 'Kandis', ''),
        ('Heißgetränke', 'Süßstoff', ''),
        ('Reinigung & Verbrauch', 'Zewa', ''),
        ('Reinigung & Verbrauch', 'Müllbeutel 120 l', ''),
        ('Reinigung & Verbrauch', 'Spülmittel Aloe Vera', ''),
        ('Reinigung & Verbrauch', 'Spülmittel Spülmaschine', ''),
        ('Reinigung & Verbrauch', 'Klarspüler', ''),
        ('Reinigung & Verbrauch', 'Kellnerblöcke', ''),
        ('Reinigung & Verbrauch', 'Pflaster', ''),
        ('Reinigung & Verbrauch', 'Piniken', ''),
        ('Reinigung & Verbrauch', 'Müllbeutel 40 l Henkel', ''),
        ('Reinigung & Verbrauch', 'Flaschenbürste', ''),
        ('Reinigung & Verbrauch', 'Milchaufschäumerreiniger', ''),
    ]),
]
DATA_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'inventurmanager-dev-secret')
def log_event(message: str) -> None:
    logging.info(message)
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()
def execute(query, params=(), many=False):
    db = get_db()
    cur = db.cursor()
    if many:
        cur.executemany(query, params)
    else:
        cur.execute(query, params)
    db.commit()
    return cur
def query_all(query, params=()):
    return get_db().execute(query, params).fetchall()
def query_one(query, params=()):
    return get_db().execute(query, params).fetchone()

def app_meta_get(key, default=''):
    row = query_one('SELECT meta_value FROM app_meta WHERE meta_key = ?', (key,))
    return (row['meta_value'] if row and row['meta_value'] is not None else default)

def app_meta_set(key, value):
    execute(
        'INSERT OR REPLACE INTO app_meta (meta_key, meta_value, updated_at) VALUES (?, ?, ?)',
        (key, str(value or ''), now_iso()),
    )

def default_shopping_slug():
    slug = app_meta_get('shopping_default_event_slug', '').strip()
    if slug and query_one('SELECT id FROM shopping_events WHERE slug = ?', (slug,)):
        return slug
    first = query_one('SELECT slug FROM shopping_events ORDER BY sort_order, name COLLATE NOCASE LIMIT 1')
    return first['slug'] if first else ''
def money(value):
    if value is None:
        return '–'
    return f'{float(value):,.2f} €'.replace(',', 'X').replace('.', ',').replace('X', '.')
def qty(value):
    if value is None:
        return '–'
    fval = float(value)
    if fval.is_integer():
        return str(int(fval))
    text = f'{fval:,.3f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return text.rstrip('0').rstrip(',')
def dmy(value):
    if not value:
        return '–'
    text = str(value).strip()
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d.%m.%Y'):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime('%d.%m.%Y')
        except ValueError:
            continue
    return text
app.jinja_env.globals['money'] = money
app.jinja_env.globals['qty'] = qty
app.jinja_env.globals['dmy'] = dmy

def compact_label(value, max_len=18):
    text = (value or '').strip()
    try:
        max_len = int(max_len)
    except (TypeError, ValueError):
        max_len = 18
    if max_len < 4 or len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + '…'

app.jinja_env.globals['compact_label'] = compact_label


def _int_or_none(value):
    text = str(value or '').strip()
    return int(text) if text.isdigit() else None

def variant_return_target(group_id=None, variant_id=None):
    gid = _int_or_none(group_id)
    if gid:
        return redirect(url_for('article_detail', group_id=gid))
    vid = _int_or_none(variant_id)
    if vid:
        return redirect(url_for('variant_detail', variant_id=vid))
    return redirect(url_for('new_variant'))

def format_purchase_display(purchase_quantity, purchase_unit_label):
    if purchase_quantity in (None, ''):
        return '–'
    unit = (purchase_unit_label or '').strip()
    try:
        qty_val = float(purchase_quantity)
    except (TypeError, ValueError):
        qty_val = None
    if qty_val is None:
        return f"{purchase_quantity} {unit}".strip()
    if qty_val <= 0:
        return '–' if not unit else unit
    if unit:
        packed = re.match(r'^\s*(\d+(?:[\.,]\d+)?)\s+(.+)$', unit)
        if packed:
            try:
                inner_qty = float(packed.group(1).replace(',', '.'))
            except ValueError:
                inner_qty = None
            inner_unit = packed.group(2).strip()
            if inner_qty and inner_unit:
                total = qty_val * inner_qty
                return f"{qty(total)} {inner_unit}".strip()
    if abs(qty_val - 1.0) < 1e-9 and unit and re.match(r'^\s*\d', unit):
        return unit
    return f"{qty(qty_val)} {unit}".strip()

app.jinja_env.globals['format_purchase_display'] = format_purchase_display
def normalize_text(value: str) -> str:
    text = (value or '').strip().lower()
    repl = str.maketrans({'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss'})
    text = text.translate(repl)
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()
def parse_number(value: str):
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace('€', '').replace('EUR', '').replace('eur', '')
    cleaned = cleaned.replace('Stk.', '').replace('Stk', '').replace('stk', '')
    cleaned = cleaned.strip()
    cleaned = re.sub(r'[^0-9,.-]', '', cleaned)
    if not cleaned or cleaned in {'-', '.', ','}:
        return None
    if ',' in cleaned and '.' in cleaned:
        if cleaned.rfind(',') > cleaned.rfind('.'):
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    else:
        cleaned = cleaned.replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return None
def variant_search_options():
    return query_all(
        '''
        SELECT v.id, g.id AS group_id, g.name AS group_name, v.variant_label,
               g.name || ' – ' || v.variant_label AS display_name
        FROM article_variants v
        JOIN article_groups g ON g.id = v.group_id
        WHERE v.is_active = 1
        ORDER BY g.name COLLATE NOCASE, v.variant_label COLLATE NOCASE
        '''
    )

def variant_search_entries():
    entries = []
    seen = set()
    for row in variant_search_options():
        display_name = (row['display_name'] or '').strip()
        group_name = (row['group_name'] or '').strip()
        variant_label = (row['variant_label'] or '').strip()
        if display_name:
            key = ('variant', normalize_text(display_name))
            if key not in seen:
                seen.add(key)
                entries.append({
                    'display_name': display_name,
                    'group_name': group_name,
                    'variant_label': variant_label,
                    'kind': 'variant',
                })
        if group_name:
            key = ('group', normalize_text(group_name))
            if key not in seen:
                seen.add(key)
                entries.append({
                    'display_name': group_name,
                    'group_name': group_name,
                    'variant_label': 'Stück',
                    'kind': 'group',
                })
    return entries


def article_search_entries():
    rows = query_all(
        '''
        SELECT g.id, g.name,
               GROUP_CONCAT(DISTINCT TRIM(COALESCE(NULLIF(v.stock_unit, ''), NULLIF(v.variant_label, ''), ''))) AS labels
        FROM article_groups g
        LEFT JOIN article_variants v ON v.group_id = g.id AND v.is_active = 1
        GROUP BY g.id, g.name
        ORDER BY g.name COLLATE NOCASE
        '''
    )
    alias_rows = query_all('SELECT group_id, alias_name FROM article_aliases ORDER BY alias_name COLLATE NOCASE')
    alias_map = {}
    for row in alias_rows:
        alias_map.setdefault(row['group_id'], []).append(row['alias_name'])
    entries = []
    for row in rows:
        labels = []
        raw_labels = (row['labels'] or '').split(',') if row['labels'] else []
        seen_labels = set()
        for label in raw_labels:
            label = (label or '').strip()
            norm = normalize_text(label)
            if label and norm not in seen_labels:
                seen_labels.add(norm)
                labels.append(label)
        entries.append({
            'group_id': row['id'],
            'name': row['name'],
            'labels': labels,
            'aliases': alias_map.get(row['id'], []),
        })
    return entries


def find_group_by_alias(name: str):
    raw = (name or '').strip()
    if not raw:
        return None
    norm = normalize_text(raw)
    if not norm:
        return None
    return query_one(
        '''
        SELECT g.id, g.name
        FROM article_aliases a
        JOIN article_groups g ON g.id = a.group_id
        WHERE a.normalized_alias = ?
        ''',
        (norm,),
    )


def upsert_article_alias(alias_name: str, group_id: int):
    raw = (alias_name or '').strip()
    if not raw or not group_id:
        return
    norm = normalize_text(raw)
    if not norm:
        return
    group_row = query_one('SELECT name FROM article_groups WHERE id = ?', (group_id,))
    if not group_row:
        return
    if normalize_text(group_row['name']) == norm:
        return
    existing = query_one('SELECT id, group_id FROM article_aliases WHERE normalized_alias = ?', (norm,))
    if existing:
        execute('UPDATE article_aliases SET alias_name = ?, group_id = ? WHERE id = ?', (raw, group_id, existing['id']))
    else:
        execute('INSERT INTO article_aliases (alias_name, normalized_alias, group_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)', (raw, norm, group_id, now_iso(), now_iso()))
def resolve_supplier_input(raw_name: str):
    supplier_text = (raw_name or '').strip()
    if not supplier_text:
        return None, None
    existing = query_one('SELECT id, name FROM suppliers WHERE lower(name)=lower(?)', (supplier_text,))
    if existing:
        return existing['id'], existing['name']
    supplier_id = ensure_supplier(supplier_text)
    return supplier_id, supplier_text
def resolve_existing_variant(variant_search='', article_name='', variant_label=''):
    options = variant_search_options()
    search_norm = normalize_text(variant_search)
    article_norm = normalize_text(article_name)
    variant_norm = normalize_text(variant_label)

    def exact_match(pred):
        for opt in options:
            if pred(opt):
                return opt
        return None

    if search_norm:
        found = exact_match(lambda o: normalize_text(o['display_name']) == search_norm)
        if found:
            return found

    # Allow the search field to contain just the article name.
    # If there is exactly one active variant for that article, use it directly.
    if search_norm and not article_norm:
        same_group = [o for o in options if normalize_text(o['group_name']) == search_norm]
        if len(same_group) == 1 and not variant_norm:
            return same_group[0]
        if variant_norm:
            found = exact_match(
                lambda o: normalize_text(o['group_name']) == search_norm and normalize_text(o['variant_label']) == variant_norm
            )
            if found:
                return found
            same_group_variant = [o for o in options if normalize_text(o['group_name']) == search_norm]
            if same_group_variant:
                best = max(
                    same_group_variant,
                    key=lambda o: difflib.SequenceMatcher(None, normalize_text(o['variant_label']), variant_norm).ratio(),
                )
                ratio = difflib.SequenceMatcher(None, normalize_text(best['variant_label']), variant_norm).ratio()
                if ratio >= 0.84:
                    return best

    if article_norm and variant_norm:
        found = exact_match(lambda o: normalize_text(o['group_name']) == article_norm and normalize_text(o['variant_label']) == variant_norm)
        if found:
            return found
        same_group = [o for o in options if normalize_text(o['group_name']) == article_norm]
        if same_group:
            best = max(same_group, key=lambda o: difflib.SequenceMatcher(None, normalize_text(o['variant_label']), variant_norm).ratio())
            ratio = difflib.SequenceMatcher(None, normalize_text(best['variant_label']), variant_norm).ratio()
            if ratio >= 0.84:
                return best

    combined_norm = normalize_text(f'{article_name} {variant_label}'.strip())
    if combined_norm:
        ranked = sorted(
            ((difflib.SequenceMatcher(None, normalize_text(o['display_name']), combined_norm).ratio(), o) for o in options),
            key=lambda item: item[0],
            reverse=True,
        )
        if ranked and ranked[0][0] >= 0.92:
            return ranked[0][1]

    if search_norm:
        ranked = sorted(
            ((difflib.SequenceMatcher(None, normalize_text(o['display_name']), search_norm).ratio(), o) for o in options),
            key=lambda item: item[0],
            reverse=True,
        )
        if ranked and ranked[0][0] >= 0.94:
            return ranked[0][1]

        # If only the article name was typed and there is a single clear fuzzy group match, use it.
        group_ranked = sorted(
            ((difflib.SequenceMatcher(None, normalize_text(o['group_name']), search_norm).ratio(), o) for o in options),
            key=lambda item: item[0],
            reverse=True,
        )
        if group_ranked and group_ranked[0][0] >= 0.96:
            top_score = group_ranked[0][0]
            top_matches = [o for score, o in group_ranked if abs(score - top_score) < 1e-9]
            if len(top_matches) == 1 and not variant_norm:
                same_group = [o for o in options if normalize_text(o['group_name']) == normalize_text(top_matches[0]['group_name'])]
                if len(same_group) == 1:
                    return same_group[0]

    return None
def split_detected_article_variant(description: str):
    desc = re.sub(r'\s+', ' ', (description or '').strip())
    if not desc:
        return '', ''
    pattern = re.compile(r'(\d+[\.,]?\d*\s?(?:kg|g|gr|gramm|l|ml|cl|stk|st|er|x\d+|x\s*\d+|cm|mm))$', re.IGNORECASE)
    match = pattern.search(desc)
    if match:
        variant = match.group(1).strip()
        article = desc[:match.start()].strip(' -–:')
        return article or desc, variant
    parts = re.split(r'\s{2,}|\s[-–]\s', desc)
    if len(parts) >= 2:
        article = parts[0].strip()
        variant = parts[-1].strip()
        if article and variant and len(variant) <= 24:
            return article, variant
    return desc, ''
def extract_date_from_text(text: str):
    patterns = [
        r'\b(\d{2}\.\d{2}\.\d{4})\b',
        r'\b(\d{2}/\d{2}/\d{4})\b',
        r'\b(\d{4}-\d{2}-\d{2})\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        raw = match.group(1)
        for fmt in ('%d.%m.%Y', '%d/%m/%Y', '%Y-%m-%d'):
            try:
                return datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
            except ValueError:
                pass
    return ''

def extract_supplier_from_text(text: str):
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r'^(?:h[äa]ndler|lieferant)\s*:\s*(.+)$', line, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ''

def find_supplier_by_name(name: str):
    supplier_text = (name or '').strip()
    if not supplier_text:
        return None
    return query_one('SELECT id, name FROM suppliers WHERE lower(name)=lower(?)', (supplier_text,))

def find_group_by_name(name: str):
    raw = (name or '').strip()
    if not raw:
        return None
    candidates = [raw]
    for sep in (' – ', ' - ', '|'):
        if sep in raw:
            left = raw.split(sep, 1)[0].strip()
            if left:
                candidates.append(left)
    seen = set()
    for cand in candidates:
        norm = normalize_text(cand)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        row = query_one('SELECT id, name FROM article_groups WHERE lower(name)=lower(?)', (cand,))
        if row:
            return row
        row = query_one('SELECT id, name FROM article_groups WHERE lower(name)=lower(?)', (norm,))
        if row:
            return row
        row = find_group_by_alias(cand)
        if row:
            return row
    groups = query_all('SELECT id, name FROM article_groups ORDER BY name COLLATE NOCASE')
    raw_norm = normalize_text(raw)
    ranked = sorted(
        ((difflib.SequenceMatcher(None, normalize_text(g['name']), raw_norm).ratio(), g) for g in groups),
        key=lambda item: item[0],
        reverse=True,
    )
    if ranked and ranked[0][0] >= 0.94:
        top_score = ranked[0][0]
        top = [g for score, g in ranked if abs(score - top_score) < 1e-9]
        if len(top) == 1:
            return top[0]
    return None

def supplier_status_payload(name: str):
    supplier_text = (name or '').strip()
    if not supplier_text:
        return {'name': '', 'known': False, 'text': '', 'css': ''}
    existing = find_supplier_by_name(supplier_text)
    if existing:
        return {'name': existing['name'], 'known': True, 'text': 'Bekannter Händler gefunden', 'css': 'ok'}
    return {'name': supplier_text, 'known': False, 'text': 'Neuer Händler wird angelegt', 'css': 'warn'}

def article_storage_payload(article_name: str, variant_search: str = '', variant_label: str = ''):
    raw_name = (article_name or '').strip()
    raw_search = (variant_search or '').strip()
    raw_variant = (variant_label or '').strip()
    group = find_group_by_name(raw_name or raw_search)
    if not group:
        return {'known': False, 'text': '', 'labels': []}
    variant_rows = query_all(
        '''
        SELECT DISTINCT TRIM(COALESCE(NULLIF(v.stock_unit, ''), NULLIF(v.variant_label, ''), '')) AS label
        FROM article_variants v
        WHERE v.group_id = ? AND v.is_active = 1
        ORDER BY label COLLATE NOCASE
        ''',
        (group['id'],),
    )
    labels = [row['label'] for row in variant_rows if (row['label'] or '').strip()]
    if not labels:
        return {'known': True, 'text': 'Bisher gespeichert als: –', 'labels': []}
    norm_variant = normalize_text(raw_variant)
    if norm_variant:
        for label in labels:
            if normalize_text(label) == norm_variant:
                return {'known': True, 'text': f'Bisher gespeichert als: {label}', 'labels': labels}
    if len(labels) == 1:
        return {'known': True, 'text': f'Bisher gespeichert als: {labels[0]}', 'labels': labels}
    shown = ', '.join(labels[:3])
    if len(labels) > 3:
        shown += ' …'
    return {'known': True, 'text': f'Bisher gespeichert als: {shown}', 'labels': labels}


def compact_normalize(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', normalize_text(value or ''))

def suggest_existing_variant_label(group_id, raw_variant='', raw_purchase_unit=''):
    rows = query_all(
        '''
        SELECT DISTINCT TRIM(COALESCE(NULLIF(v.stock_unit, ''), NULLIF(v.variant_label, ''), '')) AS label
        FROM article_variants v
        WHERE v.group_id = ? AND v.is_active = 1
        ORDER BY label COLLATE NOCASE
        ''',
        (group_id,),
    )
    labels = [row['label'] for row in rows if (row['label'] or '').strip()]
    if not labels:
        return ''
    variant_compact = compact_normalize(raw_variant)
    purchase_compact = compact_normalize(raw_purchase_unit)
    candidates = []
    for label in labels:
        label_compact = compact_normalize(label)
        score = 0
        if variant_compact:
            if label_compact == variant_compact:
                score = max(score, 100)
            elif variant_compact in label_compact:
                score = max(score, 95)
            else:
                ratio = difflib.SequenceMatcher(None, label_compact, variant_compact).ratio()
                if ratio >= 0.82:
                    score = max(score, int(ratio * 100))
        if purchase_compact:
            if label_compact == purchase_compact:
                score = max(score, 98)
            elif purchase_compact in label_compact:
                score = max(score, 96)
        if score:
            candidates.append((score, label))
    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1].lower()))
        top_score = candidates[0][0]
        top_labels = [label for score, label in candidates if score == top_score]
        if len(top_labels) == 1:
            return top_labels[0]
    if len(labels) == 1:
        return labels[0]
    return ''

def parse_purchase_unit_label(label: str):
    raw = re.sub(r'\s+', ' ', (label or '').strip())
    if not raw:
        return '', '', '1'
    match = re.match(r'^(\d+(?:[\.,]\d+)?)\s+(.+)$', raw)
    if not match:
        return raw, raw, '1'
    qty_part = match.group(1).replace(',', '.')
    unit_part = match.group(2).strip()
    countable_units = {
        'stück', 'stueck', 'stk', 'st', 'becher', 'bechern', 'tasse', 'tassen',
        'flasche', 'flaschen', 'dose', 'dosen', 'tafel', 'tafeln', 'glas', 'glaeser', 'gläser',
        'rolle', 'rollen', 'beutel', 'beuteln', 'tüte', 'tuete', 'tüten', 'tueten',
        'packung', 'packungen', 'pack', 'packs', 'karton', 'kartons', 'sack', 'säcke', 'saecke',
        'eimer', 'kanister'
    }
    unit_norm = normalize_text(unit_part)
    if unit_norm in countable_units:
        return raw, unit_part, qty_part
    return raw, raw, '1'



def canonical_variant_display_label(variant_label: str, stock_unit: str = '') -> str:
    label = (variant_label or '').strip()
    if label:
        return label
    return (stock_unit or '').strip()


def preferred_invoice_display_label(saved_variant_label: str = '', purchase_unit_label: str = '', fallback_label: str = '') -> str:
    label = (saved_variant_label or '').strip()
    if label:
        return label
    label = (purchase_unit_label or '').strip()
    if label:
        return label
    return (fallback_label or '').strip()


def format_saved_invoice_display(purchase_quantity, saved_variant_label: str = '', purchase_unit_label: str = '', fallback_label: str = ''):
    label = preferred_invoice_display_label(saved_variant_label, purchase_unit_label, fallback_label)
    if purchase_quantity in (None, ''):
        return '–'
    try:
        quantity_value = float(purchase_quantity)
    except (TypeError, ValueError):
        return f"{purchase_quantity} {label}".strip() if label else str(purchase_quantity)
    if quantity_value <= 0:
        return '–'
    if label:
        return f"{qty(quantity_value)} {label}".strip()
    return qty(quantity_value)

app.jinja_env.globals['format_saved_invoice_display'] = format_saved_invoice_display

def infer_invoice_line_import_mode(saved_variant_label: str = '', purchase_unit_label: str = '', line_units_per_purchase=None, quantity=None, purchase_quantity=None, import_mode: str = '', variant_units_per_purchase=None, variant_purchase_unit: str = '', variant_stock_unit: str = '') -> str:
    raw_mode = (import_mode or '').strip().lower()
    # "stock" ist eindeutig und darf direkt übernommen werden.
    # "pack" wird dagegen nicht blind vertraut, weil ältere/falsch gespeicherte
    # Rechnungszeilen trotz Umrechnung manchmal noch als "pack" markiert sind.
    # In diesen Fällen muss aus den tatsächlichen Zeilenwerten (quantity,
    # purchase_quantity, units_per_purchase, purchase_unit_label) erneut
    # abgeleitet werden, damit z. B. 3 x 10 Stück korrekt als 30 Stück
    # angezeigt werden.
    if raw_mode == 'stock':
        return 'stock'
    line_units_value = parse_number(line_units_per_purchase) or 1
    variant_units_value = parse_number(variant_units_per_purchase) or 1
    units_value = line_units_value if line_units_value > 1 else variant_units_value if variant_units_value > 1 else max(line_units_value, variant_units_value, 1)
    normalized_qty = parse_number(quantity)
    purchase_qty = parse_number(purchase_quantity)
    parsed_purchase_label, parsed_stock_unit, parsed_units = parse_purchase_unit_label(purchase_unit_label or '')
    saved_norm = normalize_text(saved_variant_label or '')
    parsed_stock_norm = normalize_text(parsed_stock_unit or '')
    parsed_purchase_norm = normalize_text(parsed_purchase_label or '')
    variant_stock_norm = normalize_text(variant_stock_unit or '')
    variant_purchase_norm = normalize_text(variant_purchase_unit or '')
    if units_value <= 1:
        return 'pack'
    if saved_norm and parsed_stock_norm and saved_norm == parsed_stock_norm:
        return 'stock'
    if saved_norm and parsed_purchase_norm and saved_norm == parsed_purchase_norm and units_value > 1:
        return 'stock'
    if normalized_qty not in (None, 0) and purchase_qty not in (None, 0) and abs(normalized_qty - purchase_qty) > 1e-9:
        return 'stock'
    parsed_units_value = parse_number(parsed_units) or 1
    if parsed_units_value > 1 and saved_norm and parsed_stock_norm and saved_norm == parsed_stock_norm:
        return 'stock'
    if line_units_value <= 1 and variant_units_value > 1:
        if saved_norm and variant_stock_norm and saved_norm == variant_stock_norm:
            return 'stock'
        if saved_norm and variant_purchase_norm and saved_norm == variant_purchase_norm:
            return 'stock'
        if parsed_purchase_norm and variant_stock_norm and parsed_purchase_norm == variant_stock_norm:
            return 'stock'
        if parsed_purchase_norm and variant_purchase_norm and parsed_purchase_norm == variant_purchase_norm:
            return 'stock'
    return 'pack'


def invoice_line_display_values(quantity=None, purchase_quantity=None, net_price=None, purchase_price=None, saved_variant_label: str = '', purchase_unit_label: str = '', fallback_label: str = '', line_units_per_purchase=None, import_mode: str = '', variant_units_per_purchase=None, variant_purchase_unit: str = '', variant_stock_unit: str = '', source_type: str = ''):
    mode = infer_invoice_line_import_mode(saved_variant_label, purchase_unit_label, line_units_per_purchase, quantity, purchase_quantity, import_mode, variant_units_per_purchase, variant_purchase_unit, variant_stock_unit)
    source_type_norm = (source_type or '').strip().lower()

    # Für Inventur-Startwerte soll immer die aktuell gepflegte Variantenbezeichnung
    # angezeigt werden. Alte, historisch falsche Labels wie "Stück" dürfen bei einer
    # später auf "Karton" umbenannten Variante hier nicht mehr auftauchen.
    if source_type_norm == 'inventur-startwert':
        display_label = canonical_variant_display_label(fallback_label, variant_stock_unit or variant_purchase_unit or fallback_label)
    else:
        display_label = canonical_variant_display_label(saved_variant_label, fallback_label) or preferred_invoice_display_label(saved_variant_label, purchase_unit_label, fallback_label)

    line_units_value = parse_number(line_units_per_purchase) or 1
    variant_units_value = parse_number(variant_units_per_purchase) or 1
    units_value = line_units_value if line_units_value > 1 else variant_units_value if variant_units_value > 1 else max(line_units_value, variant_units_value, 1)
    if units_value <= 0:
        units_value = 1
    normalized_qty = parse_number(quantity)
    purchase_qty = parse_number(purchase_quantity)
    purchase_price_value = parse_number(purchase_price)
    net_price_value = parse_number(net_price)

    # Inventur-Startwerte liegen bereits in der echten Bestandsmenge vor und
    # dürfen deshalb nicht noch einmal mit units_per_purchase hochgerechnet werden.
    if source_type_norm == 'inventur-startwert':
        display_quantity = normalized_qty if normalized_qty is not None else (purchase_qty if purchase_qty is not None else quantity)
        display_price = net_price_value if net_price_value is not None else purchase_price_value
    elif mode == 'stock':
        if purchase_qty is not None and units_value > 1 and (normalized_qty is None or abs(normalized_qty - purchase_qty) < 1e-9):
            display_quantity = purchase_qty * units_value
        else:
            display_quantity = normalized_qty if normalized_qty is not None else (purchase_qty * units_value if purchase_qty is not None else purchase_quantity)
        if purchase_price_value is not None and units_value > 1 and (net_price_value is None or abs(net_price_value - purchase_price_value) < 1e-9):
            display_price = purchase_price_value / units_value
        else:
            display_price = net_price_value if net_price_value is not None else (purchase_price_value / units_value if purchase_price_value is not None and units_value > 0 else purchase_price_value)
    else:
        display_quantity = purchase_qty if purchase_qty is not None else quantity
        display_price = purchase_price_value if purchase_price_value is not None else net_price_value
    display_text = format_saved_invoice_display(display_quantity, display_label, '', fallback_label)
    return {
        'import_mode': mode,
        'display_label': display_label,
        'display_quantity': display_quantity,
        'display_price': display_price,
        'display_text': display_text,
    }

def synthesize_purchase_unit_label(purchase_unit_label: str, units_per_purchase, stock_unit_label: str = '', import_mode: str = 'pack'):
    purchase_label = (purchase_unit_label or '').strip()
    stock_label = (stock_unit_label or '').strip()
    units = parse_number(units_per_purchase) or 1
    if units <= 0:
        units = 1
    if units > 1 and import_mode == 'stock':
        base = purchase_label or stock_label
        if base and not re.match(r'^\s*\d', base):
            return f"{qty(units)} {base}".strip()
    return purchase_label or stock_label

def parse_invoice_text_block(text: str):
    parsed_date = ''
    parsed_supplier = extract_supplier_from_text(text)
    rows = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith('datum:'):
            parsed_date = extract_date_from_text(line)
            continue
        if lower.startswith('lieferant:') or lower.startswith('händler:') or lower.startswith('haendler:'):
            continue
        parts = [part.strip() for part in re.split(r'\s*[|;\t]\s*', line) if part.strip()]
        if len(parts) < 4:
            continue
        article_name = parts[0]
        raw_purchase_unit_label = parts[1]
        purchase_unit_label, stock_unit_label, units_per_purchase = parse_purchase_unit_label(raw_purchase_unit_label)
        quantity_text = parts[2]
        price_text = parts[3]
        resolved = resolve_existing_variant('', article_name, stock_unit_label)
        group_match = find_group_by_name(article_name)
        matched_existing = bool(resolved)
        match_status_text = 'Neuer Artikel wird angelegt'
        match_status_class = 'warn'
        display_name = ''
        final_article_name = article_name
        final_variant_label = 'Stück'
        if resolved:
            display_name = resolved['display_name']
            final_article_name = resolved['group_name']
            final_variant_label = resolved['variant_label']
            match_status_text = 'Bekannter Artikel gefunden'
            match_status_class = 'ok'
        elif group_match:
            final_article_name = group_match['name']
            suggested_label = suggest_existing_variant_label(group_match['id'], stock_unit_label, raw_purchase_unit_label)
            existing_labels = article_storage_payload(final_article_name).get('labels', [])
            if suggested_label:
                final_variant_label = suggested_label
                display_name = f"{final_article_name} – {final_variant_label}"
                match_status_text = 'Bekannter Artikel gefunden · bestehende Variante übernommen'
            elif len(existing_labels) == 1:
                final_variant_label = existing_labels[0]
                display_name = f"{final_article_name} – {final_variant_label}"
                match_status_text = 'Bekannter Artikel gefunden · bestehende Variante übernommen'
            else:
                match_status_text = 'Bekannter Artikel gefunden · neue Variante wird angelegt'
            match_status_class = 'ok'
        rows.append({
            'variant_search': display_name,
            'article_name': final_article_name,
            'variant_label': final_variant_label,
            'purchase_unit_label': purchase_unit_label,
            'units_per_purchase': units_per_purchase,
            'quantity': quantity_text,
            'net_price': price_text,
            'matched_existing': matched_existing,
            'match_status_text': match_status_text,
            'match_status_class': match_status_class,
            'import_mode': 'stock' if (not group_match and not matched_existing) or matched_existing or str(units_per_purchase) not in {'', '1', '1.0'} else 'pack',
            'raw_detected_unit': raw_purchase_unit_label,
            'original_article_name': article_name,
        })
    return parsed_date, parsed_supplier, rows

def default_invoice_row():
    return {
        'variant_search': '',
        'article_name': '',
        'variant_label': 'Stück',
        'purchase_unit_label': '',
        'units_per_purchase': '1',
        'quantity': '',
        'net_price': '',
        'matched_existing': False,
        'match_status_text': '',
        'match_status_class': '',
        'import_mode': 'stock',
        'raw_detected_unit': '',
        'storage_status_text': '',
        'storage_status_class': '',
        'original_article_name': '',
    }


def invoice_view_flags(view='list', parsed=False, edit=False):
    if edit:
        return {
            'show_text_import': False,
            'text_import_open': False,
            'show_invoice_form': True,
            'invoice_form_open': True,
            'show_invoice_list': False,
            'invoice_list_open': False,
        }
    if parsed:
        return {
            'show_text_import': False,
            'text_import_open': False,
            'show_invoice_form': True,
            'invoice_form_open': True,
            'show_invoice_list': False,
            'invoice_list_open': False,
        }
    view = (view or 'list').strip().lower()
    if view == 'text':
        return {
            'show_text_import': True,
            'text_import_open': True,
            'show_invoice_form': True,
            'invoice_form_open': False,
            'show_invoice_list': False,
            'invoice_list_open': False,
        }
    if view == 'manual':
        return {
            'show_text_import': False,
            'text_import_open': False,
            'show_invoice_form': True,
            'invoice_form_open': True,
            'show_invoice_list': False,
            'invoice_list_open': False,
        }
    return {
        'show_text_import': False,
        'text_import_open': False,
        'show_invoice_form': False,
        'invoice_form_open': False,
        'show_invoice_list': True,
        'invoice_list_open': True,
    }
def invoice_year_options(supplier_id=None):
    sql = '''
        SELECT DISTINCT substr(invoice_date, 1, 4) AS year
        FROM invoices
        WHERE invoice_date IS NOT NULL AND trim(invoice_date) != ''
    '''
    params = []
    if supplier_id is not None:
        sql += ' AND supplier_id = ?'
        params.append(int(supplier_id))
    sql += ' ORDER BY year DESC'
    return [row['year'] for row in query_all(sql, tuple(params)) if row['year']]


def invoice_page_context(invoice_year='', **extra):
    selected_year = (invoice_year or '').strip()
    sql = '''
        SELECT i.id, i.invoice_date, COALESCE(s.name, i.supplier) AS supplier_name, COUNT(il.id) AS line_count
        FROM invoices i
        LEFT JOIN invoice_lines il ON il.invoice_id = i.id
        LEFT JOIN suppliers s ON s.id = i.supplier_id
    '''
    params = []
    if selected_year.isdigit():
        sql += ' WHERE substr(i.invoice_date, 1, 4) = ?'
        params.append(selected_year)
    sql += '''
        GROUP BY i.id
        ORDER BY i.invoice_date DESC, i.id DESC
    '''
    recent_invoices = query_all(sql, tuple(params))
    base = {
        'grouped_variants': grouped_variants(),
        'supplier_options': supplier_options(),
        'variant_search_list': variant_search_options(),
        'variant_search_json': json.dumps(variant_search_entries(), ensure_ascii=False),
        'article_search_json': json.dumps(article_search_entries(), ensure_ascii=False),
        'variant_label_options': variant_label_options(),
        'today': date.today().isoformat(),
        'recent_invoices': recent_invoices,
        'invoice_years': invoice_year_options(),
        'selected_invoice_year': selected_year,
        'draft_rows': [default_invoice_row(), default_invoice_row()],
        'supplier_search': '',
        'supplier_status': supplier_status_payload(''),
        'raw_invoice_text': '',
    }
    base.update(extra)
    return base


def enrich_draft_rows(rows):
    enriched = []
    for source in (rows or []):
        row = dict(default_invoice_row())
        row.update(source or {})
        matched_existing = bool(row.get('matched_existing'))
        if not row.get('match_status_text'):
            if matched_existing:
                row['match_status_text'] = 'Bekannter Artikel gefunden'
                row['match_status_class'] = 'ok'
            elif row.get('article_name'):
                row['match_status_text'] = 'Neuer Artikel wird angelegt'
                row['match_status_class'] = 'warn'
        raw_detected_unit = (row.get('raw_detected_unit') or '').strip()
        storage_payload = article_storage_payload(row.get('article_name', ''), row.get('variant_search', ''), row.get('variant_label', ''))
        variant_label_norm = normalize_text(row.get('variant_label') or '')
        if row.get('article_name') and storage_payload['known'] and not matched_existing:
            suggested_label = ''
            group_row = find_group_by_name(row.get('article_name', '') or row.get('variant_search', ''))
            if group_row:
                suggested_label = suggest_existing_variant_label(
                    group_row['id'],
                    row.get('variant_label', ''),
                    row.get('purchase_unit_label') or raw_detected_unit,
                )
            if suggested_label and variant_label_norm in {'', 'stueck', 'stück'}:
                row['variant_label'] = suggested_label
            elif len(storage_payload.get('labels', [])) == 1 and variant_label_norm in {'', 'stueck', 'stück'}:
                row['variant_label'] = storage_payload['labels'][0]
        if row.get('article_name') and not storage_payload['known'] and (not row.get('variant_label') or normalize_text(row.get('variant_label')) == normalize_text(raw_detected_unit)):
            row['variant_label'] = 'Stück'
        row['storage_status_text'] = storage_payload['text']
        row['storage_status_class'] = 'ok' if storage_payload['known'] else ''
        units = parse_number(row.get('units_per_purchase')) or 1.0
        if units <= 0:
            units = 1.0
        qty_val = parse_number(row.get('quantity')) or 0.0
        price_val = parse_number(row.get('net_price'))
        row['preview_purchase_unit'] = synthesize_purchase_unit_label(
            row.get('purchase_unit_label') or row.get('raw_detected_unit') or '',
            row.get('units_per_purchase') or '1',
            row.get('variant_label') or '',
            row.get('import_mode') or ('stock' if units > 1 else 'pack'),
        )
        row['preview_price_per_purchase'] = money(price_val) if price_val is not None else '–'
        row['preview_price_per_unit'] = money(price_val / units) if price_val is not None and units > 0 else '–'
        row['preview_total_units'] = qty(qty_val * units) if qty_val and units else qty_val if qty_val else '–'
        row['import_mode'] = row.get('import_mode') or ('stock' if units > 1 else 'pack')
        if row.get('article_name') and not storage_payload['known'] and row['import_mode'] == 'pack':
            row['import_mode'] = 'stock'
        stored_unit = row.get('variant_label') or row.get('preview_purchase_unit') or ''
        if row['import_mode'] == 'stock':
            row['capture_summary'] = f"Erfasst: {qty(qty_val * units)} {stored_unit} à {money(price_val / units) if price_val is not None else '–'}" if qty_val and stored_unit else ''
        else:
            row['capture_summary'] = f"Erfasst: {qty(qty_val)} {row['preview_purchase_unit']} à {money(price_val) if price_val is not None else '–'}" if qty_val and row['preview_purchase_unit'] else ''
        enriched.append(row)
    return enriched

def invoice_rows_for_invoice(invoice_id):
    rows = query_all(
        """
        SELECT il.id, il.quantity, il.net_price, il.purchase_quantity, il.purchase_price, il.purchase_unit_label,
               COALESCE(NULLIF(il.saved_variant_label, ''), v.variant_label) AS saved_variant_label,
               COALESCE(il.line_units_per_purchase, 1) AS line_units_per_purchase,
               COALESCE(il.import_mode, '') AS import_mode,
               g.name AS group_name, v.variant_label,
               COALESCE(NULLIF(v.stock_unit, ''), v.variant_label) AS stock_unit,
               COALESCE(NULLIF(v.purchase_unit, ''), v.variant_label) AS variant_purchase_unit,
               COALESCE(v.units_per_purchase, 1) AS variant_units_per_purchase,
               g.name || ' – ' || v.variant_label AS display_name
        FROM invoice_lines il
        JOIN article_variants v ON v.id = il.variant_id
        JOIN article_groups g ON g.id = v.group_id
        WHERE il.invoice_id = ?
        ORDER BY il.id
        """,
        (invoice_id,),
    )
    prepared = []
    for row in rows:
        row = dict(row)
        purchase_qty = parse_number(row['purchase_quantity'])
        normalized_qty = parse_number(row['quantity'])
        units_value = parse_number(row['line_units_per_purchase']) or 1
        if (not units_value or abs(units_value - 1.0) < 1e-9) and purchase_qty and normalized_qty and purchase_qty > 0:
            inferred = normalized_qty / purchase_qty
            if inferred > 0:
                units_value = inferred
        if units_value <= 0:
            units_value = 1
        display_variant = canonical_variant_display_label(row['saved_variant_label'], row['stock_unit'])
        purchase_unit_display = display_variant or row['purchase_unit_label'] or row['variant_purchase_unit'] or row['stock_unit'] or row['variant_label']
        resolved = resolve_existing_variant('', row['group_name'], display_variant)
        matched_existing = bool(resolved)
        import_mode = infer_invoice_line_import_mode(
            row.get('saved_variant_label', ''),
            row.get('purchase_unit_label', ''),
            units_value,
            normalized_qty,
            purchase_qty,
            row.get('import_mode', ''),
            row.get('variant_units_per_purchase'),
            row.get('variant_purchase_unit', ''),
            row.get('stock_unit', ''),
        )
        prepared.append({
            'line_id': row['id'],
            'variant_search': resolved['display_name'] if resolved else f"{row['group_name']} – {display_variant}",
            'article_name': resolved['group_name'] if resolved else row['group_name'],
            'variant_label': display_variant,
            'purchase_unit_label': purchase_unit_display,
            'units_per_purchase': qty(units_value),
            'quantity': qty(purchase_qty) if purchase_qty is not None else '',
            'net_price': str(row['purchase_price']).replace('.', ',') if row['purchase_price'] is not None else '',
            'matched_existing': matched_existing,
            'match_status_text': 'Bekannter Artikel gefunden',
            'match_status_class': 'ok',
            'import_mode': import_mode,
            'original_article_name': row['group_name'],
        })
    return enrich_draft_rows(prepared) or [default_invoice_row()]

def invoice_form_common_data(invoice_date, supplier_name, draft_rows):
    supplier_payload = supplier_status_payload(supplier_name or '')
    return {
        'today': invoice_date or date.today().isoformat(),
        'supplier_search': supplier_payload['name'],
        'supplier_status': supplier_payload,
        'draft_rows': enrich_draft_rows(draft_rows or [default_invoice_row()]),
        'supplier_options': supplier_options(),
        'variant_search_list': variant_search_options(),
        'article_search_json': json.dumps(article_search_entries(), ensure_ascii=False),
        'variant_label_options': variant_label_options(),
    }
def now_iso():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
def table_columns(conn, table_name):
    return {row[1] for row in conn.execute(f'PRAGMA table_info({table_name})').fetchall()}
def ensure_column(conn, table_name, column_name, definition):
    columns = table_columns(conn, table_name)
    if column_name not in columns:
        conn.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}')
def sync_shopping_categories(conn, event_id=None):
    """Ensure every category used by shopping items has a stable per-event sort row."""
    if event_id is None:
        event_ids = [row[0] for row in conn.execute('SELECT id FROM shopping_events ORDER BY sort_order, id').fetchall()]
    else:
        event_ids = [event_id]
    ts = now_iso()
    for current_event_id in event_ids:
        existing = conn.execute(
            'SELECT name, sort_order FROM shopping_categories WHERE event_id = ? ORDER BY sort_order, id',
            (current_event_id,),
        ).fetchall()
        known = {str(row[0]) for row in existing}
        next_order = max((int(row[1] or 0) for row in existing), default=-1) + 1
        used = conn.execute(
            """SELECT COALESCE(NULLIF(trim(category), ''), 'Weitere Artikel') AS category_name, MIN(sort_order) AS first_order
               FROM shopping_items WHERE event_id = ?
               GROUP BY COALESCE(NULLIF(trim(category), ''), 'Weitere Artikel')
               ORDER BY first_order, category_name COLLATE NOCASE""",
            (current_event_id,),
        ).fetchall()
        for category_name, _ in used:
            category_name = str(category_name or 'Weitere Artikel').strip() or 'Weitere Artikel'
            if category_name in known:
                continue
            conn.execute(
                'INSERT OR IGNORE INTO shopping_categories (event_id, name, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
                (current_event_id, category_name, next_order, ts, ts),
            )
            known.add(category_name)
            next_order += 1
    conn.commit()


def seed_default_shopping_lists(conn):
    seeded = conn.execute("SELECT meta_value FROM app_meta WHERE meta_key = 'shopping_seed_v1'").fetchone()
    if seeded:
        return
    ts = now_iso()
    for event_order, (slug, name, items) in enumerate(SHOPPING_DEFAULTS, start=1):
        row = conn.execute('SELECT id FROM shopping_events WHERE slug = ?', (slug,)).fetchone()
        if row:
            event_id = row[0]
        else:
            cur = conn.execute(
                'INSERT INTO shopping_events (slug, name, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
                (slug, name, event_order, ts, ts),
            )
            event_id = cur.lastrowid
        existing_count = conn.execute('SELECT COUNT(*) FROM shopping_items WHERE event_id = ?', (event_id,)).fetchone()[0]
        if existing_count == 0:
            for item_order, (category, item_name, source) in enumerate(items, start=1):
                conn.execute(
                    "INSERT INTO shopping_items (event_id, name, category, quantity_text, source, checked, sort_order, created_at, updated_at) VALUES (?, ?, ?, '', ?, 0, ?, ?, ?)",
                    (event_id, item_name, category, source, item_order, ts, ts),
                )
    conn.execute(
        "INSERT OR REPLACE INTO app_meta (meta_key, meta_value, updated_at) VALUES ('shopping_seed_v1', '1', ?)",
        (ts,),
    )
    conn.commit()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA foreign_keys = OFF')
    conn.executescript(
        '''
        CREATE TABLE IF NOT EXISTS article_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            category TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS article_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            variant_label TEXT NOT NULL,
            unit TEXT,
            purchase_unit TEXT,
            stock_unit TEXT,
            units_per_purchase REAL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(group_id, variant_label),
            FOREIGN KEY(group_id) REFERENCES article_groups(id)
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS article_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias_name TEXT NOT NULL,
            normalized_alias TEXT NOT NULL UNIQUE,
            group_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(group_id) REFERENCES article_groups(id)
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_date TEXT NOT NULL,
            invoice_number TEXT,
            supplier TEXT,
            supplier_id INTEGER,
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
        );
        CREATE TABLE IF NOT EXISTS invoice_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            variant_id INTEGER NOT NULL,
            quantity REAL,
            net_price REAL NOT NULL,
            purchase_quantity REAL,
            purchase_price REAL,
            purchase_unit_label TEXT,
            notes TEXT,
            FOREIGN KEY(invoice_id) REFERENCES invoices(id),
            FOREIGN KEY(variant_id) REFERENCES article_variants(id)
        );
        CREATE TABLE IF NOT EXISTS inventory_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            variant_id INTEGER NOT NULL,
            opening_stock REAL,
            closing_stock REAL,
            inventory_price REAL,
            updated_at TEXT NOT NULL,
            UNIQUE(year, variant_id),
            FOREIGN KEY(variant_id) REFERENCES article_variants(id)
        );
        CREATE TABLE IF NOT EXISTS article_suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(group_id, supplier_id),
            FOREIGN KEY(group_id) REFERENCES article_groups(id),
            FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
        );
        CREATE TABLE IF NOT EXISTS shopping_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shopping_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(event_id, name),
            FOREIGN KEY(event_id) REFERENCES shopping_events(id)
        );
        CREATE TABLE IF NOT EXISTS shopping_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            category TEXT,
            quantity_text TEXT,
            source TEXT,
            checked INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(event_id) REFERENCES shopping_events(id)
        );
        CREATE TABLE IF NOT EXISTS app_meta (
            meta_key TEXT PRIMARY KEY,
            meta_value TEXT,
            updated_at TEXT NOT NULL
        );
        '''
    )
    ensure_column(conn, 'invoices', 'supplier_id', 'INTEGER')
    ensure_column(conn, 'article_variants', 'unit', 'TEXT')
    ensure_column(conn, 'article_variants', 'purchase_unit', 'TEXT')
    ensure_column(conn, 'article_variants', 'stock_unit', 'TEXT')
    ensure_column(conn, 'article_variants', 'units_per_purchase', 'REAL DEFAULT 1')
    ensure_column(conn, 'article_groups', 'category', 'TEXT')
    ensure_column(conn, 'shopping_items', 'favorite', 'INTEGER NOT NULL DEFAULT 0')
    ensure_column(conn, 'shopping_items', 'use_count', 'INTEGER NOT NULL DEFAULT 0')
    ensure_column(conn, 'shopping_items', 'last_checked_at', 'TEXT')
    ensure_column(conn, 'invoice_lines', 'notes', 'TEXT')
    ensure_column(conn, 'invoice_lines', 'purchase_quantity', 'REAL')
    ensure_column(conn, 'invoice_lines', 'purchase_price', 'REAL')
    ensure_column(conn, 'invoice_lines', 'purchase_unit_label', 'TEXT')
    ensure_column(conn, 'invoice_lines', 'saved_variant_label', 'TEXT')
    ensure_column(conn, 'invoice_lines', 'line_units_per_purchase', 'REAL')
    ensure_column(conn, 'invoice_lines', 'import_mode', 'TEXT')
    conn.execute("UPDATE article_variants SET purchase_unit = COALESCE(NULLIF(trim(purchase_unit), ''), variant_label) WHERE purchase_unit IS NULL OR trim(purchase_unit) = ''")
    conn.execute("UPDATE article_variants SET stock_unit = COALESCE(NULLIF(trim(stock_unit), ''), variant_label) WHERE stock_unit IS NULL OR trim(stock_unit) = ''")
    conn.execute("UPDATE article_variants SET units_per_purchase = 1 WHERE units_per_purchase IS NULL OR units_per_purchase <= 0")
    conn.execute("UPDATE invoice_lines SET purchase_quantity = quantity WHERE purchase_quantity IS NULL")
    conn.execute("UPDATE invoice_lines SET purchase_price = net_price WHERE purchase_price IS NULL")
    conn.execute("UPDATE invoice_lines SET purchase_unit_label = (SELECT variant_label FROM article_variants v WHERE v.id = invoice_lines.variant_id) WHERE purchase_unit_label IS NULL OR trim(purchase_unit_label) = ''")
    conn.execute("UPDATE invoice_lines SET saved_variant_label = (SELECT variant_label FROM article_variants v WHERE v.id = invoice_lines.variant_id) WHERE saved_variant_label IS NULL OR trim(saved_variant_label) = ''")
    conn.execute("UPDATE invoice_lines SET line_units_per_purchase = CASE WHEN COALESCE(purchase_quantity, 0) != 0 AND quantity IS NOT NULL THEN ABS(quantity / purchase_quantity) ELSE COALESCE((SELECT units_per_purchase FROM article_variants v WHERE v.id = invoice_lines.variant_id), 1) END WHERE line_units_per_purchase IS NULL OR line_units_per_purchase <= 0")
    conn.commit()
    import_mode_rows = conn.execute(
        """
        SELECT il.id, il.quantity, il.purchase_quantity, il.purchase_unit_label, il.saved_variant_label, il.line_units_per_purchase
        FROM invoice_lines il
        WHERE il.import_mode IS NULL OR trim(il.import_mode) = ''
        """
    ).fetchall()
    for line_id, quantity, purchase_quantity, purchase_unit_label, saved_variant_label, line_units_per_purchase in import_mode_rows:
        inferred_mode = infer_invoice_line_import_mode(saved_variant_label, purchase_unit_label, line_units_per_purchase, quantity, purchase_quantity, '')
        conn.execute('UPDATE invoice_lines SET import_mode = ? WHERE id = ?', (inferred_mode, line_id))
    conn.commit()
    # Migrate legacy supplier text into suppliers table.
    supplier_rows = conn.execute(
        "SELECT id, supplier FROM invoices WHERE supplier IS NOT NULL AND trim(supplier) != '' AND (supplier_id IS NULL OR supplier_id = '')"
    ).fetchall()
    ts = now_iso()
    for invoice_id, supplier_name in supplier_rows:
        existing = conn.execute('SELECT id FROM suppliers WHERE lower(name)=lower(?)', (supplier_name.strip(),)).fetchone()
        if existing:
            supplier_id = existing[0]
        else:
            cur = conn.execute(
                'INSERT INTO suppliers (name, notes, created_at, updated_at) VALUES (?, ?, ?, ?)',
                (supplier_name.strip(), None, ts, ts),
            )
            supplier_id = cur.lastrowid
        conn.execute('UPDATE invoices SET supplier_id = ? WHERE id = ?', (supplier_id, invoice_id))
    conn.commit()
    article_supplier_rows = conn.execute(
        '''
        SELECT DISTINCT v.group_id, i.supplier_id
        FROM invoices i
        JOIN invoice_lines il ON il.invoice_id = i.id
        JOIN article_variants v ON v.id = il.variant_id
        WHERE i.supplier_id IS NOT NULL
        '''
    ).fetchall()
    for group_id, supplier_id in article_supplier_rows:
        conn.execute(
            'INSERT OR IGNORE INTO article_suppliers (group_id, supplier_id, created_at) VALUES (?, ?, ?)',
            (group_id, supplier_id, ts),
        )
    conn.commit()
    standardize_default_variants(conn)
    conn.commit()
    seed_default_shopping_lists(conn)
    sync_shopping_categories(conn)
    conn.close()
    seed_if_empty()
def standardize_default_variants(conn):
    ts = now_iso()
    standard_rows = conn.execute(
        """
        SELECT id, group_id, variant_label,
               COALESCE(NULLIF(trim(purchase_unit), ''), variant_label) AS purchase_unit,
               COALESCE(NULLIF(trim(stock_unit), ''), variant_label) AS stock_unit,
               COALESCE(units_per_purchase, 1) AS units_per_purchase
        FROM article_variants
        WHERE lower(trim(variant_label)) = 'standard'
        ORDER BY group_id, id
        """
    ).fetchall()
    for row in standard_rows:
        src_id, group_id, _, purchase_unit, stock_unit, units_per_purchase = row
        target = conn.execute(
            "SELECT id FROM article_variants WHERE group_id = ? AND lower(trim(variant_label)) = 'stück' AND id != ?",
            (group_id, src_id),
        ).fetchone()
        # normalize purchase labels on lines first
        conn.execute(
            "UPDATE invoice_lines SET purchase_unit_label = 'Stück' WHERE variant_id = ? AND lower(trim(COALESCE(purchase_unit_label,''))) = 'standard'",
            (src_id,),
        )
        if target:
            target_id = target[0]
            src_counts = conn.execute('SELECT * FROM inventory_counts WHERE variant_id = ?', (src_id,)).fetchall()
            for count in src_counts:
                existing = conn.execute('SELECT * FROM inventory_counts WHERE variant_id = ? AND year = ?', (target_id, count[1])).fetchone()
                if existing:
                    opening = (float(existing[3]) if existing[3] not in (None, '') else 0.0) + (float(count[3]) if count[3] not in (None, '') else 0.0)
                    closing_existing = float(existing[4]) if existing[4] not in (None, '') else None
                    closing_src = float(count[4]) if count[4] not in (None, '') else None
                    if closing_existing is None and closing_src is None:
                        closing = None
                    else:
                        closing = (closing_existing or 0.0) + (closing_src or 0.0)
                    inventory_price = existing[5] if existing[5] not in (None, '') else count[5]
                    conn.execute('UPDATE inventory_counts SET opening_stock = ?, closing_stock = ?, inventory_price = ?, updated_at = ? WHERE id = ?', (opening, closing, inventory_price, ts, existing[0]))
                    conn.execute('DELETE FROM inventory_counts WHERE id = ?', (count[0],))
                else:
                    conn.execute('UPDATE inventory_counts SET variant_id = ?, updated_at = ? WHERE id = ?', (target_id, ts, count[0]))
            conn.execute('UPDATE invoice_lines SET variant_id = ? WHERE variant_id = ?', (target_id, src_id))
            conn.execute('DELETE FROM article_variants WHERE id = ?', (src_id,))
        else:
            normalized_purchase = 'Stück' if normalize_text(purchase_unit) == 'standard' else purchase_unit
            normalized_stock = 'Stück' if normalize_text(stock_unit) == 'standard' else stock_unit
            conn.execute(
                'UPDATE article_variants SET variant_label = ?, purchase_unit = ?, stock_unit = ?, updated_at = ? WHERE id = ?',
                ('Stück', normalized_purchase, normalized_stock, ts, src_id),
            )
            conn.execute(
                "UPDATE invoice_lines SET purchase_unit_label = 'Stück' WHERE variant_id = ? AND lower(trim(COALESCE(purchase_unit_label,''))) = 'standard'",
                (src_id,),
            )
def seed_if_empty():
    # Echtbestände werden ausschließlich aus dem lokalen /data-Speicher angelegt.
    return

def ensure_group(name, category='', notes=''):
    name = (name or '').strip()
    if not name:
        raise ValueError('Artikelname fehlt.')
    row = query_one('SELECT id FROM article_groups WHERE lower(name)=lower(?)', (name,))
    if row:
        return row['id']
    cur = execute(
        'INSERT INTO article_groups (name, category, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
        (name, None, notes.strip() or None, now_iso(), now_iso()),
    )
    log_event(f'Artikelgruppe angelegt: {name}')
    return cur.lastrowid
def ensure_variant(group_id, variant_label, unit='', purchase_unit='', stock_unit='', units_per_purchase=1):
    variant_label = (variant_label or '').strip()
    unit = (unit or '').strip()
    purchase_unit = (purchase_unit or variant_label).strip()
    stock_unit = (stock_unit or variant_label).strip()
    try:
        units_per_purchase = float(str(units_per_purchase).replace(',', '.')) if units_per_purchase not in (None, '') else 1.0
    except ValueError:
        units_per_purchase = 1.0
    if units_per_purchase <= 0:
        units_per_purchase = 1.0
    if not variant_label:
        raise ValueError('Gebinde / Variante fehlt.')
    row = query_one(
        'SELECT id FROM article_variants WHERE group_id = ? AND lower(variant_label)=lower(?)',
        (group_id, variant_label),
    )
    if row:
        execute(
            'UPDATE article_variants SET unit = COALESCE(?, unit), purchase_unit = COALESCE(NULLIF(?, ""), purchase_unit), stock_unit = COALESCE(NULLIF(?, ""), stock_unit), units_per_purchase = COALESCE(?, units_per_purchase), updated_at = ? WHERE id = ?',
            (unit or None, purchase_unit, stock_unit, units_per_purchase, now_iso(), row['id']),
        )
        recalculate_variant_invoice_lines(row['id'])
        return row['id']
    cur = execute(
        'INSERT INTO article_variants (group_id, variant_label, unit, purchase_unit, stock_unit, units_per_purchase, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)',
        (group_id, variant_label, unit or None, purchase_unit, stock_unit, units_per_purchase, now_iso(), now_iso()),
    )
    log_event(f'Variante angelegt: group_id={group_id}, variant={variant_label}')
    return cur.lastrowid
def ensure_supplier(name, notes=''):
    name = (name or '').strip()
    if not name:
        raise ValueError('Lieferant fehlt.')
    row = query_one('SELECT id FROM suppliers WHERE lower(name)=lower(?)', (name,))
    if row:
        return row['id']
    cur = execute(
        'INSERT INTO suppliers (name, notes, created_at, updated_at) VALUES (?, ?, ?, ?)',
        (name, notes.strip() or None, now_iso(), now_iso()),
    )
    log_event(f'Lieferant angelegt: {name}')
    return cur.lastrowid

def normalize_invoice_line_values(variant_row, purchase_quantity, purchase_price):
    qty = float(purchase_quantity) if purchase_quantity is not None else None
    price = float(purchase_price)
    units_per_purchase = float(variant_row['units_per_purchase'] or 1)
    if units_per_purchase <= 0:
        units_per_purchase = 1
    normalized_quantity = qty * units_per_purchase if qty is not None else None
    normalized_price = price / units_per_purchase
    return normalized_quantity, normalized_price

def repair_piece_variant_units(conn):
    ts = now_iso()
    rows = conn.execute(
        '''
        SELECT id, variant_label,
               COALESCE(NULLIF(trim(purchase_unit), ''), variant_label) AS purchase_unit,
               COALESCE(NULLIF(trim(stock_unit), ''), variant_label) AS stock_unit,
               COALESCE(units_per_purchase, 1) AS units_per_purchase
        FROM article_variants
        WHERE lower(trim(COALESCE(variant_label, ''))) = 'stück'
           OR lower(trim(COALESCE(variant_label, ''))) = 'stueck'
        '''
    ).fetchall()
    for row in rows:
        variant_id = row[0]
        variant_label = (row[1] or '').strip() or 'Stück'
        purchase_unit = (row[2] or '').strip() or variant_label
        stock_unit = (row[3] or '').strip() or variant_label
        current_units = float(row[4] or 1)
        parsed_purchase_label, parsed_stock_unit, parsed_units = parse_purchase_unit_label(purchase_unit)
        needs_stock_fix = normalize_text(stock_unit) == normalize_text(purchase_unit) and normalize_text(stock_unit) != normalize_text(variant_label)
        target_stock_unit = variant_label if needs_stock_fix else stock_unit
        target_units = current_units if current_units > 0 else 1.0
        parsed_units_value = parse_number(parsed_units) or 1.0
        if parsed_stock_unit and normalize_text(parsed_stock_unit) == normalize_text(variant_label) and parsed_units_value > 1:
            target_units = parsed_units_value
        if normalize_text(target_stock_unit) != normalize_text(stock_unit) or abs(target_units - current_units) > 1e-9:
            conn.execute(
                'UPDATE article_variants SET stock_unit = ?, units_per_purchase = ?, updated_at = ? WHERE id = ?',
                (target_stock_unit, target_units, ts, variant_id),
            )
            variant_row = {
                'id': variant_id,
                'purchase_unit': purchase_unit,
                'stock_unit': target_stock_unit,
                'units_per_purchase': target_units,
            }
            invoice_rows = conn.execute('SELECT id, purchase_quantity, purchase_price FROM invoice_lines WHERE variant_id = ?', (variant_id,)).fetchall()
            for invoice_row in invoice_rows:
                if invoice_row[2] is None:
                    continue
                normalized_quantity, normalized_price = normalize_invoice_line_values(variant_row, invoice_row[1], invoice_row[2])
                conn.execute('UPDATE invoice_lines SET quantity = ?, net_price = ? WHERE id = ?', (normalized_quantity, normalized_price, invoice_row[0]))

def repair_pack_mode_variant_units(conn):
    ts = now_iso()
    rows = conn.execute(
        '''
        SELECT id, variant_label,
               COALESCE(NULLIF(trim(purchase_unit), ''), variant_label) AS purchase_unit,
               COALESCE(NULLIF(trim(stock_unit), ''), variant_label) AS stock_unit,
               COALESCE(units_per_purchase, 1) AS units_per_purchase
        FROM article_variants
        WHERE trim(COALESCE(variant_label, '')) != ''
        '''
    ).fetchall()
    for row in rows:
        variant_id = row[0]
        variant_label = (row[1] or '').strip()
        purchase_unit = (row[2] or '').strip() or variant_label
        stock_unit = (row[3] or '').strip() or variant_label
        units_per_purchase = parse_number(row[4]) or 1
        if not variant_label:
            continue
        if units_per_purchase > 1:
            continue
        if normalize_text(purchase_unit) == normalize_text(variant_label) and normalize_text(stock_unit) == normalize_text(variant_label):
            continue
        conn.execute(
            'UPDATE article_variants SET purchase_unit = ?, stock_unit = ?, units_per_purchase = 1, updated_at = ? WHERE id = ?',
            (variant_label, variant_label, ts, variant_id),
        )
        invoice_rows = conn.execute('SELECT id, purchase_quantity, purchase_price FROM invoice_lines WHERE variant_id = ?', (variant_id,)).fetchall()
        for invoice_row in invoice_rows:
            if invoice_row[2] is None:
                continue
            purchase_quantity = invoice_row[1]
            normalized_quantity = float(purchase_quantity) if purchase_quantity is not None else None
            normalized_price = float(invoice_row[2])
            conn.execute(
                'UPDATE invoice_lines SET quantity = ?, net_price = ? WHERE id = ?',
                (normalized_quantity, normalized_price, invoice_row[0]),
            )

def recalculate_variant_invoice_lines(variant_id):
    variant = query_one('SELECT id, purchase_unit, stock_unit, units_per_purchase FROM article_variants WHERE id = ?', (variant_id,))
    if not variant:
        return
    rows = query_all('SELECT id, purchase_quantity, purchase_price FROM invoice_lines WHERE variant_id = ?', (variant_id,))
    for row in rows:
        if row['purchase_price'] is None:
            continue
        normalized_quantity, normalized_price = normalize_invoice_line_values(variant, row['purchase_quantity'], row['purchase_price'])
        execute('UPDATE invoice_lines SET quantity = ?, net_price = ? WHERE id = ?', (normalized_quantity, normalized_price, row['id']))
    current_year = datetime.now().year
    inventory_price = query_one(
        '''
        SELECT il.net_price FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        WHERE il.variant_id = ?
        ORDER BY i.invoice_date DESC, il.id DESC LIMIT 1
        ''',
        (variant_id,),
    )
    if inventory_price:
        execute('UPDATE inventory_counts SET inventory_price = ?, updated_at = ? WHERE variant_id = ? AND year >= ?', (inventory_price['net_price'], now_iso(), variant_id, current_year))

def latest_price_for_variant(variant_id):
    return query_one(
        '''
        SELECT i.invoice_date AS point_date, il.net_price
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        WHERE il.variant_id = ?
        ORDER BY i.invoice_date DESC, il.id DESC
        LIMIT 1
        ''',
        (variant_id,),
    )

def inventory_layers_for_year(year, variant_id):
    opening = query_one(
        'SELECT opening_stock, inventory_price FROM inventory_counts WHERE year = ? AND variant_id = ?',
        (year, variant_id),
    )
    previous = query_one(
        'SELECT inventory_price FROM inventory_counts WHERE year = ? AND variant_id = ?',
        (year - 1, variant_id),
    )
    layers = []
    opening_stock = float(opening['opening_stock']) if opening and opening['opening_stock'] not in (None, '') else 0.0
    opening_price = None
    if previous and previous['inventory_price'] not in (None, ''):
        opening_price = float(previous['inventory_price'])
    elif opening and opening['inventory_price'] not in (None, ''):
        opening_price = float(opening['inventory_price'])
    if opening_stock > 0 and opening_price is not None:
        layers.append({'source': 'opening', 'sort_key': f'{year:04d}-01-01', 'quantity': opening_stock, 'price': opening_price})
    purchases = query_all(
        '''
        SELECT i.invoice_date, il.id, il.quantity, il.net_price
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        WHERE il.variant_id = ? AND substr(i.invoice_date, 1, 4) = ?
        ORDER BY i.invoice_date ASC, il.id ASC
        ''',
        (variant_id, str(year)),
    )
    for row in purchases:
        qty_val = float(row['quantity']) if row['quantity'] not in (None, '') else 0.0
        price_val = float(row['net_price']) if row['net_price'] not in (None, '') else None
        if qty_val > 0 and price_val is not None:
            layers.append({'source': 'invoice', 'sort_key': f"{row['invoice_date']}-{row['id']:010d}", 'quantity': qty_val, 'price': price_val})
    return layers

def inventory_available_quantity(layers):
    return sum(float(layer.get('quantity') or 0) for layer in (layers or []))

def inventory_value_from_layers(layers, closing_stock, fallback_price=None):
    if closing_stock in (None, ''):
        return None, None
    try:
        remaining = float(closing_stock)
    except (TypeError, ValueError):
        return None, None
    if remaining <= 0:
        return 0.0, 0.0
    available_total = inventory_available_quantity(layers)
    if remaining - available_total > 1e-9:
        return None, None
    total = 0.0
    for layer in reversed(layers or []):
        if remaining <= 0:
            break
        available = float(layer.get('quantity') or 0)
        if available <= 0:
            continue
        take = min(remaining, available)
        total += take * float(layer.get('price') or 0)
        remaining -= take
    avg_price = total / float(closing_stock) if float(closing_stock) > 0 else 0.0
    return total, avg_price

def inventory_value_for_year(year, variant_id, closing_stock):
    layers = inventory_layers_for_year(year, variant_id)
    fallback = query_one('SELECT inventory_price FROM inventory_counts WHERE year = ? AND variant_id = ?', (year, variant_id))
    fallback_price = fallback['inventory_price'] if fallback and fallback['inventory_price'] not in (None, '') else None
    return inventory_value_from_layers(layers, closing_stock, fallback_price)

def enrich_inventory_rows(year, rows):
    enriched = []
    for row in rows:
        data = dict(row)
        layers = inventory_layers_for_year(year, data['variant_id'])
        fallback_price = data.get('inventory_price')
        total_value, avg_price = inventory_value_from_layers(layers, data.get('closing_stock'), fallback_price)
        data['inventory_layers'] = layers
        data['available_quantity'] = inventory_available_quantity(layers)
        closing_val = float(data['closing_stock']) if data.get('closing_stock') not in (None, '') else None
        if closing_val is not None and closing_val - data['available_quantity'] > 1e-9:
            data['calculated_inventory_price'] = None
            data['calculated_inventory_value'] = None
            data['inventory_invalid'] = True
        elif avg_price is not None:
            data['calculated_inventory_price'] = avg_price
            data['calculated_inventory_value'] = total_value
            data['inventory_invalid'] = False
        else:
            data['calculated_inventory_price'] = data.get('inventory_price')
            closing = float(data['closing_stock']) if data.get('closing_stock') not in (None, '') else 0.0
            price = float(data['inventory_price']) if data.get('inventory_price') not in (None, '') else 0.0
            data['calculated_inventory_value'] = closing * price
            data['inventory_invalid'] = False
        enriched.append(data)
    return enriched
def grouped_variants():
    groups = query_all('SELECT id, name FROM article_groups ORDER BY name COLLATE NOCASE')
    result = []
    for group in groups:
        variants = query_all(
            'SELECT id, variant_label, COALESCE(unit, \"\") AS unit FROM article_variants WHERE group_id = ? AND is_active = 1 ORDER BY variant_label COLLATE NOCASE',
            (group['id'],),
        )
        result.append({'id': group['id'], 'name': group['name'], 'variants': variants})
    return result
def supplier_options():
    return query_all('SELECT id, name FROM suppliers ORDER BY name COLLATE NOCASE')
def get_article_suppliers(group_id):
    return query_all(
        '''
        SELECT s.id, s.name
        FROM article_suppliers aps
        JOIN suppliers s ON s.id = aps.supplier_id
        WHERE aps.group_id = ?
        ORDER BY s.name COLLATE NOCASE
        ''',
        (group_id,),
    )
def link_article_supplier(group_id, supplier_id):
    execute(
        'INSERT OR IGNORE INTO article_suppliers (group_id, supplier_id, created_at) VALUES (?, ?, ?)',
        (group_id, supplier_id, now_iso()),
    )
def unlink_article_supplier(group_id, supplier_id):
    execute('DELETE FROM article_suppliers WHERE group_id = ? AND supplier_id = ?', (group_id, supplier_id))
def dashboard_panels(current_year):
    ensure_inventory_year(current_year)
    return query_all(
        '''
        WITH ordered AS (
            SELECT
                v.id AS variant_id,
                g.id AS group_id,
                g.name AS group_name,
                v.variant_label,
                i.invoice_date AS point_date,
                il.net_price AS net_price,
                LAG(il.net_price) OVER (PARTITION BY v.id ORDER BY i.invoice_date, il.id) AS previous_price,
                COALESCE(s.name, i.supplier, '–') AS supplier_name,
                il.id AS line_id
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            JOIN article_variants v ON v.id = il.variant_id
            JOIN article_groups g ON g.id = v.group_id
            LEFT JOIN suppliers s ON s.id = i.supplier_id
        )
        SELECT * FROM ordered
        WHERE previous_price IS NOT NULL
          AND previous_price != 0
          AND ABS(net_price - previous_price) > 0.0000001
        ORDER BY point_date DESC, line_id DESC
        LIMIT 10
        '''
    )
@app.context_processor
def inject_dashboard_panels():
    current_year = datetime.now().year
    latest_moves = dashboard_panels(current_year)
    return {
        'global_latest_price_moves': latest_moves,
    }
def ensure_inventory_year(year):
    variants = query_all('SELECT id FROM article_variants WHERE is_active = 1')
    for variant in variants:
        existing = query_one('SELECT id FROM inventory_counts WHERE year = ? AND variant_id = ?', (year, variant['id']))
        if existing:
            continue
        prev = query_one(
            'SELECT closing_stock, inventory_price FROM inventory_counts WHERE year = ? AND variant_id = ?',
            (year - 1, variant['id']),
        )
        latest = latest_price_for_variant(variant['id'])
        opening_stock = prev['closing_stock'] if prev else None
        inventory_price = latest['net_price'] if latest else (prev['inventory_price'] if prev else None)
        execute(
            'INSERT INTO inventory_counts (year, variant_id, opening_stock, closing_stock, inventory_price, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
            (year, variant['id'], opening_stock, None, inventory_price, now_iso()),
        )
def build_svg_chart(points):
    if not points:
        return None
    cleaned_points = []
    for point in points:
        item = dict(point) if point is not None else {}
        price_value = parse_number(item.get('chart_price', item.get('net_price')))
        if price_value is None:
            continue
        item['chart_price'] = price_value
        cleaned_points.append(item)
    if not cleaned_points:
        return None
    width, height, pad = 760, 300, 36
    ys = [p['chart_price'] for p in cleaned_points]
    min_y, max_y = min(ys), max(ys)
    if min_y == max_y:
        min_y -= 1
        max_y += 1
    def x_pos(idx):
        return width / 2 if len(cleaned_points) == 1 else pad + idx * ((width - 2 * pad) / (len(cleaned_points) - 1))
    def y_pos(val):
        return height - pad - ((val - min_y) / (max_y - min_y)) * (height - 2 * pad)
    poly = ' '.join(f'{x_pos(i):.1f},{y_pos(v):.1f}' for i, v in enumerate(ys))
    dots = '\n'.join(
        f'<circle cx="{x_pos(i):.1f}" cy="{y_pos(v):.1f}" r="5" fill="#2563eb"><title>{dmy(cleaned_points[i]["point_date"])}: {money(v)}</title></circle>'
        for i, v in enumerate(ys)
    )
    labels = '\n'.join(
        '<text x="{:.1f}" y="{}" fill="#64748b" font-size="11" text-anchor="middle">{}</text>'.format(x_pos(i), height - 10, dmy(cleaned_points[i]["point_date"]))
        for i in range(len(cleaned_points))
    ).replace('</text>', '</text>')
    return f'''
    <svg viewBox="0 0 {width} {height}" width="100%" height="300" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Preisverlauf">
      <rect x="0" y="0" width="{width}" height="{height}" rx="18" fill="#f8fafc" stroke="#dbe2ea" />
      <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#cbd5e1" />
      <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#cbd5e1" />
      <polyline points="{poly}" fill="none" stroke="#2563eb" stroke-width="4" />
      {dots}
      {labels}
      <text x="{pad}" y="{pad - 10}" fill="#64748b" font-size="12">min {money(min(ys))}</text>
      <text x="{width-pad}" y="{pad - 10}" fill="#64748b" font-size="12" text-anchor="end">max {money(max(ys))}</text>
    </svg>
    '''

def price_points_for_variant(variant_id):
    return query_all(
        '''
        SELECT i.invoice_date AS point_date,
               il.net_price,
               CASE
                   WHEN i.invoice_number = 'SEED-2024' AND COALESCE(il.quantity, 0) = 0
                   THEN COALESCE(ic.closing_stock, ic.opening_stock, 0)
                   ELSE il.quantity
               END AS quantity,
               CASE
                   WHEN i.invoice_number = 'SEED-2024' AND COALESCE(il.purchase_quantity, 0) = 0
                   THEN COALESCE(ic.closing_stock, ic.opening_stock, 0)
                   ELSE il.purchase_quantity
               END AS purchase_quantity,
               il.purchase_price,
               il.purchase_unit_label,
               COALESCE(il.saved_variant_label, '') AS saved_variant_label,
               COALESCE(il.line_units_per_purchase, 1) AS line_units_per_purchase,
               COALESCE(il.import_mode, '') AS import_mode,
               COALESCE(s.name, i.supplier) AS supplier_name,
               CASE WHEN i.invoice_number = 'SEED-2024' THEN 'Inventur-Startwert' ELSE 'Rechnung' END AS source_type
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        LEFT JOIN suppliers s ON s.id = i.supplier_id
        LEFT JOIN inventory_counts ic ON ic.variant_id = il.variant_id AND ic.year = 2024
        WHERE il.variant_id = ?
        ORDER BY i.invoice_date ASC, il.id ASC
        ''',
        (variant_id,),
    )
def article_dropdown_options():
    return query_all(
        'SELECT id, name FROM article_groups ORDER BY name COLLATE NOCASE'
    )
def supplier_dropdown_options():
    return query_all(
        'SELECT id, name FROM suppliers ORDER BY name COLLATE NOCASE'
    )
def variant_label_options():
    return query_all(
        'SELECT DISTINCT variant_label FROM article_variants WHERE trim(COALESCE(variant_label, "")) != "" ORDER BY variant_label COLLATE NOCASE'
    )

def variant_label_catalog():
    def _seed_entry(label: str):
        return {
            'variant_label': (label or '').strip(),
            'variant_key': normalize_text(label),
            'usage_count': 0,
            'article_ids': set(),
        }

    catalog = {}

    linked_rows = query_all(
        '''
        SELECT v.variant_label, v.group_id
        FROM article_variants v
        WHERE trim(COALESCE(v.variant_label, '')) != '' AND COALESCE(v.is_active, 1) = 1
        ORDER BY v.variant_label COLLATE NOCASE
        '''
    )
    for row in linked_rows:
        raw_label = (row['variant_label'] or '').strip()
        key = normalize_text(raw_label)
        if not key:
            continue
        entry = catalog.get(key)
        if not entry:
            entry = _seed_entry(raw_label)
            catalog[key] = entry
        if raw_label and len(raw_label) < len(entry['variant_label'] or raw_label):
            entry['variant_label'] = raw_label
        if row['group_id'] is not None:
            entry['article_ids'].add(int(row['group_id']))
        entry['usage_count'] += 1

    result = []
    for entry in catalog.values():
        article_ids = entry.pop('article_ids', set())
        entry['article_count'] = len(article_ids)
        if entry['article_count'] > 0:
            result.append(entry)
    return sorted(result, key=lambda item: normalize_text(item['variant_label']))


def base_context(active_page='dashboard', title=None):
    return {
        'active_page': active_page,
        'title': title,
        'current_year': datetime.now().year,
    }
def first_group_match(query_text):
    q = f"%{(query_text or '').strip()}%"
    return query_one(
        '''
        SELECT DISTINCT g.id, g.name
        FROM article_groups g
        LEFT JOIN article_variants v ON v.group_id = g.id
        WHERE g.name LIKE ? COLLATE NOCASE OR v.variant_label LIKE ? COLLATE NOCASE OR COALESCE(v.unit, '') LIKE ? COLLATE NOCASE
        ORDER BY CASE WHEN lower(g.name) = lower(?) THEN 0 ELSE 1 END, g.name COLLATE NOCASE
        LIMIT 1
        ''',
        (q, q, q, (query_text or '').strip()),
    )
def first_supplier_match(query_text):
    q = f"%{(query_text or '').strip()}%"
    return query_one(
        'SELECT id, name FROM suppliers WHERE name LIKE ? COLLATE NOCASE ORDER BY CASE WHEN lower(name)=lower(?) THEN 0 ELSE 1 END, name COLLATE NOCASE LIMIT 1',
        (q, (query_text or '').strip()),
    )
@app.route('/')
def dashboard():
    current_year = datetime.now().year
    ensure_inventory_year(current_year)
    latest_inventory_year_row = query_one('SELECT MAX(year) AS y FROM inventory_counts WHERE closing_stock IS NOT NULL')
    latest_inventory_year = latest_inventory_year_row['y'] if latest_inventory_year_row and latest_inventory_year_row['y'] else None
    latest_inventory_value = 0.0
    if latest_inventory_year:
        latest_inventory_value = query_one(
            'SELECT COALESCE(SUM(COALESCE(closing_stock, 0) * COALESCE(inventory_price, 0)), 0) AS total FROM inventory_counts WHERE year = ?',
            (latest_inventory_year,),
        )['total']
    stats = {
        'group_count': query_one('SELECT COUNT(*) AS c FROM article_groups')['c'],
        'invoice_count': query_one("SELECT COUNT(*) AS c FROM invoices WHERE substr(invoice_date,1,4) = ?", (str(current_year),))['c'],
        'supplier_count': query_one('SELECT COUNT(*) AS c FROM suppliers')['c'],
        'inventory_year': latest_inventory_year,
        'inventory_value': latest_inventory_value,
    }
    recent_invoices = query_all(
        '''
        SELECT i.id, i.invoice_date, COALESCE(s.name, i.supplier, '–') AS supplier_name,
               COALESCE(SUM(COALESCE(il.purchase_quantity, il.quantity, 1) * COALESCE(il.purchase_price, il.net_price, 0)), 0) AS total
        FROM invoices i
        LEFT JOIN suppliers s ON s.id = i.supplier_id
        LEFT JOIN invoice_lines il ON il.invoice_id = i.id
        GROUP BY i.id, i.invoice_date, supplier_name
        ORDER BY i.invoice_date DESC, i.id DESC
        LIMIT 5
        '''
    )
    price_changes = dashboard_panels(current_year)
    return render_template(
        'dashboard.html',
        stats=stats,
        recent_invoices=recent_invoices,
        price_changes=price_changes,
        show_latest_moves=False,
        **base_context('dashboard', 'InventurManager – Übersicht'),
    )



def normalize_shopping_text(value):
    text = str(value or '').strip().lower()
    text = text.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()

SHOPPING_NUMBER_WORDS = {
    'ein': 1, 'eine': 1, 'einen': 1, 'einem': 1, 'einer': 1, 'eins': 1,
    'zwei': 2, 'drei': 3, 'vier': 4, 'fuenf': 5, 'fünf': 5, 'sechs': 6,
    'sieben': 7, 'acht': 8, 'neun': 9, 'zehn': 10,
}
SHOPPING_UNIT_ALIASES = {
    'stk': 'Stück', 'stueck': 'Stück', 'stück': 'Stück', 'x': 'Stück',
    'kilo': 'kg', 'kg': 'kg', 'g': 'g', 'mg': 'mg', 'liter': 'l', 'l': 'l', 'ml': 'ml',
    'packung': 'Packung', 'packungen': 'Packungen', 'paket': 'Paket', 'pakete': 'Pakete',
    'flasche': 'Flasche', 'flaschen': 'Flaschen', 'dose': 'Dose', 'dosen': 'Dosen',
    'bund': 'Bund', 'kiste': 'Kiste', 'kisten': 'Kisten', 'karton': 'Karton', 'kartons': 'Kartons',
    'beutel': 'Beutel', 'tuete': 'Tüte', 'tueten': 'Tüten', 'tüte': 'Tüte', 'tüten': 'Tüten',
}

def shopping_number_value(raw):
    text = str(raw or '').strip().lower()
    if text in SHOPPING_NUMBER_WORDS:
        return float(SHOPPING_NUMBER_WORDS[text])
    try:
        return float(text.replace(',', '.'))
    except ValueError:
        return None


def shopping_quantity_text(value, unit='Stück'):
    if value is None:
        return ''
    number = int(value) if float(value).is_integer() else float(value)
    unit_key = str(unit or 'Stück').strip().lower()
    label = SHOPPING_UNIT_ALIASES.get(unit_key, str(unit or 'Stück').strip())
    return f'{number} {label}'.strip()


def parse_shopping_input(raw):
    original = re.sub(r'\s+', ' ', str(raw or '').strip())
    if not original:
        return {'name': '', 'quantity_text': ''}
    number_pattern = r'(?:\d+(?:[.,]\d+)?|ein|eine|einen|einem|einer|eins|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn)'
    unit_pattern = r'(kg|kilo|g|mg|l|liter|ml|stück|stueck|stk|packung|packungen|paket|flasche|flaschen|dose|dosen|bund|kiste|kisten|karton|kartons|beutel|tüte|tüten|tuete|tueten|x)?'
    leading = re.match(rf'^({number_pattern})\s*(?:mal\s*)?{unit_pattern}\s+(.+)$', original, flags=re.I)
    trailing = re.match(rf'^(.+?)\s+({number_pattern})\s*(?:mal\s*)?{unit_pattern}$', original, flags=re.I)
    if leading:
        value = shopping_number_value(leading.group(1))
        unit = leading.group(2) or 'Stück'
        return {'name': leading.group(3).strip(), 'quantity_text': shopping_quantity_text(value, unit)}
    if trailing:
        value = shopping_number_value(trailing.group(2))
        unit = trailing.group(3) or 'Stück'
        return {'name': trailing.group(1).strip(), 'quantity_text': shopping_quantity_text(value, unit)}
    return {'name': original, 'quantity_text': ''}


def shopping_item_payload(row):
    return {
        'id': row['id'], 'event_id': row['event_id'], 'name': row['name'],
        'category': (row['category'] or 'Weitere Artikel').strip() or 'Weitere Artikel',
        'quantity_text': row['quantity_text'] or '', 'source': row['source'] or '',
        'checked': bool(row['checked']), 'favorite': bool(row['favorite'] if 'favorite' in row.keys() else 0),
        'use_count': int(row['use_count'] if 'use_count' in row.keys() and row['use_count'] is not None else 0),
        'sort_order': int(row['sort_order'] or 0), 'updated_at': row['updated_at'],
        'last_checked_at': row['last_checked_at'] if 'last_checked_at' in row.keys() else None,
    }


def shopping_public_state(requested_slug=''):
    events = query_all('SELECT * FROM shopping_events ORDER BY sort_order, name COLLATE NOCASE')
    default_slug = default_shopping_slug()
    wanted_slug = (requested_slug or default_slug or '').strip()
    active_event = query_one('SELECT * FROM shopping_events WHERE slug = ?', (wanted_slug,)) if wanted_slug else None
    if not active_event and events:
        active_event = events[0]
    event_payload = []
    for event in events:
        counts = query_one('SELECT COUNT(*) AS total, SUM(CASE WHEN checked = 0 THEN 1 ELSE 0 END) AS open_count, SUM(CASE WHEN checked = 1 THEN 1 ELSE 0 END) AS done_count FROM shopping_items WHERE event_id = ?', (event['id'],))
        event_payload.append({
            'id': event['id'], 'slug': event['slug'], 'name': event['name'], 'sort_order': event['sort_order'],
            'item_count': int(counts['total'] or 0), 'open_count': int(counts['open_count'] or 0), 'done_count': int(counts['done_count'] or 0),
            'is_default': event['slug'] == default_slug,
        })
    if not active_event:
        return {'events': event_payload, 'active_event': None, 'items': [], 'entries': [], 'recent': [], 'favorites': [], 'categories': [], 'default_event_slug': default_slug, 'updated_at': now_iso()}
    # Keep category order stable and user-defined. Missing legacy categories are added lazily.
    sync_shopping_categories(get_db(), active_event['id'])
    rows = query_all(
        """SELECT si.*
           FROM shopping_items si
           LEFT JOIN shopping_categories sc
             ON sc.event_id = si.event_id
            AND sc.name = COALESCE(NULLIF(trim(si.category), ''), 'Weitere Artikel')
           WHERE si.event_id = ?
           ORDER BY COALESCE(sc.sort_order, 999999), si.sort_order, si.name COLLATE NOCASE""",
        (active_event['id'],),
    )
    items = [shopping_item_payload(row) for row in rows]
    category_rows = query_all(
        'SELECT id, name, sort_order, updated_at FROM shopping_categories WHERE event_id = ? ORDER BY sort_order, id',
        (active_event['id'],),
    )
    categories = [
        {'id': row['id'], 'name': row['name'], 'sort_order': int(row['sort_order'] or 0)}
        for row in category_rows
        if any(item['category'] == row['name'] for item in items)
    ]
    entries = [item for item in items if not item['checked']]
    recent = sorted((item for item in items if item['checked']), key=lambda item: item.get('last_checked_at') or item.get('updated_at') or '', reverse=True)
    favorites = sorted((item for item in items if item['favorite']), key=lambda item: (-item['use_count'], item['name'].lower()))
    active = {'id': active_event['id'], 'slug': active_event['slug'], 'name': active_event['name'], 'sort_order': active_event['sort_order']}
    return {
        'events': event_payload, 'active_event': active, 'items': items, 'entries': entries, 'recent': recent,
        'favorites': favorites, 'categories': categories, 'default_event_slug': default_slug,
        'updated_at': max(
            [item['updated_at'] or '' for item in items] + [row['updated_at'] or '' for row in category_rows] + [active_event['updated_at'] or ''],
            default=now_iso(),
        ),
    }


def shopping_event_or_404(event_id):
    return query_one('SELECT * FROM shopping_events WHERE id = ?', (event_id,))


def shopping_item_or_404(event_id, item_id):
    return query_one('SELECT * FROM shopping_items WHERE id = ? AND event_id = ?', (item_id, event_id))


@app.get('/api/shopping/state')
def shopping_api_state():
    return jsonify(shopping_public_state(request.args.get('event', '').strip()))


@app.post('/api/shopping/default')
def shopping_api_set_default():
    body = request.get_json(silent=True) or {}
    slug = str(body.get('slug') or '').strip()
    event = query_one('SELECT id, slug, name FROM shopping_events WHERE slug = ?', (slug,)) if slug else None
    if not event:
        return jsonify({'error': 'Einkaufsliste nicht gefunden.'}), 404
    app_meta_set('shopping_default_event_slug', event['slug'])
    return jsonify({'ok': True, 'slug': event['slug'], 'name': event['name']})


@app.post('/api/shopping/<int:event_id>/items')
def shopping_api_add_item(event_id):
    event = shopping_event_or_404(event_id)
    if not event:
        return jsonify({'error': 'Einkaufsliste nicht gefunden.'}), 404
    body = request.get_json(silent=True) or {}
    parsed = parse_shopping_input(body.get('input') or body.get('name') or '')
    name = str(body.get('name') or parsed['name']).strip()
    if not name:
        return jsonify({'error': 'Bitte einen Artikel eingeben.'}), 400
    quantity_text = str(body.get('quantity_text') if body.get('quantity_text') is not None else parsed['quantity_text']).strip()
    category = str(body.get('category') or '').strip()
    source = str(body.get('source') or '').strip()
    normalized = normalize_shopping_text(name)
    existing_rows = query_all('SELECT * FROM shopping_items WHERE event_id = ?', (event_id,))
    existing = next((row for row in existing_rows if normalize_shopping_text(row['name']) == normalized), None)
    ts = now_iso()
    if existing:
        if existing['checked']:
            execute('UPDATE shopping_items SET checked = 0, quantity_text = ?, last_checked_at = NULL, updated_at = ? WHERE id = ? AND event_id = ?', (quantity_text or existing['quantity_text'] or '', ts, existing['id'], event_id))
            return jsonify({'status': 'reactivated', 'item': shopping_item_payload(shopping_item_or_404(event_id, existing['id']))})
        if quantity_text and quantity_text != (existing['quantity_text'] or ''):
            execute('UPDATE shopping_items SET quantity_text = ?, updated_at = ? WHERE id = ? AND event_id = ?', (quantity_text, ts, existing['id'], event_id))
        return jsonify({'status': 'duplicate', 'item': shopping_item_payload(shopping_item_or_404(event_id, existing['id']))}), 409
    if not category:
        category = 'Weitere Artikel'
    sync_shopping_categories(get_db(), event_id)
    if not query_one('SELECT id FROM shopping_categories WHERE event_id = ? AND name = ?', (event_id, category)):
        cat_order = query_one('SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM shopping_categories WHERE event_id = ?', (event_id,))['n']
        execute('INSERT INTO shopping_categories (event_id, name, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?)', (event_id, category, cat_order, ts, ts))
    next_order = query_one('SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM shopping_items WHERE event_id = ?', (event_id,))['n']
    cur = execute(
        '''INSERT INTO shopping_items (event_id, name, category, quantity_text, source, checked, favorite, use_count, sort_order, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?)''',
        (event_id, name, category, quantity_text, source, next_order, ts, ts),
    )
    return jsonify({'status': 'added', 'item': shopping_item_payload(shopping_item_or_404(event_id, cur.lastrowid))})


@app.patch('/api/shopping/<int:event_id>/items/<int:item_id>')
def shopping_api_patch_item(event_id, item_id):
    item = shopping_item_or_404(event_id, item_id)
    if not item:
        return jsonify({'error': 'Artikel nicht gefunden.'}), 404
    body = request.get_json(silent=True) or {}
    name = str(body.get('name', item['name'])).strip() or item['name']
    category = str(body.get('category', item['category'] or 'Weitere Artikel')).strip() or 'Weitere Artikel'
    quantity_text = str(body.get('quantity_text', item['quantity_text'] or '')).strip()
    source = str(body.get('source', item['source'] or '')).strip()
    favorite = 1 if bool(body.get('favorite', item['favorite'])) else 0
    checked = 1 if bool(body.get('checked', item['checked'])) else 0
    last_checked = item['last_checked_at']
    use_count = int(item['use_count'] or 0)
    if checked and not item['checked']:
        last_checked = now_iso()
        use_count += 1
    if not checked and item['checked']:
        last_checked = None
    sync_shopping_categories(get_db(), event_id)
    if not query_one('SELECT id FROM shopping_categories WHERE event_id = ? AND name = ?', (event_id, category)):
        cat_order = query_one('SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM shopping_categories WHERE event_id = ?', (event_id,))['n']
        ts_category = now_iso()
        execute('INSERT INTO shopping_categories (event_id, name, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?)', (event_id, category, cat_order, ts_category, ts_category))
    execute(
        '''UPDATE shopping_items SET name = ?, category = ?, quantity_text = ?, source = ?, checked = ?, favorite = ?, use_count = ?, last_checked_at = ?, updated_at = ?
           WHERE id = ? AND event_id = ?''',
        (name, category, quantity_text, source, checked, favorite, use_count, last_checked, now_iso(), item_id, event_id),
    )
    return jsonify({'item': shopping_item_payload(shopping_item_or_404(event_id, item_id))})


@app.post('/api/shopping/<int:event_id>/items/<int:item_id>/check')
def shopping_api_check_item(event_id, item_id):
    item = shopping_item_or_404(event_id, item_id)
    if not item:
        return jsonify({'error': 'Artikel nicht gefunden.'}), 404
    body = request.get_json(silent=True) or {}
    checked = bool(body.get('checked', not bool(item['checked'])))
    use_count = int(item['use_count'] or 0)
    last_checked = item['last_checked_at']
    if checked and not item['checked']:
        use_count += 1
        last_checked = now_iso()
    elif not checked:
        last_checked = None
    execute('UPDATE shopping_items SET checked = ?, use_count = ?, last_checked_at = ?, updated_at = ? WHERE id = ? AND event_id = ?', (1 if checked else 0, use_count, last_checked, now_iso(), item_id, event_id))
    return jsonify({'item': shopping_item_payload(shopping_item_or_404(event_id, item_id))})


@app.post('/api/shopping/<int:event_id>/items/<int:item_id>/favorite')
def shopping_api_favorite_item(event_id, item_id):
    item = shopping_item_or_404(event_id, item_id)
    if not item:
        return jsonify({'error': 'Artikel nicht gefunden.'}), 404
    favorite = 0 if item['favorite'] else 1
    execute('UPDATE shopping_items SET favorite = ?, updated_at = ? WHERE id = ? AND event_id = ?', (favorite, now_iso(), item_id, event_id))
    return jsonify({'item': shopping_item_payload(shopping_item_or_404(event_id, item_id))})


@app.delete('/api/shopping/<int:event_id>/items/<int:item_id>')
def shopping_api_delete_item(event_id, item_id):
    item = shopping_item_or_404(event_id, item_id)
    if not item:
        return jsonify({'error': 'Artikel nicht gefunden.'}), 404
    payload = shopping_item_payload(item)
    execute('DELETE FROM shopping_items WHERE id = ? AND event_id = ?', (item_id, event_id))
    return jsonify({'deleted': payload})


@app.post('/api/shopping/<int:event_id>/reset')
def shopping_api_reset(event_id):
    event = shopping_event_or_404(event_id)
    if not event:
        return jsonify({'error': 'Einkaufsliste nicht gefunden.'}), 404
    execute("UPDATE shopping_items SET checked = 0, quantity_text = '', last_checked_at = NULL, updated_at = ? WHERE event_id = ?", (now_iso(), event_id))
    return jsonify({'ok': True})


@app.post('/api/shopping/<int:event_id>/bulk/category')
def shopping_api_bulk_category(event_id):
    if not shopping_event_or_404(event_id):
        return jsonify({'error': 'Einkaufsliste nicht gefunden.'}), 404
    body = request.get_json(silent=True) or {}
    ids = [int(value) for value in body.get('ids', []) if str(value).isdigit()]
    category = str(body.get('category') or '').strip()
    if not ids or not category:
        return jsonify({'error': 'Artikel und Kategorie fehlen.'}), 400
    sync_shopping_categories(get_db(), event_id)
    if not query_one('SELECT id FROM shopping_categories WHERE event_id = ? AND name = ?', (event_id, category)):
        cat_order = query_one('SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM shopping_categories WHERE event_id = ?', (event_id,))['n']
        ts_category = now_iso()
        execute('INSERT INTO shopping_categories (event_id, name, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?)', (event_id, category, cat_order, ts_category, ts_category))
    placeholders = ','.join('?' for _ in ids)
    execute(f'UPDATE shopping_items SET category = ?, updated_at = ? WHERE event_id = ? AND id IN ({placeholders})', (category, now_iso(), event_id, *ids))
    return jsonify({'updated': len(ids)})


@app.post('/api/shopping/<int:event_id>/categories/rename')
def shopping_api_rename_category(event_id):
    if not shopping_event_or_404(event_id):
        return jsonify({'error': 'Einkaufsliste nicht gefunden.'}), 404
    body = request.get_json(silent=True) or {}
    old = str(body.get('old') or '').strip()
    new = str(body.get('new') or '').strip()
    if not old or not new:
        return jsonify({'error': 'Kategorie fehlt.'}), 400
    sync_shopping_categories(get_db(), event_id)
    ts = now_iso()
    old_row = query_one('SELECT id, sort_order FROM shopping_categories WHERE event_id = ? AND name = ?', (event_id, old))
    new_row = query_one('SELECT id FROM shopping_categories WHERE event_id = ? AND name = ?', (event_id, new))
    execute('UPDATE shopping_items SET category = ?, updated_at = ? WHERE event_id = ? AND category = ?', (new, ts, event_id, old))
    if old_row:
        if new_row:
            execute('DELETE FROM shopping_categories WHERE id = ?', (old_row['id'],))
        else:
            execute('UPDATE shopping_categories SET name = ?, updated_at = ? WHERE id = ?', (new, ts, old_row['id']))
    return jsonify({'ok': True})


@app.post('/api/shopping/<int:event_id>/categories/reorder')
def shopping_api_reorder_category(event_id):
    if not shopping_event_or_404(event_id):
        return jsonify({'error': 'Einkaufsliste nicht gefunden.'}), 404
    body = request.get_json(silent=True) or {}
    name = str(body.get('name') or '').strip()
    try:
        direction = int(body.get('direction') or 0)
    except (TypeError, ValueError):
        direction = 0
    if not name or direction not in (-1, 1):
        return jsonify({'error': 'Ungültige Sortierung.'}), 400
    sync_shopping_categories(get_db(), event_id)
    rows = query_all('SELECT id, name, sort_order FROM shopping_categories WHERE event_id = ? ORDER BY sort_order, id', (event_id,))
    index = next((idx for idx, row in enumerate(rows) if row['name'] == name), -1)
    target_index = index + direction
    if index < 0 or target_index < 0 or target_index >= len(rows):
        return jsonify({'ok': True})
    current, target = rows[index], rows[target_index]
    ts = now_iso()
    execute('UPDATE shopping_categories SET sort_order = ?, updated_at = ? WHERE id = ?', (target['sort_order'], ts, current['id']))
    execute('UPDATE shopping_categories SET sort_order = ?, updated_at = ? WHERE id = ?', (current['sort_order'], ts, target['id']))
    return jsonify({'ok': True})


@app.post('/api/shopping/<int:event_id>/categories/delete')
def shopping_api_delete_category(event_id):
    if not shopping_event_or_404(event_id):
        return jsonify({'error': 'Einkaufsliste nicht gefunden.'}), 404
    body = request.get_json(silent=True) or {}
    category = str(body.get('category') or '').strip()
    target = str(body.get('target') or 'Weitere Artikel').strip() or 'Weitere Artikel'
    if not category or category == target:
        return jsonify({'error': 'Ungültige Kategorie.'}), 400
    sync_shopping_categories(get_db(), event_id)
    ts = now_iso()
    if not query_one('SELECT id FROM shopping_categories WHERE event_id = ? AND name = ?', (event_id, target)):
        cat_order = query_one('SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM shopping_categories WHERE event_id = ?', (event_id,))['n']
        execute('INSERT INTO shopping_categories (event_id, name, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?)', (event_id, target, cat_order, ts, ts))
    execute('UPDATE shopping_items SET category = ?, updated_at = ? WHERE event_id = ? AND category = ?', (target, ts, event_id, category))
    execute('DELETE FROM shopping_categories WHERE event_id = ? AND name = ?', (event_id, category))
    return jsonify({'ok': True})


@app.get('/shopping')
def shopping_page():
    events = query_all('SELECT * FROM shopping_events ORDER BY sort_order, name COLLATE NOCASE')
    requested = request.args.get('event', '').strip()
    wanted = requested or default_shopping_slug()
    active_event = None
    if wanted:
        active_event = query_one('SELECT * FROM shopping_events WHERE slug = ?', (wanted,))
    if not active_event and events:
        active_event = events[0]
    sections = []
    done_count = 0
    total_count = 0
    if active_event:
        rows = query_all(
            '''SELECT * FROM shopping_items
               WHERE event_id = ?
               ORDER BY sort_order, category COLLATE NOCASE, name COLLATE NOCASE''',
            (active_event['id'],),
        )
        total_count = len(rows)
        done_count = sum(1 for row in rows if row['checked'])
        by_category = {}
        for row in rows:
            category = (row['category'] or 'Weitere Artikel').strip() or 'Weitere Artikel'
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(row)
        sections = [{'name': name, 'items': items} for name, items in by_category.items()]
    initial_state = shopping_public_state(active_event['slug'] if active_event else '')
    return render_template(
        'shopping.html', events=events, active_event=active_event, sections=sections,
        done_count=done_count, total_count=total_count, shopping_state_json=json.dumps(initial_state, ensure_ascii=False),
        **base_context('shopping', 'InventurManager – Einkaufsliste')
    )


@app.post('/shopping/<int:event_id>/save')
def save_shopping(event_id):
    event = query_one('SELECT * FROM shopping_events WHERE id = ?', (event_id,))
    if not event:
        flash('Einkaufsliste nicht gefunden.', 'error')
        return redirect(url_for('shopping_page'))
    item_ids = request.form.getlist('item_id[]')
    for raw_id in item_ids:
        try:
            item_id = int(raw_id)
        except ValueError:
            continue
        item = query_one('SELECT id FROM shopping_items WHERE id = ? AND event_id = ?', (item_id, event_id))
        if not item:
            continue
        name = request.form.get(f'name_{item_id}', '').strip()
        category = request.form.get(f'category_{item_id}', '').strip()
        quantity_text = request.form.get(f'quantity_{item_id}', '').strip()
        source = request.form.get(f'source_{item_id}', '').strip()
        checked = 1 if request.form.get(f'checked_{item_id}') == '1' else 0
        if name:
            execute(
                '''UPDATE shopping_items
                   SET name = ?, category = ?, quantity_text = ?, source = ?, checked = ?, updated_at = ?
                   WHERE id = ? AND event_id = ?''',
                (name, category, quantity_text, source, checked, now_iso(), item_id, event_id),
            )
    flash(f'Einkaufsliste „{event["name"]}“ gespeichert.', 'success')
    return redirect(url_for('shopping_page', event=event['slug']))


@app.post('/shopping/<int:event_id>/add')
def add_shopping_item(event_id):
    event = query_one('SELECT * FROM shopping_events WHERE id = ?', (event_id,))
    if not event:
        flash('Einkaufsliste nicht gefunden.', 'error')
        return redirect(url_for('shopping_page'))
    name = request.form.get('name', '').strip()
    if not name:
        flash('Bitte einen Artikelnamen eingeben.', 'error')
        return redirect(url_for('shopping_page', event=event['slug']))
    category = request.form.get('category', '').strip() or 'Weitere Artikel'
    quantity_text = request.form.get('quantity_text', '').strip()
    source = request.form.get('source', '').strip()
    next_order = query_one('SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM shopping_items WHERE event_id = ?', (event_id,))['n']
    execute(
        '''INSERT INTO shopping_items
           (event_id, name, category, quantity_text, source, checked, sort_order, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)''',
        (event_id, name, category, quantity_text, source, next_order, now_iso(), now_iso()),
    )
    flash(f'„{name}“ wurde hinzugefügt.', 'success')
    return redirect(url_for('shopping_page', event=event['slug']))


@app.post('/shopping/<int:event_id>/item/<int:item_id>/delete')
def delete_shopping_item(event_id, item_id):
    event = query_one('SELECT * FROM shopping_events WHERE id = ?', (event_id,))
    item = query_one('SELECT name FROM shopping_items WHERE id = ? AND event_id = ?', (item_id, event_id))
    if event and item:
        execute('DELETE FROM shopping_items WHERE id = ? AND event_id = ?', (item_id, event_id))
        flash(f'„{item["name"]}“ wurde aus der Vorlage entfernt.', 'success')
    return redirect(url_for('shopping_page', event=event['slug'] if event else None))


@app.post('/shopping/<int:event_id>/reset')
def reset_shopping_event(event_id):
    event = query_one('SELECT * FROM shopping_events WHERE id = ?', (event_id,))
    if event:
        execute('UPDATE shopping_items SET checked = 0, quantity_text = \'\', last_checked_at = NULL, updated_at = ? WHERE event_id = ?', (now_iso(), event_id))
        flash(f'„{event["name"]}“ wurde für den nächsten Einkauf zurückgesetzt.', 'success')
    return redirect(url_for('shopping_page', event=event['slug'] if event else None))


@app.get('/prices')
def prices_page():
    q = request.args.get('q', '').strip()
    rows = query_all(
        '''
        WITH ranked AS (
            SELECT g.id AS group_id, g.name AS group_name, v.id AS variant_id, v.variant_label,
                   COALESCE(NULLIF(v.stock_unit, ''), v.variant_label) AS unit_label,
                   i.invoice_date AS point_date, il.net_price,
                   COALESCE(s.name, i.supplier, '–') AS supplier_name,
                   ROW_NUMBER() OVER (PARTITION BY v.id ORDER BY i.invoice_date DESC, il.id DESC) AS rn
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            JOIN article_variants v ON v.id = il.variant_id
            JOIN article_groups g ON g.id = v.group_id
            LEFT JOIN suppliers s ON s.id = i.supplier_id
            WHERE v.is_active = 1
        )
        SELECT group_id, group_name, variant_id, variant_label, unit_label,
               MAX(CASE WHEN rn = 1 THEN net_price END) AS latest_price,
               MAX(CASE WHEN rn = 1 THEN point_date END) AS latest_date,
               MAX(CASE WHEN rn = 1 THEN supplier_name END) AS latest_supplier,
               MAX(CASE WHEN rn = 2 THEN net_price END) AS previous_price,
               MAX(CASE WHEN rn = 2 THEN point_date END) AS previous_date
        FROM ranked
        WHERE rn <= 2
        GROUP BY group_id, group_name, variant_id, variant_label, unit_label
        ORDER BY group_name COLLATE NOCASE, variant_label COLLATE NOCASE
        '''
    )
    if q:
        nq = normalize_text(q)
        rows = [row for row in rows if nq in normalize_text(f"{row['group_name']} {row['variant_label']} {row['latest_supplier']}")]
    return render_template('prices.html', rows=rows, q=q, **base_context('prices', 'InventurManager – Preisvergleich'))


@app.route('/articles')
def articles():
    q = request.args.get('q', '').strip()
    group_id = request.args.get('group_id', '').strip()
    if group_id.isdigit():
        return redirect(url_for('article_detail', group_id=int(group_id)))
    if q:
        match = first_group_match(q)
        if match:
            return redirect(url_for('article_detail', group_id=match['id']))
        flash('Kein passender Artikel gefunden.', 'error')
    groups = query_all(
        '''
        SELECT g.id,
               g.name,
               COUNT(DISTINCT lower(trim(COALESCE(v.variant_label, '')))) AS variant_count,
               COUNT(DISTINCT i.id) AS invoice_count,
               MAX(i.invoice_date) AS last_invoice_date
        FROM article_groups g
        LEFT JOIN article_variants v ON v.group_id = g.id AND v.is_active = 1
        LEFT JOIN invoice_lines il ON il.variant_id = v.id
        LEFT JOIN invoices i ON i.id = il.invoice_id
        GROUP BY g.id, g.name
        ORDER BY g.name COLLATE NOCASE
        '''
    )
    return render_template(
        'articles.html',
        groups=groups,
        article_options=article_dropdown_options(),
        article_search_json=json.dumps(article_search_entries(), ensure_ascii=False),
        q=q,
        **base_context('articles', 'InventurManager – Artikel'),
    )
@app.route('/articles/new', methods=['GET', 'POST'])
def new_article():
    if request.method == 'POST':
        try:
            group_name = request.form.get('name', '').strip()
            group_id = ensure_group(group_name, '', '')
            labels = request.form.getlist('variant_label[]')
            created = 0
            for label in labels:
                label = label.strip()
                if not label:
                    continue
                ensure_variant(group_id, label, '')
                created += 1
            if created == 0:
                raise ValueError('Bitte mindestens ein Gebinde anlegen.')
            selected_supplier_id = request.form.get('supplier_id', '').strip()
            new_supplier_name = request.form.get('new_supplier_name', '').strip()
            supplier_id = None
            if new_supplier_name:
                supplier_id = ensure_supplier(new_supplier_name)
            elif selected_supplier_id:
                supplier_id = int(selected_supplier_id)
            if supplier_id:
                link_article_supplier(group_id, supplier_id)
            ensure_inventory_year(datetime.now().year)
            flash('Artikel wurde angelegt.', 'success')
            return redirect(url_for('article_detail', group_id=group_id))
        except Exception as exc:
            flash(f'Artikel konnte nicht angelegt werden: {exc}', 'error')
    return render_template(
        'article_form.html',
        mode='new',
        article=None,
        variants=None,
        supplier_options=supplier_dropdown_options(),
        variant_label_options=variant_label_options(),
        **base_context('articles', 'InventurManager – Neuer Artikel'),
    )
@app.route('/articles/<int:group_id>')
def article_detail(group_id):
    current_year = datetime.now().year
    ensure_inventory_year(current_year)
    article = query_one('SELECT * FROM article_groups WHERE id = ?', (group_id,))
    if not article:
        flash('Artikel wurde nicht gefunden.', 'error')
        return redirect(url_for('articles'))
    variants = query_all(
        '''
        SELECT v.id, v.variant_label, COALESCE(v.unit, '') AS unit, COALESCE(v.purchase_unit, v.variant_label) AS purchase_unit, COALESCE(v.stock_unit, v.variant_label) AS stock_unit, COALESCE(v.units_per_purchase,1) AS units_per_purchase, v.is_active,
               (SELECT COALESCE(il.purchase_price, il.net_price) FROM invoice_lines il JOIN invoices i ON i.id = il.invoice_id WHERE il.variant_id = v.id ORDER BY i.invoice_date DESC, il.id DESC LIMIT 1) AS latest_price,
               (SELECT i.invoice_date FROM invoice_lines il JOIN invoices i ON i.id = il.invoice_id WHERE il.variant_id = v.id ORDER BY i.invoice_date DESC, il.id DESC LIMIT 1) AS latest_date,
               (SELECT COALESCE(s.name, i.supplier) FROM invoice_lines il JOIN invoices i ON i.id = il.invoice_id LEFT JOIN suppliers s ON s.id = i.supplier_id WHERE il.variant_id = v.id ORDER BY i.invoice_date DESC, il.id DESC LIMIT 1) AS latest_supplier,
               (SELECT ic.closing_stock FROM inventory_counts ic WHERE ic.variant_id = v.id AND ic.year = ?) AS closing_stock,
               (SELECT ic.inventory_price FROM inventory_counts ic WHERE ic.variant_id = v.id AND ic.year = ?) AS inventory_price
        FROM article_variants v
        WHERE v.group_id = ?
        ORDER BY v.variant_label COLLATE NOCASE
        ''',
        (current_year, current_year, group_id),
    )
    linked_suppliers = get_article_suppliers(group_id)
    linked_supplier_ids = {row['id'] for row in linked_suppliers}
    available_suppliers = [row for row in supplier_options() if row['id'] not in linked_supplier_ids]
    variant_payload = []
    for variant in variants:
        variant = dict(variant)
        raw_points = price_points_for_variant(variant['id'])
        points = []
        prev_price = None
        comparable_prices = []
        latest_display_price = None
        latest_display_unit = preferred_invoice_display_label('', '', variant['variant_label'] or variant['stock_unit'] or variant['purchase_unit'])
        for point in raw_points:
            item = dict(point)
            display_payload = invoice_line_display_values(
                quantity=item.get('quantity'),
                purchase_quantity=item.get('purchase_quantity'),
                net_price=item.get('net_price'),
                purchase_price=item.get('purchase_price'),
                saved_variant_label=item.get('saved_variant_label', ''),
                purchase_unit_label=item.get('purchase_unit_label', ''),
                fallback_label=variant['variant_label'] or variant['stock_unit'] or variant['purchase_unit'],
                line_units_per_purchase=item.get('line_units_per_purchase'),
                import_mode=item.get('import_mode', ''),
                variant_units_per_purchase=variant.get('units_per_purchase'),
                variant_purchase_unit=variant.get('purchase_unit', ''),
                variant_stock_unit=variant.get('stock_unit', ''),
                source_type=item.get('source_type', ''),
            )
            display_price = display_payload['display_price']
            display_quantity = display_payload['display_quantity']
            display_unit = display_payload['display_label']
            item['display_price'] = display_price
            item['display_quantity'] = display_quantity
            item['display_unit'] = display_unit
            item['display_purchase_text'] = display_payload['display_text']
            item['chart_price'] = display_price if display_price is not None else item.get('net_price')
            current_price = display_price
            item['change_from_previous'] = None
            if item.get('source_type') != 'Inventur-Startwert' and prev_price not in (None, 0, '') and current_price not in (None, ''):
                item['change_from_previous'] = ((current_price - prev_price) / prev_price) * 100
            points.append(item)
            if item.get('source_type') != 'Inventur-Startwert' and current_price not in (None, ''):
                comparable_prices.append(current_price)
                prev_price = current_price
                latest_display_price = current_price
                latest_display_unit = display_unit or latest_display_unit
        change_percent = None
        if len(comparable_prices) >= 2 and comparable_prices[0] not in (None, 0, ''):
            change_percent = ((comparable_prices[-1] - comparable_prices[0]) / comparable_prices[0]) * 100
        variant_payload.append(
            {
                'variant': variant,
                'points': points,
                'svg_chart': build_svg_chart(points),
                'change_percent': change_percent,
                'latest_display_price': latest_display_price if latest_display_price is not None else variant['latest_price'],
                'latest_display_unit': latest_display_unit,
            }
        )
    return render_template(
        'article_detail.html',
        article=article,
        variants=variants,
        linked_suppliers=linked_suppliers,
        available_suppliers=available_suppliers,
        variant_payload=variant_payload,
        variant_label_options=variant_label_options(),
        **base_context('articles', f'InventurManager – {article["name"]}'),
    )
@app.post('/articles/<int:group_id>/update')
def update_article(group_id):
    article = query_one('SELECT * FROM article_groups WHERE id = ?', (group_id,))
    if not article:
        flash('Artikel wurde nicht gefunden.', 'error')
        return redirect(url_for('articles'))
    name = request.form.get('name', '').strip()
    if not name:
        flash('Bitte einen Artikelnamen angeben.', 'error')
        return redirect(url_for('article_detail', group_id=group_id))
    execute(
        'UPDATE article_groups SET name = ?, updated_at = ? WHERE id = ?',
        (name, now_iso(), group_id),
    )
    flash('Artikel wurde aktualisiert.', 'success')
    return redirect(url_for('article_detail', group_id=group_id))
@app.post('/articles/<int:group_id>/delete')
def delete_article(group_id):
    article = query_one('SELECT * FROM article_groups WHERE id = ?', (group_id,))
    if not article:
        flash('Artikel wurde nicht gefunden.', 'error')
        return redirect(url_for('articles'))
    variant_ids = [row['id'] for row in query_all('SELECT id FROM article_variants WHERE group_id = ?', (group_id,))]
    db = get_db()
    cur = db.cursor()
    for variant_id in variant_ids:
        cur.execute('DELETE FROM inventory_counts WHERE variant_id = ?', (variant_id,))
        cur.execute('DELETE FROM invoice_lines WHERE variant_id = ?', (variant_id,))
    cur.execute('DELETE FROM article_suppliers WHERE group_id = ?', (group_id,))
    cur.execute('DELETE FROM article_variants WHERE group_id = ?', (group_id,))
    cur.execute('DELETE FROM article_groups WHERE id = ?', (group_id,))
    db.commit()
    log_event(f'Artikel gelöscht: {article["name"]}')
    flash('Artikel wurde gelöscht.', 'success')
    return redirect(url_for('articles'))
@app.post('/articles/<int:group_id>/suppliers/add')
def add_article_supplier(group_id):
    article = query_one('SELECT id, name FROM article_groups WHERE id = ?', (group_id,))
    if not article:
        flash('Artikel wurde nicht gefunden.', 'error')
        return redirect(url_for('articles'))
    selected_supplier_id = request.form.get('supplier_id', '').strip()
    new_supplier_name = request.form.get('new_supplier_name', '').strip()
    try:
        if new_supplier_name:
            supplier_id = ensure_supplier(new_supplier_name)
        elif selected_supplier_id:
            supplier_id = int(selected_supplier_id)
        else:
            raise ValueError('Bitte einen Lieferanten auswählen oder neu anlegen.')
        link_article_supplier(group_id, supplier_id)
        flash('Lieferant wurde dem Artikel zugewiesen.', 'success')
    except Exception as exc:
        flash(f'Lieferant konnte nicht zugewiesen werden: {exc}', 'error')
    return redirect(url_for('article_detail', group_id=group_id))
@app.post('/articles/<int:group_id>/suppliers/<int:supplier_id>/remove')
def remove_article_supplier(group_id, supplier_id):
    unlink_article_supplier(group_id, supplier_id)
    flash('Lieferant wurde vom Artikel entfernt.', 'success')
    return redirect(url_for('article_detail', group_id=group_id))
@app.post('/articles/<int:group_id>/variants/add')
def add_article_variant(group_id):
    article = query_one('SELECT id, name FROM article_groups WHERE id = ?', (group_id,))
    if not article:
        flash('Artikel wurde nicht gefunden.', 'error')
        return redirect(url_for('articles'))
    selected_label = request.form.get('variant_label_existing', '').strip()
    new_label = request.form.get('variant_label_new', '').strip()
    label = new_label or selected_label
    try:
        ensure_variant(group_id, label, '')
        ensure_inventory_year(datetime.now().year)
        flash('Gebinde wurde ergänzt.', 'success')
    except Exception as exc:
        flash(f'Gebinde konnte nicht ergänzt werden: {exc}', 'error')
    return redirect(url_for('article_detail', group_id=group_id))
@app.route('/variants/new', methods=['GET'])
def new_variant():
    return render_template(
        'variant_labels.html',
        labels=variant_label_catalog(),
        **base_context('articles', 'InventurManager – Gebinde verwalten'),
    )

@app.route('/variants/labels/edit', methods=['GET', 'POST'])
def edit_variant_label():
    label = (request.values.get('label') or '').strip()
    if not label:
        flash('Bitte ein Gebinde auswählen.', 'error')
        return redirect(url_for('new_variant'))
    if request.method == 'POST':
        action = (request.form.get('action') or 'rename').strip().lower()
        if action == 'delete':
            rows = query_all('SELECT id FROM article_variants WHERE lower(trim(variant_label)) = lower(trim(?))', (label,))
            for row in rows:
                execute('DELETE FROM inventory_counts WHERE variant_id = ?', (row['id'],))
                execute('DELETE FROM invoice_lines WHERE variant_id = ?', (row['id'],))
                execute('DELETE FROM article_variants WHERE id = ?', (row['id'],))
            execute(
                'UPDATE invoice_lines SET purchase_unit_label = "" WHERE lower(trim(COALESCE(purchase_unit_label, ""))) = lower(trim(?))',
                (label,),
            )
            flash('Gebinde wurde global gelöscht.', 'success')
            return redirect(url_for('new_variant'))
        new_label = (request.form.get('new_label') or '').strip()
        if not new_label:
            flash('Bitte ein neues Gebinde angeben.', 'error')
            return redirect(url_for('edit_variant_label', label=label))
        rows = query_all('SELECT id, group_id, variant_label, purchase_unit, stock_unit FROM article_variants WHERE lower(trim(variant_label)) = lower(trim(?))', (label,))
        for row in rows:
            duplicate = query_one('SELECT id FROM article_variants WHERE group_id = ? AND lower(trim(variant_label)) = lower(trim(?)) AND id != ?', (row['group_id'], new_label, row['id']))
            if duplicate:
                execute('UPDATE article_variants SET purchase_unit = ?, stock_unit = ?, updated_at = ? WHERE id = ?', (new_label, new_label, now_iso(), duplicate['id']))
                merge_variants(row['id'], duplicate['id'])
                execute('UPDATE invoice_lines SET purchase_unit_label = ?, saved_variant_label = ? WHERE variant_id = ?', (new_label, new_label, duplicate['id']))
                recalculate_variant_invoice_lines(duplicate['id'])
            else:
                execute(
                    'UPDATE article_variants SET variant_label = ?, purchase_unit = ?, stock_unit = ?, updated_at = ? WHERE id = ?',
                    (new_label, new_label, new_label, now_iso(), row['id']),
                )
                execute('UPDATE invoice_lines SET purchase_unit_label = ?, saved_variant_label = ? WHERE variant_id = ?', (new_label, new_label, row['id']))
                recalculate_variant_invoice_lines(row['id'])
        execute(
            'UPDATE invoice_lines SET purchase_unit_label = ?, saved_variant_label = ? WHERE lower(trim(COALESCE(purchase_unit_label, ""))) = lower(trim(?))',
            (new_label, new_label, label),
        )
        flash('Gebinde wurde global aktualisiert.', 'success')
        return redirect(url_for('new_variant'))
    label_rows = query_all(
        '''
        SELECT v.id, g.id AS group_id, g.name AS group_name, v.variant_label
        FROM article_variants v
        JOIN article_groups g ON g.id = v.group_id
        WHERE lower(trim(v.variant_label)) = lower(trim(?))
        ORDER BY g.name COLLATE NOCASE
        ''',
        (label,),
    )
    related_invoice_rows = query_all(
        '''
        SELECT il.id,
               i.invoice_date,
               COALESCE(s.name, i.supplier, 'Ohne Lieferant') AS supplier_name,
               COALESCE(il.purchase_unit_label, '') AS purchase_unit_label,
               g.id AS group_id,
               g.name AS group_name,
               v.variant_label
        FROM invoice_lines il
        LEFT JOIN invoices i ON i.id = il.invoice_id
        LEFT JOIN suppliers s ON s.id = i.supplier_id
        LEFT JOIN article_variants v ON v.id = il.variant_id
        LEFT JOIN article_groups g ON g.id = v.group_id
        ORDER BY i.invoice_date DESC, il.id DESC
        '''
    )
    label_norm = normalize_text(label)
    orphan_rows = []
    for row in related_invoice_rows:
        raw_label = (row['purchase_unit_label'] or '').strip()
        parsed_purchase_label, parsed_stock_unit, _ = parse_purchase_unit_label(raw_label)
        candidates = [raw_label, parsed_purchase_label, parsed_stock_unit, row['variant_label'] or '']
        if any(normalize_text(cand) == label_norm for cand in candidates if (cand or '').strip()):
            linked_to_same_label = row['group_id'] is not None and normalize_text(row['variant_label'] or '') == label_norm
            if not linked_to_same_label:
                orphan_rows.append({
                    'id': row['id'],
                    'invoice_date': row['invoice_date'],
                    'supplier_name': row['supplier_name'],
                    'purchase_unit_label': raw_label or label,
                })
    return render_template(
        'variant_label_edit.html',
        label=label,
        label_rows=label_rows,
        orphan_rows=orphan_rows,
        **base_context('articles', f'InventurManager – Gebinde {label}'),
    )
def merge_variants(source_variant_id, target_variant_id):
    if source_variant_id == target_variant_id:
        return target_variant_id
    src = query_one('SELECT id, group_id, variant_label, purchase_unit, stock_unit, units_per_purchase FROM article_variants WHERE id = ?', (source_variant_id,))
    tgt = query_one('SELECT id, group_id, variant_label, purchase_unit, stock_unit, units_per_purchase FROM article_variants WHERE id = ?', (target_variant_id,))
    if not src or not tgt:
        raise ValueError('Variante wurde nicht gefunden.')

    src_counts = query_all('SELECT * FROM inventory_counts WHERE variant_id = ?', (source_variant_id,))
    for row in src_counts:
        existing = query_one('SELECT * FROM inventory_counts WHERE variant_id = ? AND year = ?', (target_variant_id, row['year']))
        if existing:
            opening = (float(existing['opening_stock']) if existing['opening_stock'] not in (None, '') else 0.0) + (float(row['opening_stock']) if row['opening_stock'] not in (None, '') else 0.0)
            closing_existing = float(existing['closing_stock']) if existing['closing_stock'] not in (None, '') else None
            closing_src = float(row['closing_stock']) if row['closing_stock'] not in (None, '') else None
            if closing_existing is None and closing_src is None:
                closing = None
            else:
                closing = (closing_existing or 0.0) + (closing_src or 0.0)
            inventory_price = existing['inventory_price'] if existing['inventory_price'] not in (None, '') else row['inventory_price']
            execute('UPDATE inventory_counts SET opening_stock = ?, closing_stock = ?, inventory_price = ?, updated_at = ? WHERE id = ?', (opening, closing, inventory_price, now_iso(), existing['id']))
            execute('DELETE FROM inventory_counts WHERE id = ?', (row['id'],))
        else:
            execute('UPDATE inventory_counts SET variant_id = ?, updated_at = ? WHERE id = ?', (target_variant_id, now_iso(), row['id']))

    execute('UPDATE invoice_lines SET variant_id = ? WHERE variant_id = ?', (target_variant_id, source_variant_id))
    execute('DELETE FROM article_variants WHERE id = ?', (source_variant_id,))

    # keep the target settings the user just chose, but ensure invoice lines are recalculated with them
    target = query_one('SELECT purchase_unit, variant_label FROM article_variants WHERE id = ?', (target_variant_id,))
    if target and target['purchase_unit']:
        execute(
            'UPDATE invoice_lines SET purchase_unit_label = ?, saved_variant_label = ? WHERE variant_id = ?',
            (target['purchase_unit'], target['variant_label'] or target['purchase_unit'], target_variant_id),
        )
    recalculate_variant_invoice_lines(target_variant_id)
    return target_variant_id


@app.route('/variants/<int:variant_id>', methods=['GET', 'POST'])
def variant_detail(variant_id):
    variant = query_one(
        '''
        SELECT v.*, g.name AS group_name, g.id AS group_id
        FROM article_variants v
        JOIN article_groups g ON g.id = v.group_id
        WHERE v.id = ?
        ''',
        (variant_id,),
    )
    if not variant:
        flash('Variante wurde nicht gefunden.', 'error')
        return redirect(url_for('new_variant'))
    return_group_id = _int_or_none(request.values.get('return_group_id'))
    if request.method == 'POST':
        try:
            selected_label = request.form.get('variant_label_existing', '').strip()
            new_label = request.form.get('variant_label_new', '').strip()
            label = new_label or selected_label
            group_id = int(request.form.get('group_id', str(variant['group_id'])))
            purchase_unit = label
            stock_unit = label
            units_per_purchase = request.form.get('units_per_purchase', '').strip() or '1'
            try:
                upp = float(units_per_purchase.replace(',', '.'))
            except ValueError:
                raise ValueError('Umrechnungsfaktor muss eine Zahl sein.')
            if not label:
                raise ValueError('Bitte ein Gebinde angeben.')
            if upp <= 0:
                raise ValueError('Umrechnungsfaktor muss größer als 0 sein.')
            duplicate = query_one(
                'SELECT id, purchase_unit, stock_unit, units_per_purchase FROM article_variants WHERE group_id = ? AND lower(variant_label) = lower(?) AND id != ?',
                (group_id, label, variant_id),
            )
            if duplicate:
                current_purchase = (variant['purchase_unit'] or variant['variant_label'] or '').strip()
                current_stock = (variant['stock_unit'] or variant['variant_label'] or '').strip()
                current_upp = float(variant['units_per_purchase'] or 1)
                purchase_changed = purchase_unit.strip() != current_purchase
                stock_changed = stock_unit.strip() != current_stock
                upp_changed = abs(upp - current_upp) > 1e-9
                target_purchase = purchase_unit if purchase_changed else (duplicate['purchase_unit'] or label)
                target_stock = stock_unit if stock_changed else (duplicate['stock_unit'] or label)
                target_upp = upp if upp_changed else float(duplicate['units_per_purchase'] or 1)
                execute(
                    'UPDATE article_variants SET purchase_unit = ?, stock_unit = ?, units_per_purchase = ?, updated_at = ? WHERE id = ?',
                    (target_purchase, target_stock, target_upp, now_iso(), duplicate['id']),
                )
                merged_id = merge_variants(variant_id, duplicate['id'])
                flash('Variante wurde mit einer bestehenden Variante zusammengeführt.', 'success')
                return variant_return_target(return_group_id, merged_id)
            execute(
                'UPDATE article_variants SET group_id = ?, variant_label = ?, purchase_unit = ?, stock_unit = ?, units_per_purchase = ?, updated_at = ? WHERE id = ?',
                (group_id, label, purchase_unit, stock_unit, upp, now_iso(), variant_id),
            )
            execute(
                'UPDATE invoice_lines SET purchase_unit_label = ?, saved_variant_label = ? WHERE variant_id = ?',
                (purchase_unit, label, variant_id),
            )
            recalculate_variant_invoice_lines(variant_id)
            flash('Variante wurde aktualisiert.', 'success')
            return variant_return_target(return_group_id, variant_id)
        except Exception as exc:
            flash(f'Variante konnte nicht aktualisiert werden: {exc}', 'error')
    points = price_points_for_variant(variant_id)
    change_percent = None
    if len(points) >= 2 and points[0]['net_price']:
        change_percent = ((points[-1]['net_price'] - points[0]['net_price']) / points[0]['net_price']) * 100
    return render_template(
        'variant_form.html',
        mode='edit',
        variant=variant,
        points=points,
        svg_chart=build_svg_chart(points),
        change_percent=change_percent,
        article_options=article_dropdown_options(),
        variant_label_options=variant_label_options(),
        return_group_id=return_group_id,
        **base_context('articles', f'InventurManager – {variant["group_name"]} – {variant["variant_label"]}'),
    )
@app.get('/variants/open')
def open_variant_redirect():
    variant_id = request.args.get('variant_id', '').strip()
    return_group_id = request.args.get('return_group_id', '').strip()
    if variant_id.isdigit():
        if return_group_id.isdigit():
            return redirect(url_for('variant_detail', variant_id=int(variant_id), return_group_id=int(return_group_id)))
        return redirect(url_for('variant_detail', variant_id=int(variant_id)))
    flash('Bitte eine Variante auswählen.', 'error')
    return redirect(url_for('new_variant'))

@app.post('/variants/<int:variant_id>/delete')
def delete_variant(variant_id):
    return_group_id = _int_or_none(request.values.get('return_group_id'))
    variant = query_one(
        'SELECT v.id, v.variant_label, g.id AS group_id FROM article_variants v JOIN article_groups g ON g.id = v.group_id WHERE v.id = ?',
        (variant_id,),
    )
    if not variant:
        flash('Variante wurde nicht gefunden.', 'error')
        return redirect(url_for('new_variant'))
    db = get_db()
    cur = db.cursor()
    cur.execute('DELETE FROM inventory_counts WHERE variant_id = ?', (variant_id,))
    cur.execute('DELETE FROM invoice_lines WHERE variant_id = ?', (variant_id,))
    cur.execute('DELETE FROM article_variants WHERE id = ?', (variant_id,))
    db.commit()
    log_event(f'Variante gelöscht: {variant["variant_label"]}')
    flash('Variante wurde gelöscht.', 'success')
    return variant_return_target(return_group_id, None)
@app.route('/suppliers')
def suppliers():
    q = request.args.get('q', '').strip()
    supplier_id = request.args.get('supplier_id', '').strip()
    if supplier_id.isdigit():
        return redirect(url_for('supplier_detail', supplier_id=int(supplier_id)))
    if q:
        match = first_supplier_match(q)
        if match:
            return redirect(url_for('supplier_detail', supplier_id=match['id']))
        flash('Kein passender Lieferant gefunden.', 'error')
    suppliers_list = query_all(
        '''
        SELECT s.id, s.name,
               COUNT(DISTINCT i.id) AS invoice_count,
               COUNT(DISTINCT il.variant_id) AS variant_count,
               MAX(i.invoice_date) AS last_invoice_date
        FROM suppliers s
        LEFT JOIN invoices i ON i.supplier_id = s.id
        LEFT JOIN invoice_lines il ON il.invoice_id = i.id
        GROUP BY s.id, s.name
        ORDER BY s.name COLLATE NOCASE
        '''
    )
    return render_template(
        'suppliers.html',
        suppliers=suppliers_list,
        supplier_options=supplier_dropdown_options(),
        q=q,
        supplier_overview_open=True,
        **base_context('suppliers', 'InventurManager – Lieferanten'),
    )

@app.route('/suppliers/new', methods=['GET', 'POST'])
def new_supplier():
    if request.method == 'POST':
        try:
            supplier_id = ensure_supplier(request.form.get('name', ''))
            flash('Lieferant wurde angelegt.', 'success')
            return redirect(url_for('supplier_detail', supplier_id=supplier_id))
        except Exception as exc:
            flash(f'Lieferant konnte nicht angelegt werden: {exc}', 'error')
    return render_template('supplier_form.html', mode='new', supplier=None, article_links=None, **base_context('suppliers', 'InventurManager – Neuer Lieferant'))
@app.route('/suppliers/<int:supplier_id>', methods=['GET', 'POST'])
def supplier_detail(supplier_id):
    supplier = query_one('SELECT * FROM suppliers WHERE id = ?', (supplier_id,))
    if not supplier:
        flash('Lieferant wurde nicht gefunden.', 'error')
        return redirect(url_for('suppliers'))
    selected_year = request.args.get('year', '').strip()
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            if not name:
                raise ValueError('Bitte einen Lieferantennamen angeben.')
            execute(
                'UPDATE suppliers SET name = ?, updated_at = ? WHERE id = ?',
                (name, now_iso(), supplier_id),
            )
            execute('UPDATE invoices SET supplier = ? WHERE supplier_id = ?', (name, supplier_id))
            flash('Lieferant wurde aktualisiert.', 'success')
            return redirect(url_for('supplier_detail', supplier_id=supplier_id, year=selected_year) if selected_year else url_for('supplier_detail', supplier_id=supplier_id))
        except Exception as exc:
            flash(f'Lieferant konnte nicht aktualisiert werden: {exc}', 'error')
            supplier = query_one('SELECT * FROM suppliers WHERE id = ?', (supplier_id,))
    article_links = query_all(
        '''
        SELECT g.id AS group_id, g.name AS group_name, MAX(i.invoice_date) AS latest_date
        FROM article_groups g
        JOIN article_suppliers aps ON aps.group_id = g.id
        LEFT JOIN article_variants v ON v.group_id = g.id
        LEFT JOIN invoice_lines il ON il.variant_id = v.id
        LEFT JOIN invoices i ON i.id = il.invoice_id AND i.supplier_id = ?
        WHERE aps.supplier_id = ?
        GROUP BY g.id, g.name
        ORDER BY g.name COLLATE NOCASE
        ''',
        (supplier_id, supplier_id),
    )
    invoice_sql = '''
        SELECT i.id, i.invoice_date, COUNT(il.id) AS line_count
        FROM invoices i
        LEFT JOIN invoice_lines il ON il.invoice_id = i.id
        WHERE i.supplier_id = ?
    '''
    invoice_params = [supplier_id]
    if selected_year.isdigit():
        invoice_sql += ' AND substr(i.invoice_date, 1, 4) = ?'
        invoice_params.append(selected_year)
    invoice_sql += '''
        GROUP BY i.id
        ORDER BY i.invoice_date DESC, i.id DESC
        LIMIT 200
        '''
    invoice_rows = query_all(invoice_sql, tuple(invoice_params))
    return render_template(
        'supplier_form.html',
        mode='edit',
        supplier=supplier,
        article_links=article_links,
        invoice_rows=invoice_rows,
        supplier_invoice_years=invoice_year_options(supplier_id),
        selected_supplier_invoice_year=selected_year,
        **base_context('suppliers', f'InventurManager – {supplier["name"]}'),
    )

@app.post('/suppliers/<int:supplier_id>/delete')
def delete_supplier(supplier_id):
    supplier = query_one('SELECT * FROM suppliers WHERE id = ?', (supplier_id,))
    if not supplier:
        flash('Lieferant wurde nicht gefunden.', 'error')
        return redirect(url_for('suppliers'))
    execute('UPDATE invoices SET supplier_id = NULL WHERE supplier_id = ?', (supplier_id,))
    execute('DELETE FROM article_suppliers WHERE supplier_id = ?', (supplier_id,))
    execute('DELETE FROM suppliers WHERE id = ?', (supplier_id,))
    log_event(f'Lieferant gelöscht: {supplier["name"]}')
    flash('Lieferant wurde gelöscht.', 'success')
    return redirect(url_for('suppliers'))
@app.route('/invoice/new')
def new_invoice():
    view = request.args.get('view', 'list').strip().lower() or 'list'
    selected_year = request.args.get('year', '').strip()
    flags = invoice_view_flags(view=view)
    context = invoice_page_context(invoice_year=selected_year, invoice_view=view, **flags)
    return render_template(
        'invoice.html',
        mode='new',
        form_action=url_for('create_invoice'),
        invoice=None,
        **context,
        **base_context('invoices', 'InventurManager – Rechnungen'),
    )

@app.post('/invoice/parse-text')
def parse_invoice_text():
    supplier_search = request.form.get('supplier_search', '').strip()
    selected_supplier_name = request.form.get('supplier_select_name', '').strip()
    if not supplier_search and selected_supplier_name:
        supplier_search = selected_supplier_name
    invoice_date_input = request.form.get('invoice_date', '').strip()
    raw_invoice_text = request.form.get('invoice_text', '').strip()
    if not raw_invoice_text:
        flash('Bitte Rechnungstext einfügen.', 'error')
        return redirect(url_for('new_invoice'))
    detected_date, detected_supplier, parsed_rows = parse_invoice_text_block(raw_invoice_text)
    if not supplier_search and detected_supplier:
        supplier_search = detected_supplier
    if not parsed_rows:
        flash('Es konnten noch keine Positionen aus dem Text gelesen werden. Bitte Format mit Artikel | Gebinde | Menge | Nettopreis verwenden.', 'error')
        parsed_rows = [default_invoice_row(), default_invoice_row()]
    else:
        flash('Text wurde übernommen. Bitte alles vor dem Speichern prüfen und bei Bedarf korrigieren.', 'success')
    flags = invoice_view_flags(parsed=True)
    return render_template(
        'invoice.html',
        mode='new',
        form_action=url_for('create_invoice'),
        invoice=None,
        recent_invoices=invoice_page_context()['recent_invoices'],
        raw_invoice_text=raw_invoice_text,
        invoice_view='parsed',
        **flags,
        **invoice_form_common_data(
            detected_date if detected_date and (not invoice_date_input or invoice_date_input == date.today().isoformat()) else (invoice_date_input or detected_date or date.today().isoformat()),
            supplier_search,
            parsed_rows,
        ),
        **base_context('invoices', 'InventurManager – Rechnungen'),
    )
@app.post('/invoice/create')
def create_invoice():
    return save_invoice_from_request()

def save_invoice_from_request(invoice_id=None):
    invoice_date = request.form.get('invoice_date', '').strip()
    supplier_search = request.form.get('supplier_search', '').strip()
    selected_supplier_name = request.form.get('supplier_select_name', '').strip()
    if not supplier_search and selected_supplier_name:
        supplier_search = selected_supplier_name
    variant_searches = request.form.getlist('variant_search[]')
    article_names = request.form.getlist('article_name[]')
    variant_labels = request.form.getlist('variant_label[]')
    purchase_unit_labels = request.form.getlist('purchase_unit_label[]')
    units_per_purchase_values = request.form.getlist('units_per_purchase[]')
    quantities = request.form.getlist('quantity[]')
    net_prices = request.form.getlist('net_price[]')
    import_modes = request.form.getlist('import_mode[]')
    original_article_names = request.form.getlist('original_article_name[]')

    draft_rows = []
    max_len = max(len(variant_searches), len(article_names), len(variant_labels), len(purchase_unit_labels), len(units_per_purchase_values), len(quantities), len(net_prices), len(import_modes))
    for idx in range(max_len):
        draft_rows.append({
            'variant_search': (variant_searches[idx] if idx < len(variant_searches) else '').strip(),
            'article_name': (article_names[idx] if idx < len(article_names) else '').strip(),
            'variant_label': (variant_labels[idx] if idx < len(variant_labels) else '').strip(),
            'purchase_unit_label': (purchase_unit_labels[idx] if idx < len(purchase_unit_labels) else '').strip(),
            'units_per_purchase': (units_per_purchase_values[idx] if idx < len(units_per_purchase_values) else '1').strip() or '1',
            'quantity': (quantities[idx] if idx < len(quantities) else '').strip(),
            'net_price': (net_prices[idx] if idx < len(net_prices) else '').strip(),
            'matched_existing': False,
            'import_mode': (import_modes[idx] if idx < len(import_modes) else 'pack').strip() or 'pack',
            'original_article_name': (original_article_names[idx] if idx < len(original_article_names) else '').strip(),
        })

    def render_invoice_error(message):
        flash(message, 'error')
        rows_for_view = draft_rows or [default_invoice_row(), default_invoice_row()]
        invoice = query_one('SELECT * FROM invoices WHERE id = ?', (invoice_id,)) if invoice_id else None
        flags = invoice_view_flags(parsed=not bool(invoice_id), edit=bool(invoice_id))
        return render_template(
            'invoice.html',
            mode='edit' if invoice_id else 'new',
            form_action=url_for('update_invoice', invoice_id=invoice_id) if invoice_id else url_for('create_invoice'),
            invoice=invoice,
            recent_invoices=invoice_page_context()['recent_invoices'] if not invoice_id else [],
            invoice_years=invoice_year_options() if not invoice_id else [],
            selected_invoice_year='',
            raw_invoice_text='',
            invoice_view='parsed' if not invoice_id else 'edit',
            **flags,
            **invoice_form_common_data(invoice_date or date.today().isoformat(), supplier_search, rows_for_view),
            **base_context('invoices', 'InventurManager – Rechnung bearbeiten' if invoice_id else 'InventurManager – Rechnungen'),
        )

    if not invoice_date:
        return render_invoice_error('Bitte ein Rechnungsdatum angeben.')

    supplier_id = None
    supplier_name = None
    if supplier_search:
        supplier_id, supplier_name = resolve_supplier_input(supplier_search)

    rows = []
    for row in draft_rows:
        variant_search = row['variant_search']
        article_name = row['article_name']
        variant_label = row['variant_label']
        purchase_unit_label = row.get('purchase_unit_label', '').strip()
        units_per_purchase_raw = row.get('units_per_purchase', '1').strip() or '1'
        import_mode = (row.get('import_mode') or 'pack').strip() or 'pack'
        qty_val = row['quantity']
        price_val = row['net_price']
        purchase_unit_label = synthesize_purchase_unit_label(purchase_unit_label, units_per_purchase_raw, variant_label, import_mode)
        parsed_purchase_label, parsed_stock_unit, parsed_units = parse_purchase_unit_label(purchase_unit_label)
        purchase_unit_label = parsed_purchase_label or purchase_unit_label
        if import_mode == 'stock':
            if (not variant_label or normalize_text(variant_label) == normalize_text(parsed_purchase_label)) and parsed_stock_unit:
                variant_label = parsed_stock_unit
            current_units_guess = parse_number(units_per_purchase_raw) or 1
            parsed_units_val = parse_number(parsed_units) or 1
            if (not units_per_purchase_raw or abs(current_units_guess - 1.0) < 1e-9) and parsed_units_val > 1:
                units_per_purchase_raw = qty(parsed_units_val)
        if not any([variant_search, article_name, variant_label, purchase_unit_label, units_per_purchase_raw, qty_val, price_val]):
            continue
        if not price_val:
            return render_invoice_error('Bitte bei jeder Position einen Nettopreis angeben.')
        resolved = resolve_existing_variant(variant_search, article_name, variant_label)
        group_match = find_group_by_name(article_name or variant_search or row.get('original_article_name'))
        if not resolved and group_match:
            storage_payload = article_storage_payload(group_match['name'], variant_search, variant_label)
            suggested_label = suggest_existing_variant_label(group_match['id'], variant_label, purchase_unit_label)
            variant_label_norm = normalize_text(variant_label or '')
            target_label = ''
            if suggested_label and variant_label_norm in {'', 'stueck', 'stück', normalize_text(suggested_label)}:
                target_label = suggested_label
            elif len(storage_payload.get('labels', [])) == 1 and variant_label_norm in {'', 'stueck', 'stück'}:
                target_label = storage_payload['labels'][0]
            if target_label:
                resolved = resolve_existing_variant('', group_match['name'], target_label)
        if resolved:
            variant_id = resolved['id']
            row['matched_existing'] = True
            row['variant_search'] = resolved['display_name']
            row['article_name'] = resolved['group_name']
            row['variant_label'] = resolved['variant_label']
        else:
            if not article_name or not variant_label:
                return render_invoice_error('Bitte je Position entweder einen vorhandenen Artikel wählen oder Artikel und Gebinde angeben.')
            if group_match:
                group_id = group_match['id']
                row['article_name'] = group_match['name']
            else:
                group_id = ensure_group(article_name, '', '')
            desired_purchase_unit = variant_label
            desired_stock_unit = variant_label
            effective_units = units_per_purchase_raw
            if import_mode == 'pack':
                desired_purchase_unit = variant_label
                desired_stock_unit = variant_label
                effective_units = '1'
            else:
                desired_purchase_unit = purchase_unit_label or variant_label
                desired_stock_unit = variant_label
            variant_id = ensure_variant(group_id, variant_label, '', desired_purchase_unit, desired_stock_unit, effective_units)
        final_group_row = query_one('SELECT group_id FROM article_variants WHERE id = ?', (variant_id,))
        if final_group_row:
            original_name = (row.get('original_article_name') or '').strip()
            final_group_name_row = query_one('SELECT name FROM article_groups WHERE id = ?', (final_group_row['group_id'],))
            if original_name and final_group_name_row and normalize_text(original_name) != normalize_text(final_group_name_row['name']):
                upsert_article_alias(original_name, final_group_row['group_id'])
        try:
            purchase_quantity_val = float(qty_val.replace(',', '.')) if qty_val else None
            purchase_price_val = float(price_val.replace(',', '.'))
            units_per_purchase_val = float(units_per_purchase_raw.replace(',', '.')) if units_per_purchase_raw else 1.0
        except ValueError:
            return render_invoice_error('Bitte Menge, Einheiten je Einkaufsgebinde und Nettopreis nur als Zahlen eingeben.')
        if units_per_purchase_val <= 0:
            units_per_purchase_val = 1.0
        variant_row = query_one('SELECT id, purchase_unit, stock_unit, units_per_purchase FROM article_variants WHERE id = ?', (variant_id,))
        if import_mode == 'pack':
            effective_units = 1.0
            desired_purchase_unit = purchase_unit_label or variant_row['purchase_unit'] or variant_row['stock_unit'] or variant_label
        else:
            effective_units = units_per_purchase_val
            desired_purchase_unit = purchase_unit_label or variant_row['purchase_unit'] or variant_row['stock_unit'] or variant_label
        if effective_units <= 0:
            effective_units = 1.0
        normalized_quantity = purchase_quantity_val * effective_units if purchase_quantity_val is not None else None
        normalized_price = purchase_price_val / effective_units
        purchase_unit_label = desired_purchase_unit or variant_row['purchase_unit'] or variant_row['stock_unit'] or variant_label or ''
        row['matched_existing'] = bool(resolved)
        if resolved:
            row['match_status_text'] = 'Bekannter Artikel gefunden'
            row['match_status_class'] = 'ok'
        elif group_match:
            row['match_status_text'] = 'Bekannter Artikel gefunden · neue Variante wird angelegt'
            row['match_status_class'] = 'ok'
        else:
            row['match_status_text'] = 'Neuer Artikel wird angelegt'
            row['match_status_class'] = 'warn'
        rows.append((variant_id, normalized_quantity, normalized_price, purchase_quantity_val, purchase_price_val, purchase_unit_label, variant_label or desired_purchase_unit or '', effective_units, import_mode, None))

    if not rows:
        return render_invoice_error('Bitte mindestens eine Rechnungsposition erfassen.')

    if invoice_id:
        execute(
            'UPDATE invoices SET invoice_date = ?, supplier = ?, supplier_id = ? WHERE id = ?',
            (invoice_date, supplier_name, supplier_id, invoice_id),
        )
        execute('DELETE FROM invoice_lines WHERE invoice_id = ?', (invoice_id,))
    else:
        cur = execute(
            'INSERT INTO invoices (invoice_date, invoice_number, supplier, supplier_id, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            (invoice_date, None, supplier_name, supplier_id, None, now_iso()),
        )
        invoice_id = cur.lastrowid

    execute(
        'INSERT INTO invoice_lines (invoice_id, variant_id, quantity, net_price, purchase_quantity, purchase_price, purchase_unit_label, saved_variant_label, line_units_per_purchase, import_mode, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [(invoice_id, variant_id, quantity, net_price, purchase_quantity, purchase_price, purchase_unit_label, saved_variant_label, line_units_per_purchase, import_mode, note) for variant_id, quantity, net_price, purchase_quantity, purchase_price, purchase_unit_label, saved_variant_label, line_units_per_purchase, import_mode, note in rows],
        many=True,
    )
    if supplier_id:
        for variant_id, *_ in rows:
            group_row = query_one('SELECT group_id FROM article_variants WHERE id = ?', (variant_id,))
            if group_row:
                link_article_supplier(group_row['group_id'], supplier_id)
    invoice_year = date.fromisoformat(invoice_date).year
    ensure_inventory_year(invoice_year)
    ensure_inventory_year(invoice_year + 1)
    log_event(f'Rechnung gespeichert: {invoice_id} mit {len(rows)} Positionen.')
    flash('Rechnung wurde gespeichert.' if not request.endpoint == 'update_invoice' else 'Rechnung wurde aktualisiert.', 'success')
    return redirect(url_for('invoice_detail', invoice_id=invoice_id))

@app.route('/invoice/<int:invoice_id>')
def invoice_detail(invoice_id):
    invoice = query_one('SELECT i.*, COALESCE(s.name, i.supplier) AS supplier_name FROM invoices i LEFT JOIN suppliers s ON s.id = i.supplier_id WHERE i.id = ?', (invoice_id,))
    if not invoice:
        flash('Rechnung wurde nicht gefunden.', 'error')
        return redirect(url_for('new_invoice'))
    flags = invoice_view_flags(edit=True)
    return render_template(
        'invoice.html',
        mode='edit',
        form_action=url_for('update_invoice', invoice_id=invoice_id),
        invoice=invoice,
        recent_invoices=[],
        raw_invoice_text='',
        invoice_view='edit',
        **flags,
        **invoice_form_common_data(invoice['invoice_date'], invoice['supplier_name'] or '', invoice_rows_for_invoice(invoice_id)),
        **base_context('invoices', 'InventurManager – Rechnung bearbeiten'),
    )

@app.post('/invoice/<int:invoice_id>/update')
def update_invoice(invoice_id):
    existing = query_one('SELECT id FROM invoices WHERE id = ?', (invoice_id,))
    if not existing:
        flash('Rechnung wurde nicht gefunden.', 'error')
        return redirect(url_for('new_invoice'))
    return save_invoice_from_request(invoice_id=invoice_id)

@app.post('/invoice/<int:invoice_id>/delete')
def delete_invoice(invoice_id):
    existing = query_one('SELECT id FROM invoices WHERE id = ?', (invoice_id,))
    if not existing:
        flash('Rechnung wurde nicht gefunden.', 'error')
        return redirect(url_for('new_invoice'))
    execute('DELETE FROM invoice_lines WHERE invoice_id = ?', (invoice_id,))
    execute('DELETE FROM invoices WHERE id = ?', (invoice_id,))
    flash('Rechnung wurde gelöscht.', 'success')
    return redirect(url_for('new_invoice'))

@app.route('/inventory/<int:year>')

def inventory_page(year):
    ensure_inventory_year(year)
    q = request.args.get('q', '').strip()
    supplier_id = request.args.get('supplier_id', '').strip()
    missing_only = request.args.get('missing_only', '').strip() == '1'
    sql = '''
        SELECT v.id AS variant_id, g.id AS group_id, g.name AS group_name, v.variant_label, COALESCE(v.unit, '') AS unit,
               ic.opening_stock, ic.closing_stock, ic.inventory_price,
               COALESCE((
                    SELECT s.name
                    FROM invoice_lines il2
                    JOIN invoices i2 ON i2.id = il2.invoice_id
                    LEFT JOIN suppliers s ON s.id = i2.supplier_id
                    WHERE il2.variant_id = v.id AND COALESCE(s.name, i2.supplier) IS NOT NULL
                    ORDER BY i2.invoice_date DESC, il2.id DESC
                    LIMIT 1
               ), '–') AS latest_supplier
        FROM article_variants v
        JOIN article_groups g ON g.id = v.group_id
        LEFT JOIN inventory_counts ic ON ic.variant_id = v.id AND ic.year = ?
        WHERE v.is_active = 1
    '''
    params = [year]
    if q:
        sql += ' AND (g.name LIKE ? COLLATE NOCASE OR v.variant_label LIKE ? COLLATE NOCASE OR COALESCE(v.unit, \"\") LIKE ? COLLATE NOCASE)'
        like = f'%{q}%'
        params.extend([like, like, like])
    if supplier_id.isdigit():
        sql += ' AND EXISTS (SELECT 1 FROM article_suppliers aps WHERE aps.group_id = g.id AND aps.supplier_id = ?)'
        params.append(int(supplier_id))
    if missing_only:
        sql += ' AND ic.closing_stock IS NULL'
    sql += ' ORDER BY g.name COLLATE NOCASE, v.variant_label COLLATE NOCASE'
    rows = enrich_inventory_rows(year, query_all(sql, tuple(params)))
    total_value = sum(float(row.get('calculated_inventory_value') or 0) for row in rows)
    all_rows = enrich_inventory_rows(year, query_all(
        '''
        SELECT v.id AS variant_id, g.id AS group_id, g.name AS group_name, v.variant_label, COALESCE(v.unit, '') AS unit,
               ic.opening_stock, ic.closing_stock, ic.inventory_price, '–' AS latest_supplier
        FROM article_variants v
        JOIN article_groups g ON g.id = v.group_id
        LEFT JOIN inventory_counts ic ON ic.variant_id = v.id AND ic.year = ?
        WHERE v.is_active = 1
        ''',
        (year,),
    ))
    all_total_value = sum(float(row.get('calculated_inventory_value') or 0) for row in all_rows)
    return render_template(
        'inventory.html',
        year=year,
        rows=rows,
        q=q,
        supplier_id=supplier_id,
        missing_only=missing_only,
        suppliers=supplier_options(),
        total_value=total_value,
        all_total_value=all_total_value,
        **base_context('inventory', f'InventurManager – Inventur {year}'),
    )
@app.get('/inventory/<int:year>/print')
def inventory_print(year):
    ensure_inventory_year(year)
    rows = enrich_inventory_rows(year, query_all(
        '''
        SELECT v.id AS variant_id, g.name AS group_name, v.variant_label, ic.opening_stock, ic.closing_stock, ic.inventory_price
        FROM article_variants v
        JOIN article_groups g ON g.id = v.group_id
        LEFT JOIN inventory_counts ic ON ic.variant_id = v.id AND ic.year = ?
        WHERE v.is_active = 1
        ORDER BY g.name COLLATE NOCASE, v.variant_label COLLATE NOCASE
        ''',
        (year,),
    ))
    total_value = sum(float(row.get('calculated_inventory_value') or 0) for row in rows)
    return render_template(
        'inventory_print.html',
        year=year,
        rows=rows,
        total_value=total_value,
        **base_context('inventory', f'InventurManager – Inventur {year} PDF'),
    )
@app.post('/inventory/<int:year>/save')
def save_inventory(year):
    variant_ids = request.form.getlist('variant_id[]')
    opening_stocks = request.form.getlist('opening_stock[]')
    closing_stocks = request.form.getlist('closing_stock[]')
    inventory_prices = request.form.getlist('inventory_price[]')
    pending_rows = []
    validation_errors = []
    for idx, variant_id in enumerate(variant_ids):
        try:
            vid = int(variant_id)
        except ValueError:
            continue
        opening = opening_stocks[idx].strip() if idx < len(opening_stocks) else ''
        closing = closing_stocks[idx].strip() if idx < len(closing_stocks) else ''
        opening_val = float(opening.replace(',', '.')) if opening else None
        closing_val = float(closing.replace(',', '.')) if closing else None
        layers = inventory_layers_for_year(year, vid)
        available_qty = inventory_available_quantity(layers)
        _, calculated_price = inventory_value_for_year(year, vid, closing_val)
        if closing_val not in (None, '') and float(closing_val) - available_qty > 1e-9:
            variant = query_one(
                '''
                SELECT g.name AS group_name, v.variant_label
                FROM article_variants v
                JOIN article_groups g ON g.id = v.group_id
                WHERE v.id = ?
                ''',
                (vid,),
            )
            label = f"{variant['group_name']} / {variant['variant_label']}" if variant else f'Variante {vid}'
            validation_errors.append(
                f"{label}: Endbestand {qty(closing_val)} überschreitet die verfügbare Menge {qty(available_qty)}."
            )
        pending_rows.append((vid, opening_val, closing_val, calculated_price))
    if validation_errors:
        for message in validation_errors:
            flash(message, 'error')
        return redirect(url_for('inventory_page', year=year))
    for vid, opening_val, closing_val, calculated_price in pending_rows:
        execute(
            '''
            INSERT INTO inventory_counts (year, variant_id, opening_stock, closing_stock, inventory_price, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(year, variant_id) DO UPDATE SET
              opening_stock = excluded.opening_stock,
              closing_stock = excluded.closing_stock,
              inventory_price = excluded.inventory_price,
              updated_at = excluded.updated_at
            ''',
            (
                year,
                vid,
                opening_val,
                closing_val,
                calculated_price,
                now_iso(),
            ),
        )
    for variant_id in variant_ids:
        try:
            vid = int(variant_id)
        except ValueError:
            continue
        current = query_one('SELECT closing_stock, inventory_price FROM inventory_counts WHERE year = ? AND variant_id = ?', (year, vid))
        execute(
            '''
            INSERT INTO inventory_counts (year, variant_id, opening_stock, closing_stock, inventory_price, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(year, variant_id) DO UPDATE SET
              opening_stock = excluded.opening_stock,
              inventory_price = excluded.inventory_price,
              updated_at = excluded.updated_at
            ''',
            (
                year + 1,
                vid,
                current['closing_stock'] if current else None,
                None,
                current['inventory_price'] if current else None,
                now_iso(),
            ),
        )
    log_event(f'Inventur gespeichert: {year}')
    flash(f'Inventur {year} wurde gespeichert.', 'success')
    redirect_query = {'year': year}
    return redirect(url_for('inventory_page', year=year))
@app.route('/reports')
def reports():
    # Alte Route bleibt als Weiterleitung erhalten.
    variant_id = request.args.get('variant_id', '').strip()
    if variant_id.isdigit():
        return redirect(url_for('variant_detail', variant_id=int(variant_id)))
    return redirect(url_for('articles'))
def install_snippet():
    return '\n'.join([
        'rm -rf /tmp/inventurmanager-update',
        'mkdir -p /tmp/inventurmanager-update',
        '',
        'unzip -o /share/InventurManager/inventurmanager-v0.9.2.zip -d /tmp/inventurmanager-update',
        '',
        'rm -rf /addons/inventurmanager',
        'mkdir -p /addons/inventurmanager',
        '',
        'cp -a /tmp/inventurmanager-update/. /addons/inventurmanager/',
        '',
        "grep '^version:' /addons/inventurmanager/config.yaml",
    ])
@app.route('/settings')
def settings_page():
    text = LOG_PATH.read_text(encoding='utf-8') if LOG_PATH.exists() else ''
    return render_template('settings.html', log_text=text[-50000:], **base_context('settings', 'InventurManager – Einstellungen'))
@app.get('/settings/backup/download')
def download_backup():
    if not DB_PATH.exists():
        flash('Es gibt noch keine Datenbank für ein Backup.', 'error')
        return redirect(url_for('settings_page'))
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    return send_file(DB_PATH, as_attachment=True, download_name=f'inventurmanager-backup-{timestamp}.db')
@app.post('/settings/backup/restore')
def restore_backup():
    file = request.files.get('backup_file')
    if not file or not file.filename:
        flash('Bitte eine Backup-Datei auswählen.', 'error')
        return redirect(url_for('settings_page'))
    tmp_path = DATA_DIR / '_restore_tmp.db'
    file.save(tmp_path)
    try:
        test = sqlite3.connect(tmp_path)
        test.execute('SELECT name FROM sqlite_master LIMIT 1')
        test.close()
        shutil.copy2(tmp_path, DB_PATH)
        log_event('Backup wiederhergestellt.')
        flash('Backup wurde wiederhergestellt. Ein Neustart des Add-ons ist sinnvoll.', 'success')
    except Exception as exc:
        flash(f'Backup konnte nicht wiederhergestellt werden: {exc}', 'error')
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return redirect(url_for('settings_page'))
@app.route('/logs')
def logs_page():
    return redirect(url_for('settings_page'))
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8130')), debug=False)
