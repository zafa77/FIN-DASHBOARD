"""ZAFA RESEARCH prototype: delayed intraday NQ momentum confirmation.
Only computed directional signals are published, never a chart/bar tape.
Yahoo/CME quotes may be delayed, unavailable or rate-limited; not licensed live data.
Do not trade from this signal without independent price/order-flow verification.
"""
import json
import math
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

OUT=Path("data/nq_intraday_bias.json")
ET=ZoneInfo("America/New_York")
SYMBOL="NQ=F"

def stance(value,threshold):
    return 1 if value>threshold else -1 if value < -threshold else 0

def run():
    now=datetime.now(timezone.utc)
    now_et=now.astimezone(ET)
    if now_et.weekday()>4 or not (time(9,30)<=now_et.time()<time(16,10)):
        print("Outside NY cash session; preserving last snapshot.")
        return
    frame=yf.Ticker(SYMBOL).history(period="3d",interval="5m",auto_adjust=False,prepost=True,raise_errors=False,timeout=35)
    if frame is None or frame.empty or len(frame)<15:
        raise RuntimeError("No usable NQ=F intraday bars from Yahoo")
    idx=frame.index
    if idx.tz is None:
        raise RuntimeError("Intraday index has no timezone")
    frame=frame.copy()
    frame.index=frame.index.tz_convert(ET)
    session=frame[(frame.index.date==now_et.date())&
                  (frame.index.time>=time(9,30))&
                  (frame.index.time<time(16,0))]
    session=session.dropna(subset=["Close","High","Low","Volume"])
    session=session[session["Close"]>0]
    # Do not evaluate an opening range, VWAP or EMA before sufficient live-session bars.
    if len(session)<13:
        print("Fewer than 13 complete NY-session 5m bars; do not publish a signal.")
        return
    last=session.index[-1].to_pydatetime().astimezone(timezone.utc)
    age=(now-last).total_seconds()/60
    if age<0 or age>40:
        raise RuntimeError("Latest NQ price bar outside 40 minute freshness gate: "+str(round(age,1))+"m")
    close=session["Close"].astype(float)
    vol=session["Volume"].fillna(0).clip(lower=0).astype(float)
    typical=(session["High"]+session["Low"]+session["Close"])/3
    volume_total=float(vol.sum())
    if not math.isfinite(volume_total) or volume_total<=0:
        raise ValueError("No usable exchange-traded volume for session VWAP")
    vwap=float((typical*vol).sum()/volume_total)
    price=float(close.iloc[-1])
    ema5=float(close.ewm(span=5,adjust=False).mean().iloc[-1])
    ema13=float(close.ewm(span=13,adjust=False).mean().iloc[-1])
    ref30=float(close.iloc[-7])
    hi=float(session.iloc[:3]["High"].max())
    lo=float(session.iloc[:3]["Low"].min())
    if not all(math.isfinite(x) and x>0 for x in (price,vwap,ema5,ema13,ref30,hi,lo)):
        raise ValueError("Invalid numeric prices or opening range")
    distance=100*(price/vwap-1)
    spread=100*(ema5/ema13-1)
    ret30=100*(price/ref30-1)
    orb=1 if price>hi*1.0002 else -1 if price<lo*.9998 else 0
    factors=[
      {"key":"vwap","name":"NQ vs VWAP sesiune","value":round(distance,3),"unit":"%","vote":stance(distance,.08)},
      {"key":"ema","name":"EMA5 vs EMA13 (5m)","value":round(spread,3),"unit":"%","vote":stance(spread,.035)},
      {"key":"return30m","name":"Impuls ultimele 30m","value":round(ret30,3),"unit":"%","vote":stance(ret30,.12)},
      {"key":"openingRange","name":"Preț vs ORB 09:30–09:45 NY","value":"above" if orb>0 else "below" if orb<0 else "inside","unit":"","vote":orb}
    ]
    positives=sum(f["vote"]>0 for f in factors)
    negatives=sum(f["vote"]<0 for f in factors)
    label="bullish" if positives>=3 and negatives<=1 else "bearish" if negatives>=3 and positives<=1 else "mixed"
    payload={
      "version":1,"status":"active","instrument":"NQ futures continuous, Yahoo NQ=F",
      "dataType":"delayed_research_intraday_not_realtime","source":"Yahoo Finance CME delayed research bars",
      "sessionDate":now_et.date().isoformat(),"dataAsOf":last.isoformat(timespec="seconds"),
      "computedAt":now.isoformat(timespec="seconds"),"barInterval":"5m",
      "bars":len(session),"lastBarAgeMinutes":round(age,1),"score":positives-negatives,
      "positive":positives,"negative":negatives,"neutral":len(factors)-positives-negatives,
      "bias":label,"factors":factors,
      "disclaimer":"Nu este feed CME real-time; pot exista întârziere, rate limits și erori de preț. Nu include order-flow delta."
    }
    OUT.parent.mkdir(exist_ok=True,parents=True)
    if OUT.is_file():
        try:
            previous=json.loads(OUT.read_text(encoding="utf-8"))
            if previous.get("dataAsOf")==payload["dataAsOf"]:
                print("NQ snapshot unchanged: "+payload["dataAsOf"]);return
        except Exception:pass
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NQ intraday momentum",payload["bias"],"positive",positives,"negative",negatives,
          "dataAsOf",payload["dataAsOf"],"age",payload["lastBarAgeMinutes"])
if __name__=="__main__":
    try:run()
    except Exception as exc:
        print("No fresh bias published:",type(exc).__name__,str(exc),file=sys.stderr)
        raise
