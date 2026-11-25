'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM, VirtualConsole } = require('jsdom');

const html = fs.readFileSync('index.html','utf8');
const weights = JSON.parse(fs.readFileSync('data/sector_weights.json','utf8'));
const vix = JSON.parse(fs.readFileSync('data/vix_30d.json','utf8'));
const cot = JSON.parse(fs.readFileSync('data/cot_tff.json','utf8'));
const macroFixture=JSON.parse(fs.readFileSync('data/macro_indicators.json','utf8'));
const breadthFixture=JSON.parse(fs.readFileSync('data/ndx_breadth.json','utf8'));
const sectorMomentumMock={
  asOf:'2026-11-23',
  source:'State Street ETF NAV test fixture',
  sectors:Object.fromEntries(['XLK','XLF','XLV','XLY','XLC','XLI','XLP','XLE','XLU','XLRE','XLB'].map((key,i)=>[key,{'1D':i===0?2.73:(i-5)*.22,'2W':i===0?6.31:(i-5)*.55,'1M':i===0?9.32:(i-5)*.75}]))
};

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function response(data) {
  return { ok:true, status:200, json:async () => structuredClone(data) };
}
async function scenario(withKey) {
  const errors = [], apiCalls = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', e => errors.push(String(e && (e.stack || e.message || e))));
  const dom = new JSDOM(html, {
    url:'https://zafa77.github.io/FIN-DASHBOARD/',
    runScripts:'dangerously',
    virtualConsole,
    beforeParse(window) {
      if(withKey)window.localStorage.setItem('atlas-td-api-key','DUMMY_TEST_KEY_NEVER_REAL');
      window.setInterval = () => 0;
      const originalTimeout=window.setTimeout.bind(window);
      window.setTimeout=(callback,ms,...args)=>
        originalTimeout(callback, Number(ms)>=50000?2:Number(ms)>=20000?5000:ms, ...args);
      window.fetch=async input => {
        const url=new URL(String(input),window.location.href);
        if(url.pathname.endsWith('/data/sector_weights.json')) return response(weights);
        if(url.pathname.endsWith('/data/vix_30d.json')) return response(vix);
        if(url.pathname.endsWith('/data/cot_tff.json')) return response(cot);
        if(url.pathname.endsWith('/data/sector_performance.json')) return response(sectorMomentumMock);
        if(url.pathname.endsWith('/data/macro_indicators.json')) return response(macroFixture);
        if(url.pathname.endsWith('/data/ndx_breadth.json')) return response(breadthFixture);
        const symbols=(url.searchParams.get('symbol')||'').split(',').filter(Boolean);
        if(url.pathname.endsWith('/quote')) {
          apiCalls.push({type:'quote',symbols});
          const result={};
          symbols.forEach(s=>{result[s]={percent_change:'1.25',close:'101.25',previous_close:'100.00',datetime:'2026-11-23'}});
          return response(result);
        }
        if(url.pathname.endsWith('/time_series')) {
          apiCalls.push({type:'history',symbols});
          const result={};
          symbols.forEach(s=>{
            result[s]={values:Array.from({length:35},(_,i)=>({
              datetime:'2026-11-'+String(Math.max(1,23-i)).padStart(2,'0'),
              close:String(125-i*.2)
            }))};
          });
          return response(result);
        }
        throw Error('Unexpected fetch '+url.toString());
      };
    }
  });
  const doc=dom.window.document;
  async function until(predicate,label) {
    for(let i=0;i<200;i++) {
      if(errors.length)break;
      if(predicate())return;
      await delay(15);
    }
    assert.fail('Not rendered: '+label+'; '+errors.join('\n'));
  }
  await until(()=>doc.querySelectorAll('#spx-heat .heat-cell').length===11,'SPX map');
  assert.equal(doc.querySelectorAll('#growth-heat .heat-cell').length,10,'Growth map items');
  const sectorQuotes=[...doc.querySelectorAll('#sector-momentum-tbody .sector-tv-quote script[src*="embed-widget-single-quote"]')];
  const themeQuote=doc.querySelector('#public-sector-quotes script[src*="embed-widget-market-quotes"]');
  assert.equal(sectorQuotes.length,11,'11 intraday single-quote widgets embedded inside the momentum rows');
  assert.ok(themeQuote,'AI quote list remains available');
  const symbols=sectorQuotes.map(script=>JSON.parse(script.textContent).symbol);
  assert.equal(new Set(symbols).size,11,'Every sector has a distinct live quote');
  assert.ok(symbols.includes('AMEX:XLK') && symbols.includes('AMEX:XLB'),'Sector quotes use SPDR sector ETF symbols');
  assert.equal(JSON.parse(themeQuote.textContent).symbolsGroups[0].symbols.length,7,'Seven AI symbols remain');
  assert.equal(doc.querySelector('#sector-momentum-live'),null,'Duplicate live quote side table removed');
  assert.ok(!doc.querySelector('#sector-momentum').textContent.includes('1D close'),'Historical 1D close column removed');
  assert.equal(doc.querySelectorAll('#sector-momentum-tbody tr[data-sector-symbol]').length,11,'11 static sector rows');
  assert.equal(doc.querySelector('#contributie')!==null,true,'Legacy calculator remains in DOM');
  assert.ok(html.includes('ZAFA MARKET REBORN'),'Public site renamed');
  assert.ok(doc.querySelector('#bias-center + #economic-calendar'),
    'Economic calendar placed immediately after the three bias cards');
  const calendar=doc.querySelector('#economic-calendar details');
  assert.ok(calendar,'Calendar uses a native expandable panel');
  assert.equal(calendar.open,false,'Calendar remains collapsed initially');
  const frame=calendar.querySelector('iframe');
  assert.ok(frame,'Investing.com calendar iframe embedded');
  const url=new URL(frame.src);
  assert.equal(url.origin,'https://sslecal2.investing.com','Official calendar embed host retained');
  assert.equal(url.searchParams.get('columns'),'exc_flags,exc_currency,exc_importance,exc_actual,exc_forecast,exc_previous','User-supplied economic columns retained');
  assert.equal(url.searchParams.get('countries'),'25,32,6,37,72,22,17,39,14,10,35,43,56,36,110,11,26,12,4,5','User-supplied countries retained');
  assert.equal(url.searchParams.get('timeZone'),'68','User-selected calendar timezone retained');
  assert.equal(url.searchParams.get('features'),'datepicker,timezone','Official calendar feature flags retained');
  assert.equal(frame.getAttribute('loading'),'lazy','Economic calendar loads lazily');
  assert.ok(calendar.querySelector('a[href="https://www.investing.com/"]'),'Provider attribution preserved');
  assert.ok(html.includes('.economic-calendar-scroll{max-width:100%;overflow-x:auto'),
    'Horizontal scrolling available on narrow screens');


  assert.equal(doc.querySelectorAll('#history-tbody tr').length,18,'History table items');
  await until(()=>doc.getElementById('vix-current').textContent!=='—','VIX official last close');
  assert.ok(doc.querySelector('#vix-spark polyline'),'VIX historical line');
  await until(()=>doc.querySelectorAll('#vix-history-chart path').length===2,'VIX native historical chart');
  assert.equal(doc.getElementById('vix-chart-current').textContent,doc.getElementById('vix-current').textContent,'VIX charts share the same Cboe closing value');
  assert.equal(doc.querySelector('[data-vix-period="1M"]').getAttribute('aria-pressed'),'true','1M VIX selected initially');
  doc.querySelector('[data-vix-period="3M"]').click();
  assert.equal(doc.querySelector('[data-vix-period="3M"]').getAttribute('aria-pressed'),'true','3M VIX range works');
  assert.ok(doc.getElementById('vix-chart-range').textContent.includes('3M'),'Historical chart updates range');
  assert.ok(doc.querySelectorAll('#vix-history-chart .vix-point').length>=10,'Historical VIX daily points');
  doc.querySelector('[data-vix-period="5D"]').click();
  assert.equal(doc.querySelectorAll('#vix-history-chart .vix-point').length,6,'5D VIX uses six closing observations for five-day change');
  doc.querySelector('[data-vix-period="1M"]').click();
  assert.ok(!html.includes('TVC:VIX|1D'),'Unavailable TradingView VIX embed removed');

  assert.ok(doc.getElementById('feed-budget'),'API usage status exists');
  assert.equal(doc.querySelectorAll('#public-weight-grid .public-weight-item').length,11,'Sector weights public without any key');
  await until(()=>doc.querySelectorAll('#sector-momentum-tbody tr').length===11,'11 sector momentum rows');
  assert.ok(doc.getElementById('sector-momentum-updated').textContent.includes('2026-11-23'),'Sector NAV data date shown');
  const xlkRow=[...doc.querySelectorAll('#sector-momentum-tbody tr')].find(row=>row.textContent.includes('XLK'));
  assert.ok(xlkRow,'Sector XLK row available');
  assert.equal(xlkRow.querySelectorAll('.momentum-cell.extreme').length,2,'Large 2W and 1M moves highlighted clearly');
  assert.ok(xlkRow.textContent.includes('+6,31%'),'NAV 2W return formatted');
  assert.ok(xlkRow.querySelector('[data-return="1M"]').textContent.includes('+9,32%'),'NAV 1M preserved');
  assert.equal(xlkRow.querySelectorAll('.sector-tv-quote').length,1,'Intraday quote and historical returns share one sector row');

  assert.ok(doc.getElementById('sector-momentum-note').textContent.includes('NAV'),'Return type is disclosed');
  const vixPriceWidget=doc.querySelector('.vix-single-widget script[src*="embed-widget-single-quote"]');
  assert.ok(vixPriceWidget,'VIX has numeric intraday broker quote');
  assert.equal(JSON.parse(vixPriceWidget.textContent).symbol,'CAPITALCOM:VIX','VIX quote broker source');
  assert.ok(doc.querySelector('#vix-current.vix-official-value'),'Historical official VIX close labeled separately');
  await until(()=>doc.querySelectorAll('#macro-cpi-chart path').length===2,'CPI historical line');
  assert.equal(doc.getElementById('macro-cpi-value').textContent,
    macroFixture.cpi.yoy.toLocaleString('ro-RO',{minimumFractionDigits:2,maximumFractionDigits:2})+'%',
    'Actual CPI YoY displayed from the official saved series');
  assert.ok(doc.getElementById('macro-cpi-date').textContent.includes(macroFixture.cpi.asOf.slice(0,4)),'CPI report year displayed');
  assert.ok(doc.getElementById('macro-fed-value').textContent.includes(
    macroFixture.fed.upper.toLocaleString('ro-RO',{minimumFractionDigits:2,maximumFractionDigits:2})),
    'Fed target range upper bound displayed');
  assert.ok(doc.querySelectorAll('#macro-fed-chart path').length>=2,'Fed history step chart displayed');
  assert.equal(doc.querySelectorAll('#macro-indicators script[src*="external-embedding/"]').length,0,
    'Restricted DXY TradingView iframes removed');
  await until(()=>doc.querySelectorAll('#macro-dxy-chart path').length===2,'Native DXY chart from FRED basket');
  assert.equal(doc.getElementById('macro-dxy-value').textContent,
    macroFixture.dxy.value.toLocaleString('ro-RO',{minimumFractionDigits:2,maximumFractionDigits:2}),
    'Indicative daily DXY displays calculated FRED/ICE basket value');
  assert.ok(doc.getElementById('macro-dxy-date').textContent.includes(macroFixture.dxy.asOf.slice(0,4)),
    'DXY last observation date disclosed');
  assert.equal(doc.querySelectorAll('#macro-indicators .macro-indicator-card').length,3,'Exactly three compact macro cards');

  await until(()=>doc.getElementById('bias-weekly-label').dataset.signal!=='pending','weekly bias calculated');
  await until(()=>doc.getElementById('bias-daily-label').dataset.signal!=='pending','daily bias calculated');
  await until(()=>doc.getElementById('bias-momentum-label').dataset.signal!=='pending','momentum availability state');
  const evaluator=dom.window.ZafaBiasEngine;
  assert.ok(evaluator,'Bias engine exposed for deterministic logic verification');
  const allData={breadth:breadthFixture,macro:macroFixture,sectors:sectorMomentumMock,vix,cot};
  const weekly=evaluator.labelScore(evaluator.signalsWeekly(allData));
  const daily=evaluator.labelScore(evaluator.signalsDaily(allData));
  assert.equal(doc.getElementById('bias-weekly-label').dataset.signal,weekly.code,'Weekly direction computed from actual EOD factors');
  assert.equal(doc.getElementById('bias-daily-label').dataset.signal,daily.code,'Daily direction computed from actual EOD factors');
  assert.ok(weekly.valid>=4 && daily.valid>=4,'At least four actual inputs required for contextual bias');
  assert.ok(doc.getElementById('bias-context-line').textContent.includes('Weekly:'),
    'Joint textual weekly/daily/momentum interpretation shown');
  assert.ok(doc.getElementById('bias-weekly-count').textContent.includes('factori'),
    'Explainable votes shown, not arbitrary confidence percentages');
  assert.ok(doc.getElementById('bias-weekly-asof').textContent.includes('CFTC'),
    'Weekly factors timestamp and CFTC provenance shown');
  assert.ok(doc.getElementById('bias-daily-asof').textContent.includes('nu date premarket'),
    'Daily score does not falsely claim premarket activity');
  const missing=evaluator.labelScore([]);
  assert.equal(missing.code,'unavailable','Missing inputs never produce bullish/bearish guesses');
  const fakeMomentum={
    status:'active',instrument:'NQ futures continuous, Yahoo NQ=F',
    sessionDate:'2026-11-25',dataAsOf:'2026-11-25T15:45:00+00:00',
    factors:[
      {key:'vwap',name:'VWAP',value:0.2,unit:'%',vote:1},
      {key:'ema',name:'EMA',value:0.3,unit:'%',vote:1},
      {key:'return30m',name:'30m',value:0.4,unit:'%',vote:1},
      {key:'openingRange',name:'ORB',value:'inside',unit:'',vote:0}
    ]
  };
  assert.equal(evaluator.momentumAssessment(fakeMomentum,new Date('2026-11-25T16:00:00Z')).code,'bullish',
    'Three same-direction intraday confirmations produce bullish signal');
  assert.equal(evaluator.momentumAssessment({...fakeMomentum,factors:fakeMomentum.factors.map(f=>({...f,vote:-f.vote}))},
    new Date('2026-11-25T16:00:00Z')).code,'bearish','Inverse confirmations produce bearish signal');
  assert.equal(evaluator.momentumAssessment(fakeMomentum,new Date('2026-11-25T17:00:00Z')).code,'stale',
    'Bars older than 45 minutes must not produce directional momentum');
  assert.equal(evaluator.momentumAssessment(fakeMomentum,new Date('2026-11-25T13:30:00Z')).code,'preopen',
    'Momentum does not falsely treat overnight futures as NY cash-session confirmation');
  assert.equal(evaluator.momentumAssessment(null,new Date('2026-11-25T16:00:00Z')).code,'unavailable',
    'No intraday feed means no directional current-momentum bias');

  await until(()=>doc.getElementById('breadth-advances').textContent===String(breadthFixture.advances),'NDX market breadth');
  assert.equal(doc.getElementById('breadth-declines').textContent,String(breadthFixture.declines),'NDX declines');
  assert.equal(doc.getElementById('breadth-ma20').textContent,breadthFixture.above20Pct.toLocaleString('ro-RO',{minimumFractionDigits:1,maximumFractionDigits:1})+'%','Nasdaq MA20 breadth');
  assert.equal(doc.getElementById('breadth-ma50').textContent,breadthFixture.above50Pct.toLocaleString('ro-RO',{minimumFractionDigits:1,maximumFractionDigits:1})+'%','Nasdaq MA50 breadth');
  assert.ok(doc.getElementById('breadth-date').textContent.includes(breadthFixture.asOf),'EOD date clearly shown');
  assert.ok(doc.getElementById('breadth-coverage').textContent.includes('nu live'),'Nasdaq breadth not mislabeled as live');
  await until(()=>doc.getElementById('us02y-official').textContent!=='—','Official US02Y value');
  assert.equal(doc.getElementById('us02y-official').textContent,macroFixture.us02y.yieldPct.toLocaleString('ro-RO',{minimumFractionDigits:2,maximumFractionDigits:2})+'%','FRED US02Y official value');
  assert.equal(doc.getElementById('us02y-5d').textContent,macroFixture.us02y.fiveDayBp.toLocaleString('ro-RO',{minimumFractionDigits:1,maximumFractionDigits:1})+' bp','5-day bp variation');
  assert.equal(doc.querySelectorAll('#bias-inputs script[src*="embed-widget-single-quote"]').length,0,
    'Restricted US02Y iframe removed');
  await until(()=>doc.querySelectorAll('#us02y-chart path').length===1,'Native FRED US02Y line chart');
  assert.ok(doc.getElementById('us02y-asof').textContent.includes('nu intraday'),
    'Native official yield data clearly labeled non-intraday');
  for(const key of [3,4,5]){
    assert.ok(doc.querySelector('#sector-momentum .sector-momentum-table th:nth-child('+key+')'),
      'Momentum header '+key+' remains for aligned data');
  }
  assert.ok(html.includes('td[data-return] .momentum-cell'),'Shared centered alignment for 2W / 1M badges');
  assert.equal(doc.querySelectorAll('#bias-inputs .card').length,2,'Compact two-card bias inputs');



  assert.equal(doc.querySelectorAll('#sector-pie .sector-pie-slice').length,11,'S&P sector donut has 11 colored slices');
  assert.equal(doc.getElementById('sector-pie-center-value').textContent,'100%','Pie center shows full distribution');
  const techButton=[...doc.querySelectorAll('#public-weight-grid .public-weight-item')].find(x=>x.textContent.includes('XLK'));
  assert.ok(techButton,'XLK legend button');
  techButton.click();
  assert.ok(doc.getElementById('sector-pie-center-label').textContent.includes('Technology'),'Selected slice shows name');
  assert.equal(doc.getElementById('sector-pie-center-value').textContent,weights.weights.XLK.toLocaleString('ro-RO',{minimumFractionDigits:2,maximumFractionDigits:2})+'%','Selected slice matches current issuer weight');
  assert.equal(techButton.getAttribute('aria-pressed'),'true','Pie selection accessible');
  techButton.click();
  assert.equal(doc.getElementById('sector-pie-center-value').textContent,'100%','Toggle pie selection off');
  const macro=doc.getElementById('macro');
  assert.ok(macro.querySelector('#vix-history-chart'),'Native Cboe VIX chart is inside Macro');
  assert.ok(![...macro.querySelectorAll('script[src*="embed-widget-symbol-overview"]')].some(s=>s.textContent.includes('TVC:VIX')),'Restricted VIX embed is absent');
  const cf=macro.querySelector('#vix-live-proxy script[src*="embed-widget-advanced-chart"]');
  assert.ok(cf,'Broker VIX intraday chart embedded');
  const options=JSON.parse(cf.textContent);
  assert.equal(options.symbol,'CAPITALCOM:VIX','Capital.com volatility CFD proxy');
  assert.equal(options.interval,'5','Five-minute candles on initial load');
  assert.ok(macro.querySelector('#vix-official-history details')===null || macro.querySelector('#vix-official-history')!==null,'Official historical series retained');
  assert.equal(macro.querySelector('#vix-official-history').open,false,'Cboe historical details collapsed by default');
  assert.ok(macro.textContent.includes('nu VIX spot oficial'),'Clear separation of CFD and official index');
  assert.ok(doc.querySelector('.ticker-frame script').textContent.includes('CAPITALCOM:VIX'),'VIX CFD displayed in ticker tape');



  assert.equal(doc.querySelector('#feed'),null,'Old section 00 removed from visible page');
  assert.equal(doc.querySelector('#sectoare'),null,'Old section 02 removed from visible page');
  assert.equal(doc.querySelector('nav a[href="#feed"]'),null,'Navigation does not link removed feed');
  assert.equal(doc.querySelector('nav a[href="#sectoare"]'),null,'Navigation does not link removed charts');
  assert.equal(doc.querySelector('#public-market'),null,'Old market overview widget removed');
  assert.equal(doc.querySelector('#public-history'),null,'Old ETF chart widget removed');
  assert.equal(doc.querySelector('#macro .section-title').textContent.includes('02 /'),true,'Macro renumbered');
  assert.equal(doc.querySelector('#cftc .section-title').textContent.includes('03 /'),true,'CFTC renumbered');
  assert.equal(doc.body.classList.contains('no-key'),!withKey,'Public/personal mode selected');

  assert.ok(html.includes('OANDA:SPX500USD') && html.includes('OANDA:NAS100USD'),'OANDA US500/NAS100 CFD feed references');
  assert.ok(!html.includes('TVC:SPX') && !html.includes('NASDAQ:QQQ'),'No prior SPX/QQQ price widgets');
  assert.ok(!html.includes('CME_MINI:ES1!') && !html.includes('CME_MINI:NQ1!'),'No delayed CME widgets in primary dashboard');
  assert.ok(doc.getElementById('instalare').querySelector('details.settings-details'),'Data settings collapsible');
  assert.ok(doc.getElementById('instalare').querySelector('#td-key'),'API key UI preserved');

  await until(()=>doc.querySelectorAll('#cot-weeks tr').length===8,'8 weeks CFTC');
  const nq = cot.markets.NQ.observations.at(-1);
  const es = cot.markets.ES.observations.at(-1);
  assert.ok(doc.getElementById('cot-leveraged-net').textContent.includes(Math.abs(nq.leveragedFunds.net).toLocaleString('ro-RO')),'Real CFTC NQ net leveraged position');
  assert.equal(doc.querySelectorAll('#cot-position-table tr').length,2,'CFTC both investor groups');
  assert.ok(doc.querySelectorAll('#cot-chart polyline').length===2,'CFTC historical %OI lines');
  doc.querySelector('[data-cot-market="ES"]').click();
  await until(()=>doc.getElementById('cot-leveraged-net').textContent.includes(Math.abs(es.leveragedFunds.net).toLocaleString('ro-RO')),'CFTC ES toggle');
  doc.querySelector('[data-cot-market="NQ"]').click();

  if(withKey) {
    await until(()=>doc.querySelector('#market-grid .market-tile b').textContent.includes('1,25'),'Quote value');
    await until(()=>doc.querySelector('#history-tbody tr td:nth-child(3)').textContent!=='—','History 5D');
    await until(()=>apiCalls.filter(c=>c.type==='history').length===3,'all three ETF history batches');
    assert.equal(apiCalls.filter(c=>c.type==='quote').length,3,'Three requests for 18 ETF quotes');
    assert.equal(apiCalls.filter(c=>c.type==='history').length,3,'Three requests for 18 ETF histories');
    assert.ok(apiCalls.every(c=>c.symbols.length<=6),'Never request more than six symbols at a time');
    assert.ok(doc.getElementById('feed-budget').textContent.includes('API:'),'API usage rendered');
  } else {
    assert.equal(apiCalls.length,0,'No key means zero vendor API requests');
  }
  assert.deepEqual(errors,[],'No browser script errors');
  console.log('PASS',withKey?'dummy-key API mode':'no-key mode',{spxTiles:doc.querySelectorAll('#spx-heat .heat-cell').length,historyRows:doc.querySelectorAll('#history-tbody tr').length,vix:doc.getElementById('vix-current').textContent,apiCalls:apiCalls.length});
  dom.window.close();
}
(async()=>{await scenario(false);await scenario(true)})().catch(e=>{console.error('ATLAS SMOKE FAILED',e);process.exitCode=1});