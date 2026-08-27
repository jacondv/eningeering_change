import csv
import sys

import openpyxl

pn_col = int(sys.argv[1]) if len(sys.argv) > 1 else 3
pic_col = int(sys.argv[2]) if len(sys.argv) > 2 else 13

wb = openpyxl.load_workbook('/tmp/pic_update_source.xlsx', data_only=True)
ws = wb.worksheets[0]
rows = list(ws.iter_rows(min_row=2, values_only=True))
with open('/tmp/pic_update.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    for r in rows:
        pn = str(r[pn_col]).strip() if r[pn_col] is not None else ''
        pic = (r[pic_col] or '').strip() if r[pic_col] is not None else ''
        if pn:
            w.writerow([pn, pic])
print(f'{len(rows)} rows converted')
