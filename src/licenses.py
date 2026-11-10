#!/usr/bin/env python3
"""Attach a licence to every reception row (no ingest script changes).

  python3 -I src/licenses.py

Licence is a function of the source, so data/licenses.tsv (one row per source) is loaded into a
`licenses` table and the view `reception_licensed` gives every row its licence. Re-run after any
ingest; it fails loudly if a source has no licence row.
The compilation itself (refKey normalization, the overlap columns, the joins) is CC BY-NC 4.0,
as LICENSE says (Wilson, 2026-09-10 and 2026-11-10).
"""
import csv, os, sqlite3, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db = sqlite3.connect(os.path.join(HERE, 'data', 'reception.sqlite'))
rows = list(csv.DictReader(open(os.path.join(HERE, 'data', 'licenses.tsv'), encoding='utf-8'), delimiter='\t'))
db.executescript("""DROP VIEW IF EXISTS reception_licensed; DROP TABLE IF EXISTS licenses;
CREATE TABLE licenses(source TEXT PRIMARY KEY, license TEXT NOT NULL, stores_text TEXT, note TEXT);""")
db.executemany('INSERT INTO licenses VALUES (?,?,?,?)', [(r['source'], r['license'], r['stores_text'], r['note']) for r in rows])
db.execute("""CREATE VIEW reception_licensed AS
  SELECT r.*, l.license FROM reception r LEFT JOIN licenses l ON l.source = r.source""")
missing = [s for (s,) in db.execute('SELECT DISTINCT source FROM reception WHERE source NOT IN (SELECT source FROM licenses)')]
db.commit()
for lic, n in db.execute('SELECT license, count(*) FROM reception_licensed GROUP BY license ORDER BY 2 DESC'):
    print(f'{lic}\t{n}')
if missing:
    sys.exit(f'sources with no licence row: {missing}')
