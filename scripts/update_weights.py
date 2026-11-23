"""Update SPY proxy sector allocations from issuer daily holdings XLSX.
The last valid dated JSON remains when download/parse fails.
"""
import io, json, re, sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from openpyxl import load_workbook

URL = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
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
 for sheet in workbook.worksheets:
  pass
  pass
 raise ValueError("Complete 11-sector SPY holdings table not found")

def parse_sector_website():
 from bs4 import BeautifulSoup
 url="https://www.ssga.com/us/en/intermediary/etfs/state-street-spdr-sp-500-etf-trust-spy"
 request=Request(url,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36","Accept":"text/html"})
 with urlopen(request,timeout=45) as response:
  html=response.read(9_000_000).decode("utf-8","replace")
 soup=BeautifulSoup(html,"html.parser")
 print("ISSUER-WEB",len(html),"tables",len(soup.find_all("table")),"contains-tech",("Information Technology" in html))
 for table in soup.find_all("table"):
  sums={}
  for tr in table.find_all("tr"):
   cells=[x.get_text(" ",strip=True) for x in tr.find_all(["th","td"])]
   if len(cells)<2:continue
   ticker=TICKERS.get(norm(cells[0]))
   if ticker:
    raw=next((x for x in cells[1:] if "%" in x),None)
    if raw is None:continue
    value=numeric(raw)
    if value is not None:sums[ticker]=value
  if len(sums)==11 and 97<=sum(sums.values())<=103:
   cleaned={k:round(v,4) for k,v in sorted(sums.items())}
   whole=soup.get_text(" ",strip=True)
   m=re.search(r"Fund Sector Breakdown\s+as of\s+([A-Z][a-z]{2}\s+\d{1,2}\s+20\d\d)",whole)
   asof=datetime.strptime(m.group(1),"%b %d %Y").strftime("%Y-%m-%d") if m else None
   print("Issuer sector table parsed",asof,cleaned)
   return cleaned,asof,url
 raise ValueError("Issuer HTML has no validated 11-sector table")

def main():
 try:
  request=Request(URL,headers={"User-Agent":"Mozilla/5.0 (ATLAS personal financial research)","Accept":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream"})
  with urlopen(request,timeout=45) as response:
   data=response.read(10_000_000)
  if not data.startswith(b"PK"):raise ValueError("Issuer response is not an XLSX file")
  try:
   weights,asof,real_source=parse_sector_website()
  except Exception as web_error:
   print("WARNING: fund sector website unavailable:",web_error,file=sys.stderr)
   weights,asof=parse(data)
   real_source=URL
  result={"source":"State Street — SPY daily holdings (SPX proxy)","sourceUrl":real_source,"asOf":asof,"fetchedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),"weights":weights,"type":"issuer-holdings-proxy"}
  OUT.parent.mkdir(parents=True,exist_ok=True)
  OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  print("Updated SPY weights",asof,weights)
 except Exception as exc:
  print(f"WARNING: {exc}; previous weights preserved",file=sys.stderr)
  if not OUT.exists():raise
if __name__=="__main__":main()