#!/usr/bin/env bash
# Download all data needed for the Dallas Fed paper replication.
# Run this before replicate.py if the data/ directory is empty.
set -euo pipefail

DATADIR="$(dirname "$0")/data"
mkdir -p "$DATADIR/qcew"

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REF="https://www.bls.gov/oes/tables.htm"

echo "=== Downloading AIOE data from GitHub ==="
curl -sL -o "$DATADIR/AIOE_DataAppendix.xlsx" \
  "https://github.com/AIOE-Data/AIOE/raw/main/AIOE_DataAppendix.xlsx"
echo "  Done."

echo "=== Downloading QCEW national data (2019-2025) ==="
for year in 2019 2020 2021 2022 2023 2024 2025; do
  for qtr in 1 2 3 4; do
    outfile="$DATADIR/qcew/us_${year}_q${qtr}.csv"
    code=$(curl -sL -o "$outfile" -w "%{http_code}" \
      "https://data.bls.gov/cew/data/api/${year}/${qtr}/area/US000.csv")
    if [ "$code" = "200" ] && [ "$(wc -l < "$outfile")" -gt 10 ]; then
      echo "  ${year}Q${qtr}: OK"
    else
      echo "  ${year}Q${qtr}: skipped (HTTP $code)"
      rm -f "$outfile"
    fi
    sleep 0.3
  done
done

echo "=== Downloading OEWS national data (May 2019, 2022) ==="
for year in 19 22; do
  echo "  Downloading May 20${year}..."
  curl -sL \
    -H "User-Agent: $UA" -H "Referer: $REF" \
    "https://www.bls.gov/oes/special.requests/oesm${year}nat.zip" \
    -o "$DATADIR/oesm${year}nat.zip"
  (cd "$DATADIR" && mkdir -p "oesm${year}" && unzip -qo "oesm${year}nat.zip" -d "oesm${year}")
done

echo "=== Downloading OEWS 2024 flat files ==="
for f in oe.series oe.data.0.Current oe.occupation oe.datatype; do
  echo "  $f..."
  curl -sL \
    -H "User-Agent: $UA" \
    -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
    -H "Accept-Language: en-US,en;q=0.5" \
    -H "Referer: $REF" \
    "https://download.bls.gov/pub/time.series/oe/$f" \
    -o "$DATADIR/$(echo "$f" | sed 's/\.0\.Current/.current/')"
  sleep 1
done

echo "=== Extracting OEWS 2024 national data ==="
python3 -c "
import pandas as pd
DATADIR = '$DATADIR'
target_datatypes = {'01', '04', '11', '12', '13', '14', '15'}
target_series = {}
with open(f'{DATADIR}/oe.series', 'r') as f:
    f.readline()
    for line in f:
        parts = line.split('\t')
        if len(parts) >= 6:
            sid, at, ind, occ, dt = parts[0].strip(), parts[2].strip(), parts[3].strip(), parts[4].strip(), parts[5].strip()
            if at == 'N' and ind == '000000' and not occ.endswith('0') and occ != '000000' and dt in target_datatypes:
                target_series[sid] = (occ, dt)
records = []
with open(f'{DATADIR}/oe.data.current', 'r') as f:
    next(f)
    for line in f:
        parts = line.split('\t')
        if len(parts) >= 4:
            sid = parts[0].strip()
            if sid in target_series:
                occ, dtype = target_series[sid]
                records.append({'occ_code': occ, 'datatype': dtype, 'value': parts[3].strip()})
df = pd.DataFrame(records)
df['value'] = pd.to_numeric(df['value'], errors='coerce')
pivot = df.pivot_table(index='occ_code', columns='datatype', values='value')
pivot.columns = {'01':'tot_emp','04':'a_mean','11':'a_pct10','12':'a_pct25','13':'a_median','14':'a_pct75','15':'a_pct90'}.get(c,c) for c in pivot.columns]
pivot.to_csv(f'{DATADIR}/oews_2024_national.csv')
print(f'  {len(pivot)} occupations')
"

echo "=== Extracting OEWS historical data ==="
python3 -c "
import pandas as pd
DATADIR = '$DATADIR'
for year, path in [(2019, f'{DATADIR}/oesm19/oesm19nat/national_M2019_dl.xlsx'),
                   (2022, f'{DATADIR}/oesm22/oesm22nat/national_M2022_dl.xlsx')]:
    df = pd.read_excel(path)
    df.columns = [c.lower() for c in df.columns]
    df = df[df['i_group'] == 'cross-industry']
    df = df[df['o_group'] == 'detailed'].copy()
    df['occ_code_clean'] = df['occ_code'].str.replace('-', '')
    wage_cols = ['tot_emp', 'a_mean', 'a_pct10', 'a_pct25', 'a_median', 'a_pct75', 'a_pct90']
    for col in wage_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    out = df[['occ_code', 'occ_code_clean', 'occ_title'] + [c for c in wage_cols if c in df.columns]]
    out.to_csv(f'{DATADIR}/oews_{year}_national.csv', index=False)
    print(f'  {year}: {len(out)} occupations')
"

echo ""
echo "All data downloaded. Run: python3 replication/replicate.py"
