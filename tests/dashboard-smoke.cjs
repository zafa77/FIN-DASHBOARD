'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM, VirtualConsole } = require('jsdom');

const html = fs.readFileSync('index.html','utf8');
const weights = JSON.parse(fs.readFileSync('data/sector_weights.json','utf8'));
const vix = JSON.parse(fs.readFileSync('data/vix_30d.json','utf8'));
const cot = JSON.parse(fs.readFileSync('data/cot_tff.json','utf8'));

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
  const publicQuotes=doc.querySelectorAll('#public-sector-quotes script[src*="embed-widget-market-quotes"]');
  assert.equal(publicQuotes.length,2,'Two public TradingView quote tables');
  const cfg=[...publicQuotes].map(el=>JSON.parse(el.textContent));
  assert.equal(cfg[0].symbolsGroups[0].symbols.length,11,'11 sector symbols');
  assert.equal(cfg[1].symbolsGroups[0].symbols.length,7,'7 AI symbols');
  assert.equal(doc.querySelector('#contributie')!==null,true,'Legacy calculator remains in DOM');
  assert.ok(html.includes('ZAFA MARKET REBORN'),'Public site renamed');

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
  assert.equal(doc.querySelectorAll('#sector-pie .sector-pie-slice').length,11,'S&P sector donut has 11 colored slices');
  assert.equal(doc.getElementById('sector-pie-center-value').textContent,'100%','Pie center shows full distribution');
  const techButton=[...doc.querySelectorAll('#public-weight-grid .public-weight-item')].find(x=>x.textContent.includes('XLK'));
  assert.ok(techButton,'XLK legend button');
  techButton.click();
  assert.ok(doc.getElementById('sector-pie-center-label').textContent.includes('Technology'),'Selected slice shows name');
  assert.ok(doc.getElementById('sector-pie-center-value').textContent.includes('34,30'),'Selected slice shows current issuer weight');
  assert.equal(techButton.getAttribute('aria-pressed'),'true','Pie selection accessible');
  techButton.click();
  assert.equal(doc.getElementById('sector-pie-center-value').textContent,'100%','Toggle pie selection off');
  const macro=doc.getElementById('macro');
  assert.ok(macro.querySelector('#vix-history-chart'),'Native Cboe VIX chart is inside Macro');
  assert.ok(![...macro.querySelectorAll('script[src*="embed-widget-symbol-overview"]')].some(s=>s.textContent.includes('TVC:VIX')),'Restricted VIX embed is absent');


  assert.ok(doc.querySelector('#public-market script[src*="embed-widget-market-overview"]'),'Free market watchlist embedded');
  assert.ok(doc.querySelector('#public-history script[src*="embed-widget-symbol-overview"]'),'Public history chart embedded');
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