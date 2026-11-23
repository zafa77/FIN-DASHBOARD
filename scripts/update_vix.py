"""VIX closing history directly from Cboe. No Twelve Data API credits."""
from __future__ import annotations
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

URLS = [
 "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
 "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
]
OUT = Path("data/vix_30d.json")

def download():
 errors = []
 for url in URLS:
  try:
   req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept":"text/csv,*/*"})
   with urlopen(req, timeout=50) as response:
    raw = response.read(3_000_000)
   if not raw or b"DATE" not in raw[:300].upper():
    raise ValueError("Unexpected response format")
   return raw.decode("utf-8-sig"), url
  except Exception as exc:
   errors.append(f"{url}: {exc}")
 raise RuntimeError("; ".join(errors))

def run():
 text, source = download()
 rows = []
 reader = csv.DictReader(io.StringIO(text))
 for item in reader:
  x = {str(k).strip().upper():str(v).strip() for k,v in item.items() if k is not None}
  try:
   raw_date=x["DATE"]
   d=None
   for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
    try:
     d=datetime.strptime(raw_date,fmt)
     break
    except ValueError:
     pass
   if d is None:
    continue
   close=float(x["CLOSE"].replace(",",""))
   if not 0<close<200:
    continue
   rows.append({"date": d.strftime("%Y-%m-%d"), "close":round(close,4)})
  except (ValueError,KeyError,TypeError):
   continue
 rows.sort(key=lambda a:a["date"])
 clean={row["date"]:row for row in rows}
 ordered=sorted(clean.values(),key=lambda a:a["date"])
 if len(ordered)<100:
  raise ValueError("VIX price history too small")
 result={
  "source":"Cboe VIX daily historical close",
  "sourceUrl":source,
  "updatedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),
  "asOf":ordered[-1]["date"],
  "observations":ordered[-90:]
 }
 OUT.parent.mkdir(parents=True,exist_ok=True)
 OUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
 print("VIX updated through",result["asOf"],"observations",len(result["observations"]))
if __name__=="__main__":
 try:run()
 except Exception as e:
  print("WARNING VIX update failed, retaining last valid file:",e,file=sys.stderr)
  if not OUT.exists():
   raise
