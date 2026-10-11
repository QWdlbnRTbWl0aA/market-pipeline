'use strict';
const $ = id => document.getElementById(id);
let settings, selectedRun, selectedSummary, tab = 'information', busy = false, usageRefresh = null;
const text = (tag, value, cls) => {const n = document.createElement(tag); n.textContent = value; if(cls) n.className=cls; return n;};
async function api(path, options) {const r=await fetch(path,{cache:'no-store',...options});const v=await r.json();if(!r.ok)throw Error(v.error||`HTTP ${r.status}`);return v;}
function notice(message){$('notice').textContent=message;}
function setBusy(value){busy=value;$('collect').disabled=value;$('save-scheduled').disabled=value;}
function trialParameters(){return {niches:$('keywords').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean).map(keywords=>({category:'Trial search',keywords})),limit:$('results-limit').value?Number($('results-limit').value):null,shop_ids:[...new Set($('shop-ids').value.split(/[\s,]+/).filter(Boolean))],exclude_fetched_listings:$('exclude-listings').checked,exclude_fetched_shops:$('exclude-shops').checked};}
function applyScheduled(value, populate=false){
 settings=value;
 $('saved-settings').textContent=`Keywords: ${value.niches.map(n=>n.keywords).join(' · ')} · results limit: ${value.limit??'unlimited'} · shops: ${(value.shop_ids||[]).join(', ')||'all Etsy'}`;
 $('schedule').textContent=`Daily runs ${value.daily_enabled?'enabled':'disabled'} · ${value.daily_time} (${value.timezone}) · ${value.scheduler_enabled?'scheduler running':'scheduler not running'}${value.daily_resume_at&&value.daily_enabled?' · armed from '+timestamp(value.daily_resume_at):''}`;
 $('toggle-daily').textContent=value.daily_enabled?'Disable daily runs':'Enable daily runs';$('toggle-daily').disabled=false;$('toggle-daily').setAttribute('aria-pressed',String(value.daily_enabled));
 const saved={...value};for(const key of ['revision','credentials_present','scheduler_enabled','scheduler_error'])delete saved[key];
 $('current-configuration').textContent=JSON.stringify(saved,null,2);
 if(populate){$('keywords').value=value.niches.map(n=>n.keywords).join('\n');$('results-limit').value=value.limit??'';$('shop-ids').value=(value.shop_ids||[]).join(', ');$('exclude-listings').checked=!!value.exclude_fetched_listings;$('exclude-shops').checked=!!value.exclude_fetched_shops;}
}
async function toggleDaily(){
 $('toggle-daily').disabled=true;
 try{const value=await api('/api/daily-enabled',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!settings.daily_enabled,revision:settings.revision})});applyScheduled(value);notice(value.daily_enabled?'Daily runs enabled for the next scheduled time. No search was started.':'Daily runs disabled. Manual searches remain available.');}
 catch(e){notice(e.message);$('toggle-daily').disabled=false;}
}
async function saveScheduled(){if(!$('search-form').reportValidity())return;try{$('save-scheduled').disabled=true;const value=await api('/api/scheduled-search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parameters:trialParameters(),revision:settings.revision})});applyScheduled(value);notice('Daily configuration saved. No search was started.');}catch(e){notice(e.message+' Reload the page if another tab changed the daily settings.');}finally{$('save-scheduled').disabled=busy;}}
async function start(){try{setBusy(true);notice('Starting trial search…');await api('/api/collect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parameters:trialParameters()})});await poll();}catch(e){setBusy(false);notice(e.message);}}
function progressMessage(job){
 const p=job.progress;if(!p)return 'Starting collection…';
 const counts=`${p.request_count} requests · ${p.listing_count} listings fetched · ${p.shops_fetched} shops fetched`;
 if(p.phase==='waiting'){const seconds=Math.max(0,Math.ceil((new Date(p.resume_at)-Date.now())/1000));return `Waiting to send — rate-limit protection (${seconds}s remaining). ${p.reason}. ${counts}`;}
 if(p.phase==='request_sent')return `Request sent: ${p.endpoint}. Awaiting Etsy response. ${counts}`;
 if(p.phase==='request_stopped')return `Request stopped: ${p.error||p.http_status||'unknown error'}. ${counts}`;
 if(p.phase==='page_saved')return `Search page saved · ${p.pages_fetched} pages · Etsy reports ${shown(p.provider_result_count)} listings. ${counts}`;
 return `${p.phase.replaceAll('_',' ')}${p.http_status?' · HTTP '+p.http_status:''}. ${counts}`;
}
async function poll(){try{const job=await api('/api/job');if(job?.status==='running'){setBusy(true);notice(progressMessage(job));if(job.run_id&&(!selectedRun||selectedRun.run_id!==job.run_id))await openRun(job.run_id);else if(job.run_id&&tab==='information'){if(job.progress.listing_count!==selectedRun.listing_count||job.progress.shops_fetched!==selectedSummary?.shops_fetched)await openRun(job.run_id);else{selectedRun.progress=job.progress;selectedSummary=await api('/api/runs/'+job.run_id+'/summary');render();}}await updateUsage();setTimeout(poll,1000);return;}setBusy(false);if(job){notice(`Collection ${job.status}. ${job.error||'Saved output available in Information.'}`);await loadRuns(job.run_id);await updateUsage();}}catch(e){setBusy(false);notice(e.message);}}
async function refreshDashboard(){await Promise.all([updateUsage(),loadRuns(undefined,true)]);}
async function loadRuns(selectId, newest=false){const rows=await api('/api/runs');$('runs').replaceChildren();if(!rows.length)$('runs').append(text('p','No saved runs yet. Start with a configured trial niche.','muted'));for(const row of rows){const b=text('button','',`run ${selectedRun?.run_id===row.run_id?'selected':''}`);b.dataset.runId=row.run_id;b.append(text('span',row.started_at?new Date(row.started_at).toLocaleString():row.run_id),text('span',`${row.status.toUpperCase()} · ${row.listing_count} listings`,row.status),text('span',row.trigger||'unavailable'));b.onclick=()=>openRun(row.run_id);$('runs').append(b);}if(selectId)await openRun(selectId);else if(newest&&rows.length)await openRun(rows[0].run_id);}
async function openRun(id){try{[selectedRun,selectedSummary]=await Promise.all([api('/api/runs/'+id),api('/api/runs/'+id+'/summary')]);$('download-raw').href='/api/runs/'+id+'/download';$('download-raw').setAttribute('aria-disabled','false');$('result-title').textContent='Saved collection';$('run-status').textContent=selectedRun.status.toUpperCase();$('result-meta').textContent=`${new Date(selectedRun.started_at).toLocaleString()} · ${selectedRun.listing_count} listings · ${selectedRun.run_id}`;render();for(const b of $('runs').children)b.classList.toggle('selected',b.dataset.runId===id);}catch(e){notice(e.message);}}
function sourceLink(label,url){const a=text('a',label);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
function shown(value) { return value == null ? 'unknown' : String(value); }
function listingCard(row) {
  const card = text('article', '', 'listing'); const heading = text('h3', '');
  heading.append(sourceLink(row.title, row.url)); card.append(heading);
  const metrics = text('div', '', 'metrics');
  for (const label of [row.price == null ? 'Price unknown' : `${row.price} ${row.currency || 'currency unknown'}`,
       row.digital == null ? 'Digital type unknown' : row.digital ? 'Digital evidence observed' : 'Physical product',
       row.bestseller === true ? 'Best-seller badge observed' : 'Best-seller status unknown',
       `Views: ${shown(row.listing_views)}`, `Favorites: ${shown(row.listing_favorites)}`,
       `Original creation: ${row.original_created_at ? row.original_created_at.slice(0,10) : 'unknown'}`, `Shop ID: ${shown(row.shop_id)}`]) metrics.append(text('span', label));
  card.append(metrics);
  if (row.tags) card.append(text('p', 'Tags: ' + row.tags.join(' · '), 'tags'));
  const description = text('details', ''); description.append(text('summary', 'Description and available fields'), text('pre', JSON.stringify(row, null, 2))); card.append(description);
  const actions = text('div', '', 'entity-actions');
  const history = text('button', 'Listing history', 'secondary'); history.onclick = () => showHistory('listing', row.listing_id); actions.append(history);
  card.append(actions); return card;
}
function timestamp(value) { return value ? `${new Date(value).toLocaleString()} (browser local) · ${value} (UTC)` : 'unknown'; }
function rawDetails(response, label) {
  const d = text('details', ''); d.append(text('summary', `${label} · HTTP ${response.http_status ?? 'not requested'}`));
  if(response.finished_at)d.append(text('p', `Response received: ${timestamp(response.finished_at)} · ${((new Date(response.finished_at)-new Date(response.requested_at))/1000).toFixed(2)} seconds`, 'muted'));
  d.append(text('p', `Requested: ${timestamp(response.requested_at)}`, 'muted'));
  if (response.error) d.append(text('p', response.error, 'error'));
  if (response.raw_file) d.append(text('p', `Saved file: data/runs/${selectedRun.run_id}/${response.raw_file}`, 'muted'));
  else d.append(text('p', 'No raw response saved for this attempt. Inspect the request status and error.', 'muted'));
  d.append(text('p', response.source_url || response.error || 'No response', 'muted'));
  if (response.effective_parameters) d.append(text('pre', JSON.stringify(response.effective_parameters, null, 2)));
  if (response.raw_file) {
    const url = `/api/runs/${selectedRun.run_id}/raw-file/${response.raw_file}`;
    const p = text('pre', 'Loading raw response…'); d.append(sourceLink('Open raw response as text', url), p);
    d.addEventListener('toggle', async () => { if (d.open && !p.dataset.loaded) { try { const r = await fetch(url); p.textContent = await r.text(); p.dataset.loaded = 'yes'; } catch(e) { p.textContent = e.message; } } });
  }
  return d;
}
function render() {
  const c = $('content'); c.replaceChildren(); $('badge-only').parentElement.hidden = tab !== 'listings';
  if (!selectedRun) return;
  document.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  if (tab === 'listings') {
    for (const query of selectedRun.queries) {
      c.append(text('h3', `${query.niche.category} · ${query.niche.keywords}`));
      if (query.niche.provisional) c.append(text('p', 'Provisional technical trial niche; not a business recommendation.', 'muted'));
      if (query.error) c.append(text('div', query.error, 'error'));
      if (query.pages) c.append(text('p', `${query.pages.length} page attempts · stopped at ${query.pagination_stop} · Etsy total: ${shown(query.provider_result_count)} · ${query.collection_complete?'source exhausted':'review collection coverage'}`, 'muted'));
      for (const row of query.listings.filter(r => !$('badge-only').checked || r.bestseller === true)) c.append(listingCard(row));
    }
    if ($('badge-only').checked && selectedRun.listing_count && !selectedRun.queries.some(q => q.listings.some(r => r.bestseller === true))) c.append(text('p', 'No best-seller badges observed in this sample. Unknown status does not establish that a listing is not a best seller.', 'empty'));
    if (selectedRun.tracked_listings?.length) { c.append(text('h3','Tracked listing observations'));for(const r of selectedRun.tracked_listings)if(r.listing)c.append(listingCard(r.listing));else c.append(text('p',r.error||r.status,'error')); }
    else if (!selectedRun.listing_count) c.append(text('p', 'No listing data was retrieved. Raw error responses are retained; this run is not usable for market research.', 'empty'));
  } else if (tab === 'information') { renderInformation(c);
  } else if (tab === 'shops') {
    if (!selectedRun.shops?.length) c.append(text('p', 'No shop observations saved for this run. Shop counters cannot be recovered from listing-only responses.', 'empty'));
    for (const record of selectedRun.shops || []) {
      c.append(text('h3', `Shop ${record.shop_id} · ${record.shop?.shop_name || record.status}`));
      if (record.error) c.append(text('p', record.error, 'error'));
      const shop = record.shop; if (!shop) continue;
      c.append(text('p', `Shop-wide sold transactions: ${shown(shop.transaction_sold_count)} · Active listings: ${shown(shop.listing_active_count)} · Shop favorites: ${shown(shop.shop_favorites)}`, 'muted'));
      c.append(text('p', 'These counters belong to the whole shop, not an individual listing.', 'muted'));
      const actions = text('div', '', 'entity-actions'); const history = text('button', 'Shop history', 'secondary'); history.onclick = () => showHistory('shop', shop.shop_id);
      actions.append(history); c.append(actions);
      const d = text('details', ''); d.append(text('summary', 'Shop fields and provenance'), text('pre', JSON.stringify(shop, null, 2))); c.append(d);
    }
  }
}

async function showHistory(kind, identity) {
  try {
    const rows = await api(`/api/history/${kind}/${identity}`); const c = $('content'); c.replaceChildren(text('h3', `${kind} ${identity} · saved observations`));
    if (!rows.length) { c.append(text('p', 'No observations saved yet.', 'empty')); return; }
    const table = text('table', '', 'history-table'); const names = kind === 'listing' ? ['observed_at','listing_views','listing_favorites','price','currency','state'] : ['observed_at','transaction_sold_count','listing_active_count','shop_favorites'];
    const header = text('tr',''); names.forEach(n => header.append(text('th',n.replaceAll('_',' ')))); table.append(header);
    for (const entry of rows.slice(0,100)) { const row = text('tr',''); names.forEach(n => row.append(text('td',shown(entry[n])))); table.append(row); } c.append(table);
    const back = text('button','Back to run','secondary'); back.onclick = render; c.append(back);
  } catch (e) { notice(e.message); }
}
function updateUsage(){if(usageRefresh)return usageRefresh;usageRefresh=fetchUsage().finally(()=>{usageRefresh=null;});return usageRefresh;}
async function fetchUsage() {
  try {
    const usage = await api('/api/usage');
    $('usage-five').textContent = usage.last_5_minutes;
    $('usage-day').textContent = usage.last_24_hours;
    $('usage-note').textContent = `Counts refreshed: ${new Date(usage.checked_at).toLocaleString()}. ` + usage.scope + ' Five minutes is an activity window; Etsy limits per second and rolling 24 hours.';
    const q=usage.quota;
    if(q){const wait=q.wait_seconds==null?'Cannot send with current budgets':q.ready?'Ready to send':`Waiting ${Math.ceil(q.wait_seconds)}s · next estimated slot ${timestamp(q.next_available_at)}`;
      $('quota-note').textContent=`Quota protection: ${q.effective_daily_ceiling} requests allowed in the rolling window (${q.provider_limit??'unknown'} Etsy allowance; ${q.reserve} reserved${q.reserve_percent!=null?` / ${q.reserve_percent}%`:''}). ${q.safe_requests_available} safe slots available. ${wait}. Last observed remaining: ${q.last_observed_remaining??'unknown'}; projected: ${q.projected_remaining??'unknown'}. Recovery is estimated from saved history; Etsy bucket timing and other key users can differ.`;
    }else $('quota-note').textContent='Quota information unavailable.';
  } catch (error) { $('usage-five').textContent = '—'; $('usage-day').textContent = '—'; $('usage-note').textContent = 'Request counts unavailable: ' + error.message; }
}

function renderInformation(c){
 renderStatistics(c);
 const run=selectedRun, queries=run.queries||[];
 const attempts=[...queries.flatMap(q=>q.pages||[q]),...(run.tracked_listings||[]),...(run.shops||[])];
 const completedShops=(run.shops||[]).filter(r=>r.shop).length;
 const discovered=new Set(queries.flatMap(q=>q.listings||[]).map(r=>r.shop_id).filter(Boolean)).size;
 const duration=run.finished_at?(new Date(run.finished_at)-new Date(run.started_at))/1000:null;
 const table=text('table','');
 const entries=[['Status',run.status],['Started',timestamp(run.started_at)],['Finished',timestamp(run.finished_at)],['Duration',duration==null?'In progress':`${duration.toFixed(1)} seconds`],['Trigger',run.trigger],['API source',run.settings?.source||'unknown'],['API requests',run.progress?.request_count??run.request_count??attempts.filter(r=>r.http_status!=null).length],['Requests with HTTP 200',attempts.filter(r=>r.http_status===200).length],['Failed HTTP responses',attempts.filter(r=>r.http_status!=null&&r.http_status!==200).length],['Skipped requests',attempts.filter(r=>r.status==='skipped').length],['Raw responses saved',attempts.filter(r=>r.raw_file).length],['Throttle waits',(run.throttle_waits||[]).length],['Throttle wait time',`${(run.throttle_waits||[]).reduce((sum,w)=>sum+w.seconds,0).toFixed(2)} seconds`],['Listings fetched',run.listing_count],['Shops discovered',run.shop_coverage?.discovered??discovered],['Shops fetched',completedShops],['Shop attempts',(run.shops||[]).length],['Stop reason',run.stop_reason||'None recorded']];
 for(const q of queries)entries.push(['Search',q.niche.keywords],['Listings reported by Etsy',shown(q.provider_result_count)],['Search pages',(q.pages||[q]).length],['Search stopped',q.pagination_stop||q.status],['Previously fetched listing rows excluded',q.excluded_listing_count??0],['Previously fetched shop rows excluded',q.excluded_shop_listing_count??0],['Search coverage',q.collection_complete===true?'All reported results retrieved':q.collection_complete===false?'Incomplete — see stop reason':'Legacy run; inspect reported/fetched counts']);
 for(const [label,value] of entries){const row=text('tr','');row.append(text('th',label),text('td',shown(value)));table.append(row);}c.append(table);
 c.append(text('p','A broad keyword can include physical products. Etsy pagination and quota limits may prevent collecting every reported result.','muted'));
 c.append(sourceLink('Open snapshot JSON',`/api/runs/${run.run_id}`));
 if(run.request_plans?.length){const d=text('details','');d.append(text('summary','Request plans and rate-limit waits'),text('pre',JSON.stringify({plans:run.request_plans,waits:run.throttle_waits||[]},null,2)));c.append(d);}
 for(const q of queries)(q.pages||[q]).forEach((r,i)=>c.append(rawDetails(r,`Search page ${i+1}`)));
 for(const r of run.tracked_listings||[])c.append(rawDetails(r,`Listing ${r.listing_id}`));
 for(const r of run.shops||[])c.append(rawDetails(r,`Shop ${r.shop_id}`));
 if(run.dqa){const d=text('details','');d.append(text('summary','Data quality details'),text('pre',JSON.stringify(run.dqa,null,2)));c.append(d);}
}
function renderStatistics(c){
 const s=selectedSummary;if(!s)return;
 const cards=text('div','','summary-grid');
 for(const [label,value] of [['Available reported · queried sources',s.reported_available],['Unique listings fetched',s.unique_listings],['Shops in returned listings',s.distinct_shops_in_returned_listings],['Estimated remaining listing calls · full query',s.estimated_remaining_listing_requests_full_query],['Known shop calls remaining',s.known_shop_detail_requests_remaining],['Selected shops not yet searched',s.selected_shop_initial_search_requests_remaining]]){const card=text('div','','stat-card');card.append(text('strong',shown(value)),text('span',label));cards.append(card);}c.append(cards);
 c.append(text('p',s.estimate_note,'muted'));
 for(const q of s.query_estimates)c.append(text('p',`${q.shop_id?'Shop '+q.shop_id:'Etsy search'}: ${shown(q.reported_available)} reported (${q.reported_count_scope}); ${q.matching_listings_fetched} matching fetched; ${shown(q.listing_pages_remaining_within_provider_offset)} estimated listing calls within Etsy pagination range.`, 'muted'));
 if(s.selected_shop_search_coverage)c.append(text('p',`Selected shops: ${s.selected_shop_search_coverage.queried}/${s.selected_shop_search_coverage.selected} searched. Other selected shops may not be queried once the result limit is met.`,'muted'));
 const distributions=text('div','','distribution-grid');
 function distribution(label,rows){const panel=text('section','','distribution');panel.append(text('h3',label));const table=text('table','');for(const [name,count] of rows.slice(0,50)){const tr=text('tr','');tr.append(text('td',name),text('td',count));table.append(tr);}panel.append(table);if(rows.length>50)panel.append(text('p',`Showing 50 of ${rows.length}; all counts are in the download.`,'muted'));distributions.append(panel);}
 distribution('Returned categories · taxonomy IDs',s.categories.map(r=>[r.taxonomy_id==null?'Unknown':String(r.taxonomy_id),r.listing_count]));
 distribution('Returned shops',s.shops.map(r=>[r.shop_name?`${r.shop_name} (${r.shop_id})`:shown(r.shop_id),r.listing_count]));
 distribution('Product types',Object.entries(s.digital));c.append(distributions);
 const detail=text('details','');detail.append(text('summary','Full statistics and request estimates'),text('pre',JSON.stringify(s,null,2)));c.append(detail);
}
async function updatePipeline(){
 try{
  const state=await api('/api/pipeline');
  $('pipeline-note').textContent=`${state.execution_enabled?'Reviewed execution enabled':'Refinement execution disabled'} · ${state.counts.pending_proposals} proposals awaiting review · supervisor ${state.supervisor.status}. Existing daily searches use their saved configuration.`;
  $('pipeline-proposals').replaceChildren();$('pipeline-cohorts').replaceChildren();$('pipeline-timeline').replaceChildren();$('pipeline-workers').replaceChildren();
  function proposal(row,cohort=false){
   const box=text('details','');const manifest=row.manifest;if(!manifest)return;
   const key=cohort?row.cohort_id:row.proposal_id;
   box.append(text('summary',`${cohort?'Tracking cohort':'Search proposal'} · ${row.status}`));
   box.append(text('pre',JSON.stringify(manifest,null,2)),text('p','Exact manifest SHA256: '+row.manifest_sha256,'muted'));
   if(['awaiting_approval','paused','approved','active'].includes(row.status)){
    const review=text('label','');const check=document.createElement('input');check.type='checkbox';review.append(check,document.createTextNode(cohort?' I reviewed these identities, dates and request bounds.':' I reviewed these phrases, request bounds, reference listings and the 10 percentage-point relevance rubric.'));box.append(review);
    for(const [action,label] of (cohort?[['approve','Approve cohort'],['pause','Pause future tracking'],['cancel','Cancel future tracking']]:[['approve','Approve bounded trial'],['reject','Reject'],['pause','Pause queued trial'],['cancel','Cancel queued trial']])){
     const button=text('button',label,'secondary');button.type='button';button.onclick=async()=>{
      if(action==='approve'&&!check.checked){notice('Review the exact manifest and check the confirmation first.');return;}
      const payload={action,manifest_sha256:row.manifest_sha256,reviewer:'dashboard operator'};
      if(action==='approve'&&!cohort)payload.reference={rubric_accepted:true,minimum_relevance_gain:manifest.comparison_policy.minimum_relevance_gain,reference_listing_ids:[...new Set(manifest.phrases.flatMap(p=>p.listing_ids))]};
      button.disabled=true;
      try{await api(`/api/pipeline/${cohort?'cohorts':'proposals'}/${key}/decision`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});notice('Decision saved. '+(state.execution_enabled?'Only approved bounded work can queue.':'Execution remains disabled; no source requests were sent.'));await updatePipeline();}catch(e){notice(e.message);}finally{button.disabled=false;}
     };box.append(button);
    }
   }
   if(!cohort&&row.comparison){
    box.append(text('h3','Saved blind review sample'),text('pre',JSON.stringify(row.comparison.review_sample||[],null,2)));
    if(row.status==='awaiting_human_labels'){
     const input=document.createElement('textarea');input.rows=6;input.placeholder='JSON labels by listing ID: {"123":"relevant","456":"irrelevant"}';input.setAttribute('aria-label','Human relevance labels');box.append(input);
     const submit=text('button','Save reviewed relevance labels','secondary');submit.type='button';submit.onclick=async()=>{
      try{const labels=JSON.parse(input.value);await api(`/api/pipeline/proposals/${key}/labels`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({snapshot_sha256:row.comparison.snapshot_sha256,reviewer:'dashboard operator',labels})});notice('Comparison review saved. Daily configuration is unchanged.');await updatePipeline();}catch(e){notice(e.message);}
     };box.append(submit);
    }
   }
   return box;
  }
  for(const row of state.proposals){const box=proposal(row);if(box)$('pipeline-proposals').append(box);}
  for(const row of state.cohorts){const box=proposal(row,true);if(box)$('pipeline-cohorts').append(box);}
  const table=text('table','');for(const row of state.timeline.slice(0,80)){const tr=text('tr','');tr.append(text('td',timestamp(row.at)),text('td',row.stage),text('td',row.status+(row.delivery_status?' / '+row.delivery_status:'')),text('td',row.source_run_id||row.root_cycle_id||'unknown'));table.append(tr);}$('pipeline-timeline').append(table);
  async function operation(stage,action,record_id){try{const result=await api('/api/pipeline/operations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stage,action,record_id,reason:'Explicit dashboard operator action'})});notice(`${stage}: ${result.status}. Active work and safety ledgers are preserved.`);await updatePipeline();}catch(e){notice(e.message);}}
  for(const row of state.supervisor.services||[]){
   const worker=text('div','');worker.append(text('p',`${row.name}: ${row.status} · ${row.readiness||'readiness pending'} · ${row.restart_count} restarts`,'muted'));
   if(['collector','controller','product','search_refinement','market_insights'].includes(row.name)){const button=text('button',row.paused?'Resume admission':'Pause admission','secondary');button.onclick=()=>operation(row.name,row.paused?'resume':'pause','0'.repeat(64));worker.append(button);}$('pipeline-workers').append(worker);
  }
  for(const row of state.timeline.filter(r=>['search_refinement','market_insights'].includes(r.stage)&&/^[a-f0-9]{64}$/.test(r.job_id)&&['failed','budget_waiting','running'].includes(r.status))){
   const line=text('p',`${row.stage} ${row.source_run_id}: ${row.status} `);
   for(const action of ['reconcile','retry']){const button=text('button',action==='reconcile'?'Reconcile saved delivery':'Explicit stage retry','secondary');button.onclick=()=>operation(row.stage,action,row.job_id);line.append(button);}$('pipeline-workers').append(line);
  }
 }catch(e){$('pipeline-note').textContent='Pipeline status unavailable: '+e.message;}
}
async function init(){
 setBusy(true);
 $('pipeline-refresh').onclick=updatePipeline;
 $('search-form').onsubmit=e=>{e.preventDefault();start();};$('save-scheduled').onclick=saveScheduled;$('toggle-daily').onclick=toggleDaily;
 $('refresh').onclick=()=>refreshDashboard().catch(e=>notice(e.message));$('badge-only').onchange=render;
 $('download-raw').onclick=e=>{if(!selectedRun){e.preventDefault();notice('Select a saved run first.');}};
 document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;render();});
 // Critical panels start immediately; configuration and shops cannot gate them.
 const primary=[loadRuns().catch(e=>{$('runs').textContent='Saved runs unavailable: '+e.message;}),updateUsage()];
 const configuration=api('/api/config').then(value=>{applyScheduled(value,true);setBusy(false);}).catch(e=>notice('Configuration unavailable: '+e.message));
 setInterval(updateUsage,15000);window.addEventListener('focus',updateUsage);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)updateUsage();});
 await Promise.all([...primary,configuration]);
 updatePipeline();setInterval(updatePipeline,30000);
 // Suggestions load after critical panels; no full snapshot is fetched on load.
 api('/api/shops').then(shops=>{for(const shop of shops){const option=text('option',shop.shop_name||shop.shop_id);option.value=shop.shop_id;$('known-shops').append(option);}}).catch(e=>notice('Shop suggestions unavailable: '+e.message));
 try{const job=await api('/api/job');if(job?.status==='running')poll();}catch(e){notice(e.message);}
}
init();
