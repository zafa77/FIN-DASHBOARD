"""Download official CFTC Traders in Financial Futures (TFF) futures-only reports.
Track Nasdaq-100 and S&P 500 consolidated contracts, Asset Managers and Leveraged Funds.
No third-party API key. Tuesday-position snapshots, normally published Fridays.
"""
import csv
import io
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

YEAR = datetime.now(timezone.utc).year
ARCHIVE = f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{YEAR}.zip"
WEEKLY = "https://www.cftc.gov/dea/newcot/FinFutWk.txt"
OUTPUT = Path("data/cot_tff.json")
MARKETS = {
    "NQ": {"code": "20974+", "name": "NASDAQ-100 Consolidated"},
    "ES": {"code": "13874+", "name": "S&P 500 Consolidated"},
}
# Indices from CFTC's official Traders in Financial Futures field list (zero-based).
FIELDS = {
    "market": 0, "date": 2, "code": 3, "oi": 7,
    "asset_long": 11, "asset_short": 12, "asset_spreading": 13,
    "lev_long": 14, "lev_short": 15, "lev_spreading": 16,
}
ALIASES = {
    "market": "Market_and_Exchange_Names",
    "date": "Report_Date_as_MM_DD_YYYY",
    "code": "CFTC_Contract_Market_Code",
    "oi": "Open_Interest_All",
    "asset_long": "Asset_Mgr_Positions_Long_All",
    "asset_short": "Asset_Mgr_Positions_Short_All",
    "asset_spreading": "Asset_Mgr_Positions_Spread_All",
    "lev_long": "Lev_Money_Positions_Long_All",
    "lev_short": "Lev_Money_Positions_Short_All",
    "lev_spreading": "Lev_Money_Positions_Spread_All",
}

def download(url, limit=12_000_000):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (ATLAS personal CFTC research)", "Accept": "*/*"})
    with urlopen(req, timeout=60) as response:
        data = response.read(limit+1)
    if len(data)>limit:
        raise ValueError("Oversized CFTC download")
    return data

def decode(data):
    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try: return data.decode(encoding)
        except UnicodeDecodeError: pass
    raise ValueError("Could not decode CFTC text")

def pos_int(value):
    s = str(value).strip().replace(",","")
    if s in ("", "."): return 0
    val = int(float(s))
    if val < 0: raise ValueError("Unexpected negative open position")
    return val

def parse_date(s):
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d"):
        try: return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError: pass
    raise ValueError("Invalid CFTC report date: "+s)

def parse_text(text):
    raw = list(csv.reader(io.StringIO(text)))
    rows = [row for row in raw if len(row)>=17]
    if not rows: raise ValueError("Missing financial futures rows")
    lookup = dict(FIELDS)
    first = [c.strip().strip('"') for c in rows[0]]
    if "CFTC_Contract_Market_Code" in first:
        lookup = {k:first.index(alias) if alias in first else FIELDS[k] for k,alias in ALIASES.items()}
        rows = rows[1:]
    result = {key:{} for key in MARKETS}
    for row in rows:
        try:
            market_name = row[lookup["market"]].upper()
            code = str(row[lookup["code"]]).strip().strip('"')
            symbol = next((s for s,m in MARKETS.items() if code==m["code"]), None)
            if not symbol:
                # We require the consolidated code; never silently combine NQ + MNQ manually.
                continue
            if "CONSOLIDATED" not in market_name:
                continue
            day = parse_date(row[lookup["date"]])
            oi = pos_int(row[lookup["oi"]])
            if oi < 10000: continue
            def group(prefix):
                lo = pos_int(row[lookup[prefix+"_long"]])
                sh = pos_int(row[lookup[prefix+"_short"]])
                spread = pos_int(row[lookup[prefix+"_spreading"]])
                return {"long":lo, "short":sh, "spreading":spread, "net":lo-sh,
                        "netPctOI": round(100*(lo-sh)/oi, 3)}
            rec = {"date":day, "openInterest":oi, "assetManagers":group("asset"),
                   "leveragedFunds":group("lev")}
            result[symbol][day] = rec
        except (ValueError,KeyError,TypeError,IndexError):
            continue
    return result

def merge(into,source):
    for symbol, observations in source.items():
        into[symbol].update(observations)

def run():
    content=download(ARCHIVE)
    if not content.startswith(b"PK"):raise ValueError("CFTC archive is not a ZIP file")
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        candidates=[n for n in z.namelist() if n.lower().endswith((".txt",".csv"))]
        if not candidates:raise ValueError("No CFTC text report in ZIP")
        most=max(candidates,key=lambda n:z.getinfo(n).file_size)
        base=parse_text(decode(z.read(most)))
    errors=[]
    try:
        weekly=parse_text(decode(download(WEEKLY)))
        merge(base,weekly)
    except Exception as exc:
        errors.append("Weekly file unavailable: "+str(exc))
    end={}
    for symbol,m in MARKETS.items():
        observations=sorted(base[symbol].values(),key=lambda x:x["date"])
        if len(observations)<12:raise ValueError("Fewer than 12 COT weeks for "+symbol)
        # The 2026 annual archive + most recent live report yields 26-week history.
        observations=observations[-26:]
        if observations[-1]["date"] > datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            raise ValueError("CFTC report date is in future")
        end[symbol]={**m,"observations":observations}
        print(symbol,"weeks",len(observations),"latest",observations[-1]["date"],
              "leveraged net",observations[-1]["leveragedFunds"]["net"])
    payload={
        "report":"CFTC Traders in Financial Futures (TFF) — Futures Only",
        "asOf":max(end["NQ"]["observations"][-1]["date"],end["ES"]["observations"][-1]["date"]),
        "updatedAt":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourceUrls":[ARCHIVE,WEEKLY],
        "disclaimer":"Positions as of Tuesday, generally released Friday. Weekly changes in holdings are not executed trading volume.",
        "markets":end,
        "warnings":errors,
    }
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("CFTC TFF updated",payload["asOf"])

if __name__=="__main__":
    try:run()
    except Exception as exc:
        print("WARNING COT update failed; preserving previous data:",exc,file=sys.stderr)
        if not OUTPUT.exists():raise
