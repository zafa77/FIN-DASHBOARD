"""ZAFA Market Reborn: update public US inflation and Fed target rate history.
Data: Federal Reserve Bank of St. Louis FRED CSV; no API key or Twelve Data credits.
CPI = CPIAUCNS, the non-seasonally adjusted headline CPI index, as YoY %.
Fed target = DFEDTARL/DFEDTARU, the official policy target range (not effective rate).
"""
import csv
import io
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OUTPUT = Path("data/macro_indicators.json")
SERIES = {
    "cpi": "CPIAUCNS",
    "fedLower": "DFEDTARL",
    "fedUpper": "DFEDTARU",
    "us02y": "DGS2",
    "eurusd": "DEXUSEU",
    "usdjpy": "DEXJPUS",
    "gbpusd": "DEXUSUK",
    "usdcad": "DEXCAUS",
    "usdsek": "DEXSDUS",
    "usdchf": "DEXSZUS",
}

def fetch_series(series, start):
    args=urlencode({"id": series, "cosd": start.isoformat()})
    url="https://fred.stlouisfed.org/graph/fredgraph.csv?"+args
    request=Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; ZAFA-Market-Reborn/1.0)",
        "Accept":"text/csv,text/plain,*/*",
    })
    with urlopen(request,timeout=55) as res:
        raw=res.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError(series+": unexpectedly large CSV")
    text=raw.decode("utf-8-sig")
    records=list(csv.DictReader(io.StringIO(text)))
    if not records:raise ValueError(series+": empty FRED CSV")
    value_col=next((s for s in records[0] if s.strip().upper()==series.upper()),None)
    date_col=next((s for s in records[0] if s.strip().lower() in ("date","observation_date")),None)
    if not value_col or not date_col:raise ValueError(series+": invalid CSV columns "+str(list(records[0])))
    rows={}
    today=datetime.now(timezone.utc).date()
    for record in records:
        try:
            d=date.fromisoformat(record[date_col])
            v=float(record[value_col])
            if d<=today and math.isfinite(v) and v>=0:
                rows[d]=v
        except (ValueError,TypeError):continue
    if not rows:raise ValueError(series+": all FRED observations missing")
    return sorted(rows.items()),url

def round_two(x):return round(float(x),2)

def make_cpi(rows):
    samples=dict(rows)
    all_months=sorted(samples)
    annual=[]
    for current_date in all_months:
        last_year=date(current_date.year-1,current_date.month,1)
        now=samples[current_date]
        old=samples.get(last_year)
        if old and old>0:
            annual.append({"date":current_date.strftime("%Y-%m"),"yoy":round_two(100*(now/old-1))})
    if len(annual)<18:raise ValueError("Not enough CPI YoY observations")
    latest=annual[-1]
    if (datetime.now(timezone.utc).date()-date.fromisoformat(latest["date"]+"-01")).days>145:
        raise ValueError("CPI series stale: "+latest["date"])
    return {
        "asOf":latest["date"],
        "yoy":latest["yoy"],
        "priorYoY":annual[-2]["yoy"],
        "deltaPp":round_two(latest["yoy"]-annual[-2]["yoy"]),
        "frequency":"monthly",
        "series":"CPIAUCNS",
        "method":"12-month percentage change in non-seasonally-adjusted headline CPI",
        "history":annual[-24:],
    }

def make_fed(lower_rows,upper_rows):
    lower=dict(lower_rows)
    upper=dict(upper_rows)
    today=datetime.now(timezone.utc).date()
    aligned=[]
    for d in sorted(set(lower).intersection(upper)):
        lo=lower[d];hi=upper[d]
        if 0<=lo<=hi<=25:aligned.append((d,lo,hi))
    if not aligned:raise ValueError("Fed lower and upper range dates do not match")
    last=aligned[-1]
    if (today-last[0]).days>20:raise ValueError("Fed target series stale: "+last[0].isoformat())
    changes=[]
    for d,lo,hi in aligned:
        if not changes or changes[-1]["lower"]!=lo or changes[-1]["upper"]!=hi:
            changes.append({"date":d.isoformat(),"lower":round_two(lo),"upper":round_two(hi)})
    cutoff=today-timedelta(days=730)
    before=[r for r in changes if date.fromisoformat(r["date"])<cutoff]
    history=([before[-1]] if before else [])+[r for r in changes if date.fromisoformat(r["date"])>=cutoff]
    latest={"date":last[0].isoformat(),"lower":round_two(last[1]),"upper":round_two(last[2])}
    if history and history[-1]["date"]!=latest["date"]:
        history.append(latest)
    year_ago=today-timedelta(days=365)
    old=[r for r in changes if date.fromisoformat(r["date"])<=year_ago]
    prior_year=old[-1] if old else None
    delta=round_two(latest["upper"]-prior_year["upper"]) if prior_year else None
    return {
        "asOf":latest["date"],
        "lower":latest["lower"],
        "upper":latest["upper"],
        "deltaUpper12mPp":delta,
        "changes2y":history,
        "lastPolicyChange":changes[-1]["date"],
        "previousRange":changes[-2] if len(changes)>=2 else None,
        "series":["DFEDTARL","DFEDTARU"],
        "method":"Federal funds target range, not the effective federal funds rate",
    }

def make_us02y(rows):
    today=datetime.now(timezone.utc).date()
    if len(rows)<8:raise ValueError("Too few US02Y observations")
    latest=rows[-1]
    if (today-latest[0]).days>10:raise ValueError("US02Y FRED series is stale")
    if latest[1]>25:raise ValueError("Unexpected treasury yield")
    daily_bp=round((latest[1]-rows[-2][1])*100,1)
    five_bp=round((latest[1]-rows[-6][1])*100,1)
    return {
      "asOf":latest[0].isoformat(),
      "yieldPct":round_two(latest[1]),
      "dailyBp":daily_bp,
      "fiveDayBp":five_bp,
      "previousDate":rows[-2][0].isoformat(),
      "history":[{"date":day.isoformat(),"yieldPct":round_two(value)} for day,value in rows[-50:]],
      "source":"Federal Reserve H.15 via FRED",
      "series":"DGS2",
      "method":"Daily 2-year Treasury constant maturity yield, percentage; differences in basis points."
    }

def make_dxy_indicative(fx_rows):
    """ICE USDX basket formula applied to FRED daily H.10 exchange rates.
    Indicative end-of-day reconstruction: not an official ICE spot quote.
    """
    points={name:dict(rows) for name,rows in fx_rows.items()}
    shared=set.intersection(*(set(v) for v in points.values()))
    history=[]
    for day in sorted(shared):
        v={name:rows[day] for name,rows in points.items()}
        if any(x<=0 for x in v.values()):continue
        dxy=50.14348112 * (v["eurusd"]**(-.576)) * (v["usdjpy"]**.136) * (
            v["gbpusd"]**(-.119)) * (v["usdcad"]**.091) * (
            v["usdsek"]**.042) * (v["usdchf"]**.036)
        if math.isfinite(dxy) and 50<dxy<180:
            history.append({"date":day.isoformat(),"value":round_two(dxy)})
    if len(history)<25:raise ValueError("DXY cannot be reconstructed from sufficient common FX observations")
    latest=history[-1]
    age=(datetime.now(timezone.utc).date()-date.fromisoformat(latest["date"])).days
    if age>18:raise ValueError("DXY FX rates too old: "+latest["date"])
    return {
      "asOf":latest["date"],
      "value":latest["value"],
      "oneDayPts":round_two(latest["value"]-history[-2]["value"]),
      "fiveDayPts":round_two(latest["value"]-history[-6]["value"]),
      "history":history[-65:],
      "source":"Federal Reserve H.10 FX rates via FRED, ICE USDX index-weight formula",
      "formula":"50.14348112 * EURUSD^-0.576 * USDJPY^0.136 * GBPUSD^-0.119 * USDCAD^0.091 * USDSEK^0.042 * USDCHF^0.036",
      "type":"indicative_eod_reconstruction_not_ice_official_or_intraday",
      "series":{"eurusd":"DEXUSEU","usdjpy":"DEXJPUS","gbpusd":"DEXUSUK",
                "usdcad":"DEXCAUS","usdsek":"DEXSDUS","usdchf":"DEXSZUS"}
    }

def main():
    today=datetime.now(timezone.utc).date()
    cpi,url_cpi=fetch_series(SERIES["cpi"],date(today.year-5,1,1))
    low,url_low=fetch_series(SERIES["fedLower"],today-timedelta(days=1120))
    high,url_high=fetch_series(SERIES["fedUpper"],today-timedelta(days=1120))
    us02y,url_us02y=fetch_series(SERIES["us02y"],today-timedelta(days=180))
    fx_rows={}
    fx_urls=[]
    for key in ("eurusd","usdjpy","gbpusd","usdcad","usdsek","usdchf"):
        rows,url=fetch_series(SERIES[key],today-timedelta(days=235))
        fx_rows[key]=rows
        fx_urls.append(url)
    payload={
        "updatedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source":"FRED / U.S. Bureau of Labor Statistics / Federal Reserve",
        "sourceUrls":[url_cpi,url_low,url_high,url_us02y,*fx_urls],
        "cpi":make_cpi(cpi),
        "fed":make_fed(low,high),
        "us02y":make_us02y(us02y),
        "dxy":make_dxy_indicative(fx_rows),
    }
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ZAFA macro updated:",payload["cpi"]["asOf"],payload["cpi"]["yoy"],
          "Fed:",payload["fed"]["lower"],payload["fed"]["upper"],
          "changes:",len(payload["fed"]["changes2y"]),
          "US02Y:",payload["us02y"]["yieldPct"],"change bp:",payload["us02y"]["dailyBp"],
          "DXY indicative:",payload["dxy"]["value"],"date:",payload["dxy"]["asOf"])
if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("ERROR: official FRED macro update failed; existing published data is preserved:",exc,file=sys.stderr)
        raise