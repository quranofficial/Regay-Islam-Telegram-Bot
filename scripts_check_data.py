from pathlib import Path
import json, sqlite3, sys
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
checks={
 'regayislam.db':('ayah_text',6236),
 'surat.db':('surat',114),
 'name.db':('name',100),
 'duha.db':('du3a',56),
 'mu.db':('babat',2009),
}
failed=False
for filename,(table,expected) in checks.items():
    con=sqlite3.connect(DATA/filename)
    actual=con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    con.close()
    status='OK' if actual==expected else 'MISMATCH'
    print(f'{status}: {filename} / {table}: {actual} rows (expected {expected})')
    failed |= actual!=expected
for p in DATA.glob('*.json'):
    try:
        obj=json.loads(p.read_text(encoding='utf-8'))
        print(f'OK: {p.name}: {len(obj) if hasattr(obj,"__len__") else "valid"}')
    except Exception as e:
        print(f'BAD JSON: {p.name}: {e}'); failed=True
# The standalone PDF library must contain a substantial, valid catalogue.
try:
    books=json.loads((DATA/'ktebakan.json').read_text(encoding='utf-8'))
    valid_books=[b for b in books if isinstance(b,dict) and b.get('name') and str(b.get('url','')).startswith('https://')]
    print(f'OK: PDF library: {len(valid_books)} valid books')
    failed |= len(valid_books)<50
except Exception as e:
    print(f'BAD PDF library: {e}'); failed=True

# Validate the actual Ramadan content tables (Titles contains stale table names).
try:
    con=sqlite3.connect(DATA/'ramazanew.db')
    existing={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required={'welcome','barbang','parshew','nwezhtaraweh','shawyqadr'}
    missing=required-existing
    print(f'OK: Ramadan content tables: {len(required & existing)}/{len(required)}')
    failed |= bool(missing)
    con.close()
except Exception as e:
    print(f'BAD Ramadan database: {e}'); failed=True

# Recitation timing databases are keyed by the exact reciter ID.
timing_ids=set()
for p in (DATA/'recitation_timings').glob('[0-9]*.db'):
    if not p.stem.isdigit():
        continue
    try:
        con=sqlite3.connect(p)
        count=con.execute('SELECT count(*) FROM timings').fetchone()[0]
        con.close()
        if count:
            timing_ids.add(p.stem)
    except Exception as e:
        print(f'BAD timing database {p.name}: {e}'); failed=True
print(f'OK: reciter timing databases: {len(timing_ids)}')
failed |= len(timing_ids)<50

if failed: sys.exit(1)
print('Data integrity checks passed.')
