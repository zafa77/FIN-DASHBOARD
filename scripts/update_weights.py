"""Update SPY proxy sector allocations from issuer daily holdings XLSX.
The last valid dated JSON remains when download/parse fails.
"""
import io, json, re, sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from openpyxl import load_workbook

URL = "https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-spy.xlsx"
OUT = Path("data/sector_weights.json")
TICKERS = {
 "information technology":"XLK", "technology":"XLK",
 "financials":"XLF", "financial":"XLF",
 "health care":"XLV", "healthcare":"XLV",
 "consumer discretionary":"XLY",
 "communication services":"XLC", "communication":"XLC",
 "industrials":"XLI", "industrial":"XLI",
 "consumer staples":"XLP", "energy":"XLE",
 "utilities":"XLU", "real estate":"XLRE", "materials":"XLB"
}
EXPECTED = set(TICKERS.values())
def norm(v):
 return re.sub(r"\s+"," ",str(v if v is not None else "").strip().lower())
def numeric(v):
 if isinstance(v,(int,float)):return float(v)
 try:return float(str(v).strip().replace("%","").replace(",","").replace("$",""))
 except (TypeError, ValueError):return None
def source_date(rows):
 for row in rows[:30]:
  vals=[v for v in row[:8] if v is not None]
  t=" ".join(map(str,vals))
  if "holdings" not in t.lower() and "as of" not in t.lower():continue
  for v in vals:
   if isinstance(v,(date,datetime)):return v.strftime("%Y-%m-%d")
  m=re.search(r"\b(?:20\d\d[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]20\d\d)\b",t)
  if m:
   for fmt in ("%Y-%m-%d","%Y/%m/%d","%m/%d/%Y","%d/%m/%Y","%m-%d-%Y"):
    try:return datetime.strptime(m.group(0),fmt).strftime("%Y-%m-%d")
    except ValueError:pass
 return None
def parse(data):
 workbook=load_workbook(io.BytesIO(data),read_only=True,data_only=True)
 for sheet in workbook.worksheets:
  rows=list(sheet.iter_rows(values_only=True))
  for start,row in enumerate(rows[:75]):
   headers=list(map(norm,row))
   si=next((i for i,x in enumerate(headers) if x in ("sector","gics sector","gics sector name","sector name")),None)
   wi=next((i for i,x in enumerate(headers) if x in ("weight","weight (%)","weight %","fund weight","market value weight")),None)
   if si is None or wi is None:continue
   result={ticker:0.0 for ticker in EXPECTED};count=0
   for cells in rows[start+1:]:
    if len(cells)<=max(si,wi):continue
    ticker=TICKERS.get(norm(cells[si]))
    value=numeric(cells[wi])
    if ticker and value is not None and value>=0:
     result[ticker]+=value;count+=1
   total=sum(result.values())
   if 0.97<total<1.03:
    result={k:100*v for k,v in result.items()};total*=100
   if count<400 or not 97<=total<=103 or any(v<=0 for v in result.values()):continue
   return {k:round(v,4) for k,v in sorted(result.items())},source_date(rows)
 raise ValueError("Complete 11-sector SPY holdings table not found")
def main():
 try:
  request=Request(URL,headers={"User-Agent":"Mozilla/5.0 (ATLAS personal financial research)","Accept":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream"})
  with urlopen(request,timeout=45) as response:
   data=response.read(10_000_000)
  if not data.startswith(b"PK"):raise ValueError("Issuer response is not an XLSX file")
  weights,asof=parse(data)
  result={"source":"State Street — SPY daily holdings (SPX proxy)","sourceUrl":URL,"asOf":asof,"fetchedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),"weights":weights,"type":"issuer-holdings-proxy"}
  OUT.parent.mkdir(parents=True,exist_ok=True)
  OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  print("Updated SPY weights",asof,weights)
 except Exception as exc:
  print(f"WARNING: {exc}; previous weights preserved",file=sys.stderr)
  if not OUT.exists():raise
if __name__=="__main__":main()
