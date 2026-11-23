'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM, VirtualConsole } = require('jsdom');

const html = fs.readFileSync('index.html','utf8');
const weights = JSON.parse(fs.readFileSync('data/sector_weights.json','utf8'));
const vix = JSON.parse(fs.readFileSync('data/vix_30d.json','utf8'));
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
  assert.equal(doc.querySelectorAll('#history-tbody tr').length,22,'History table items');
  await until(()=>doc.getElementById('vix-current').textContent!=='—','VIX official last close');
  assert.ok(doc.querySelector('#vix-spark polyline'),'VIX historical line');
  assert.ok(doc.getElementById('feed-budget'),'API usage status exists');
  if(withKey) {
    await until(()=>doc.querySelector('#market-grid .market-tile b').textContent.includes('1,25'),'Quote value');
    await until(()=>doc.querySelector('#history-tbody tr td:nth-child(3)').textContent!=='—','History 5D');
    await until(()=>apiCalls.filter(c=>c.type==='history').length===4,'all four ETF history batches');
    assert.equal(apiCalls.filter(c=>c.type==='quote').length,4,'Four requests for 22 ETF quotes');
    assert.equal(apiCalls.filter(c=>c.type==='history').length,4,'Four requests for 22 ETF histories');
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