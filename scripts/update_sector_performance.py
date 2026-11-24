"""ZAFA: calculate sector momentum from official State Street ETF daily NAV history.
No Twelve Data key and no republication of raw price series.
Retains previous last-valid results if issuer source is unavailable.
"""
from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from openpyxl import load_workbook

TICKERS = ("XLK", "XLF", "XLV", "XLY", "XLC", "XLI", "XLP", "XLE", "XLU", "XLRE", "XLB")
OUT = Path("data/sector_performance.json")
SOURCE_TEMPLATE = [
    "https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/navhistory-daily-us-{ticker}.xlsx",
    "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/navhist-us-en-{ticker}.xlsx",
    "https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/navhist-us-en-{ticker}.xlsx",
]

def download(url):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; ZAFA-Research/1.0)", "Accept":"application/octet-stream,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*"})
    with urlopen(req,timeout=55) as r:
        data=r.read(17_000_000)
    if len(data)>16_000_000:
        raise ValueError("Oversized file")
    return data

def rows_from_xlsx(data):
    book=load_workbook(io.BytesIO(data),read_only=True,data_only=True)
    return [list(sheet.iter_rows(values_only=True)) for sheet in book.worksheets]

def rows_from_xml(data):
    root=ET.fromstring(data)
    ns="{urn:schemas-microsoft-com:office:spreadsheet}"
    ns2="{urn:schemas-microsoft-com:office:spreadsheet}"
    books=[]
    for sheet in root.iter():
        if not sheet.tag.endswith("Worksheet"):continue
        results=[]
        for child in sheet.iter():
            if child.tag.endswith("Row"):
                row=[]
                for cell in child:
                    if not cell.tag.endswith("Cell"):continue
                    index=cell.attrib.get(ns2+"Index")
                    if index:
                        new_idx=int(index)-1
                        if new_idx>80:break
                        while len(row)<new_idx:row.append(None)
                    data_node=next((x for x in cell if x.tag.endswith("Data")),None)
                    row.append(data_node.text if data_node is not None else None)
                if row:results.append(row)
        if results:books.append(results)
    return books

def date_value(value):
    if isinstance(value,datetime):return value.date()
    if isinstance(value,date):return value
    if isinstance(value,(float,int)):
        if 35000<value<55000:return date(1899,12,30)+timedelta(days=int(value))
        return None
    raw=str(value or "").strip()
    raw=re.sub(r"T\d\d:.*$","",raw)
    for fmt in ("%Y-%m-%d","%m/%d/%Y","%m/%d/%y","%m-%d-%Y","%m-%d-%y","%d-%b-%Y","%b %d, %Y"):
        try:return datetime.strptime(raw,fmt).date()
        except ValueError:pass
    return None

def decimal_value(val):
    if isinstance(val,(int,float)):return float(val)
    try:return float(str(val).strip().replace("$","").replace(",",""))
    except (ValueError,TypeError):return None

def header_name(val):
    return re.sub(r"\s+"," ",str(val or "").strip().lower())

def parse_history(data):
    if data.startswith(b"PK"):books=rows_from_xlsx(data)
    elif b"Workbook" in data[:1000] or data.lstrip().startswith(b"<?xml"):books=rows_from_xml(data)
    else:raise ValueError("Neither .xlsx nor Excel XML")

    for rows in books:
        for head_i,head in enumerate(rows[:45]):
            vals=[header_name(v) for v in head]
            dcol=next((i for i,x in enumerate(vals) if x in ("date","as of date","pricing date","nav date","date (mm/dd/yyyy)","date (mm/dd/yy)","as of")),None)
            ncol=next((i for i,x in enumerate(vals) if x in ("nav","nav per share","nav/share","net asset value","nav price","net asset value per share","fund nav","nav per share ($)")),None)
            if dcol is None or ncol is None:continue
            if dcol==ncol:continue
            clean={}
            for row in rows[head_i+1:]:
                if max(dcol,ncol)>=len(row):continue
                day=date_value(row[dcol]);nav=decimal_value(row[ncol])
                if day and nav and 0<nav<50000 and date(2000,1,1)<=day<=date.today()+timedelta(days=1):
                    clean[day]=nav
            points=sorted(clean.items(),key=lambda item:item[0])
            if len(points)>=30:return points
    headers=[[[str(v)[:32] for v in row[:10]] for row in sheet[:12]] for sheet in books[:1]]
    raise ValueError("NAV table not found. Sample rows: "+repr(headers)[:1400])

def load_ticker(ticker):
    errors=[]
    for pattern in SOURCE_TEMPLATE:
        url=pattern.format(ticker=ticker.lower())
        try:
            records=parse_history(download(url))
            return records,url
        except Exception as e:
            errors.append(f"{e.__class__.__name__}: {e}")
    raise RuntimeError(ticker+" source attempts: "+" | ".join(errors)[:1400])

def run():
    today=datetime.now(timezone.utc).date()
    results,urls,last_dates={},[],[]
    for ticker in TICKERS:
        points,url=load_ticker(ticker)
        last_date=points[-1][0]
        if (today-last_date).days>15:
            raise ValueError(f"Stale NAV for {ticker} {last_date}")
        close=points[-1][1]
        def performance(lookback):
            previous=points[-1-lookback][1]
            if previous<=0:raise ValueError("Invalid previous NAV")
            return round(100*(close/previous-1),3)
        returns={k:performance(n) for k,n in (("1D",1),("2W",10),("1M",21))}
        results[ticker]=returns
        last_dates.append(last_date)
        urls.append(url)
        print(ticker,last_date.isoformat(),returns,flush=True)
    if (max(last_dates)-min(last_dates)).days>3:
        raise ValueError("Inconsistent NAV report dates: "+repr(last_dates))
    payload={
      "source":"State Street SPDR ETF official daily NAV history",
      "sourceUrls":sorted(set(urls)),
      "asOf":min(last_dates).isoformat(),
      "updatedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),
      "method":"NAV change, not dividend-adjusted total return or real-time ETF price",
      "windowDates":{"previous":"preceding trading close","twoWeeks":"10 prior closes","oneMonth":"21 prior closes"},
      "sectors":results
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("Updated 11 sector NAV momentum values",payload["asOf"])

if __name__=="__main__":
    try:run()
    except Exception as e:
        print("ERROR: sector NAV history fetch failed; retaining existing dataset:",e,file=sys.stderr)
        raise
