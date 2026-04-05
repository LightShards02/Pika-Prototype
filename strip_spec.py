import csv

src = 'C:/Users/night/Work/Echelondx/Pika/dataset/specimen/raw-design-spec.csv'
dst = 'C:/Users/night/Work/Echelondx/Pika/dataset/specimen/raw-design-spec-stripped.csv'

with open(src, newline='', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))
    fieldnames = [c for c in rows[0].keys() if c not in ('acceptance_criteria', 'module_role')]

with open(dst, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
    w.writeheader()
    w.writerows(rows)

print(f'Wrote {len(rows)} rows, columns: {fieldnames}')
