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
if failed: sys.exit(1)
print('Data integrity checks passed.')
