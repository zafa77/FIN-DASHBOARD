"""Experimental Nasdaq-100 end-of-day market breadth.
The output contains only aggregate counts/percentages, no stock-level quotes.
Underlying research price feed: Yahoo Finance via yfinance; this is not a licensed
realtime or redistributable market data product. Replace for commercial use.
Run after the US cash close. Fail closed below 95% coverage.
"""
import io
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

OUTPUT = Path("data/ndx_breadth.json")
URL = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
HEADERS = {"User-Agent": "ZAFA-Research-Monitor/1.0 (contact: project GitHub issues)"}

def constituents():
    res = requests.get(URL, headers=HEADERS, timeout=45)
    res.raise_for_status()
    tables = pd.read_html(io.StringIO(res.text))
    tickers=[]
    for table in tables:
        columns=[str(c).lower().strip() for c in table.columns]
        possible=[i for i,x in enumerate(columns) if any(n in x for n in ("ticker","symbol"))]
        if not possible or not (90<=len(table)<=125):continue
        for ticker in table.iloc[:,possible[0]].astype(str):
            ticker=ticker.split("[")[0].strip().upper().replace(".","-")
            if re.fullmatch(r"[A-Z][A-Z0-9-]{0,7}",ticker) and ticker not in tickers:
                tickers.append(ticker)
        if 95<=len(tickers)<=110:
            return tickers
        tickers=[]
    raise ValueError("Could not validate current 95–110 NASDAQ-100 component securities")

def download_batches(symbols):
    close={}
    errors=[]
    for idx in range(0,len(symbols),18):
        batch=symbols[idx:idx+18]
        try:
            frame=yf.download(
              tickers=batch,period="5mo",interval="1d",
              auto_adjust=True,progress=False,threads=True,
              group_by="column",timeout=35
            )
            if frame.empty:raise ValueError("empty daily frame")
            series=frame.get("Close")
            if series is None:raise ValueError("missing close field")
            if isinstance(series,pd.Series):
                series=series.to_frame(name=batch[0])
            for symbol in batch:
                if symbol not in series.columns:continue
                values=series[symbol].dropna()
                if len(values)<55:continue
                close[symbol]=values
        except Exception as exc:
            errors.append(f"batch {idx//18}: {str(exc)[:160]}")
    return close,errors

def main():
    symbols=constituents()
    closes,errors=download_batches(symbols)
    if len(closes)<int(len(symbols)*.95+.999):
        raise RuntimeError(f"Insufficient Yahoo coverage: {len(closes)}/{len(symbols)}; "+", ".join(errors))
    newest=Counter(series.index[-1].date().isoformat() for series in closes.values()).most_common(1)[0][0]
    current={}
    for ticker,prices in closes.items():
        sample=prices[prices.index.date<=datetime.strptime(newest,"%Y-%m-%d").date()]
        if len(sample)<51 or sample.index[-1].date().isoformat()!=newest:continue
        # Exclude nulls, non-positive and implausible prices.
        if not (sample.tail(51).gt(0).all()):continue
        current[ticker]=sample
    total=len(current)
    required=int(len(symbols)*.95+.999)
    if total<required:raise RuntimeError(f"Same-session breadth coverage too low {total}/{len(symbols)} on {newest}")
    as_of=datetime.strptime(newest,"%Y-%m-%d").replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc)-as_of).days>6:
        raise RuntimeError("Stale breadth date: "+newest)
    advance=sum(float(s.iloc[-1])>float(s.iloc[-2]) for s in current.values())
    decline=sum(float(s.iloc[-1])<float(s.iloc[-2]) for s in current.values())
    unchanged=total-advance-decline
    above20=sum(float(s.iloc[-1])>float(s.tail(20).mean()) for s in current.values())
    above50=sum(float(s.iloc[-1])>float(s.tail(50).mean()) for s in current.values())
    payload={
       "asOf":newest,"generatedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),
       "source":"Nasdaq-100 component list: Wikipedia; adjusted EOD closes: Yahoo Finance research feed",
       "sources":[URL,"https://finance.yahoo.com/"],
       "method":"Last adjusted close > prior close = advance; close > trailing SMA20/SMA50 = above MA",
       "dataType":"EOD derived aggregates; not live or exchange-certified breadth",
       "universeCount":len(symbols),"covered":total,
       "coveragePct":round(100*total/len(symbols),1),
       "advances":advance,"declines":decline,"unchanged":unchanged,
       "above20":above20,"above50":above50,
       "above20Pct":round(100*above20/total,1),
       "above50Pct":round(100*above50/total,1),
    }
    assert payload["advances"]+payload["declines"]+payload["unchanged"]==total
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("Nasdaq-100 breadth calculated",newest,"coverage",total,"/",len(symbols),
          "A/D",advance,decline,"Above MA20/50",above20,above50)
if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("ERROR: breadth update failed; previous published file retained:",exc,file=sys.stderr)
        raise
