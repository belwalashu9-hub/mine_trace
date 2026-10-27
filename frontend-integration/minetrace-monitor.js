/* Drop-in, dependency-free component. No remote news is inserted as HTML. */
class MineTraceMonitor extends HTMLElement {
  connectedCallback() {
    this.root = this.attachShadow({mode:'open'});
    this.root.innerHTML = `<style>
      :host{display:block;font:15px system-ui;color:#dce9ed;background:#101d28;padding:24px;border-radius:16px}
      h2{font-size:24px} button{padding:10px;border:1px solid #58b9b5;border-radius:6px;background:#193846;color:inherit;cursor:pointer}
      article{padding:14px;border-bottom:1px solid #37505e} a{color:#79d8d4} p{line-height:1.5}
      pre{white-space:pre-wrap} svg{width:100%;background:#172d3c;border:1px solid #37505e} .muted{color:#a2b7c5}
    </style><h2>MineTrace · Near-real-time geopolitical monitoring</h2>
    <p class="muted">Candidate corridors only. News reports do not prove closure or shipment availability.</p>
    <button id="refresh">Refresh cached results</button> <button id="sync">Fetch GDELT and reassess</button>
    <p id="status" role="status"></p><div id="summary"></div>
    <h3>Candidate route geometry · schematic longitude / latitude</h3><svg viewBox="0 0 720 360" aria-label="Candidate route geometry"></svg>
    <h3>Recent reported events</h3><div id="events"></div><h3>Routes and evidence</h3><div id="routes"></div><pre id="detail"></pre>`;
    this.root.querySelector('#refresh').onclick = () => this.refresh();
    this.root.querySelector('#sync').onclick = async () => {
      this.root.querySelector('#sync').disabled=true;
      try { await this.api('/sync?source=live',{method:'POST'}); await this.refresh(); }
      catch(e){this.status(e.message);} finally{this.root.querySelector('#sync').disabled=false;}
    };
    this.refresh();
  }
  status(text){this.root.querySelector('#status').textContent=text;}
  async api(path,options={}){
    const r=await fetch((this.getAttribute('api-base') || 'http://127.0.0.1:8000')+'/api/v1/live'+path,options);
    if(!r.ok)throw Error(`Backend request failed (${r.status}). Cached data may be stale.`);
    return r.json();
  }
  async refresh(){
    this.status('Loading cached evidence…');
    try{
      const [summary,events,routes]=await Promise.all([this.api('/dashboard/summary'),this.api('/events'),this.api('/routes')]);
      this.status(`Last sync: ${summary.system_status.last_sync_timestamp || 'never'} · ${summary.system_status.last_sync_status}`);
      this.root.querySelector('#summary').textContent=`${summary.overview.active_geopolitical_events} events · ${summary.overview.routes_under_alert} routes under alert`;
      const feed=this.root.querySelector('#events');feed.replaceChildren();
      if(!events.items.length)feed.textContent='No classified reports in this database.';
      for(const e of events.items){const card=document.createElement('article');
        const title=document.createElement('strong');title.textContent=(e.synthetic?'SYNTHETIC DEMO · ':'')+e.title;card.append(title);
        const p=document.createElement('p');p.textContent=`${e.event_type} · ${e.verification_status} · ${e.affected_country || 'location unknown'} · ${e.mineral_relevance}`;card.append(p);
        for(const evidence of e.evidence){try{const url=new URL(evidence.source_url);if(!['http:','https:'].includes(url.protocol))continue;
          const a=document.createElement('a');a.href=url.href;a.textContent=' Source ';a.target='_blank';a.rel='noopener noreferrer';card.append(a);}catch{}}
        feed.append(card);
      }
      const list=this.root.querySelector('#routes'),svg=this.root.querySelector('svg');list.replaceChildren();svg.replaceChildren();
      for(const r of routes.routes){
        const card=document.createElement('article'),button=document.createElement('button');
        button.textContent=r.name+' · '+r.operability_status;
        button.onclick=async()=>{try{this.root.querySelector('#detail').textContent=JSON.stringify(await this.api('/routes/'+encodeURIComponent(r.route_id)+'/explanation'),null,2);}catch(e){this.status(e.message);}};
        card.append(button);const p=document.createElement('p');p.textContent=r.designation+' · '+r.shipment_feasibility;card.append(p);list.append(card);
        const c=r.geometry?.coordinates || [];
        for(let i=1;i<c.length;i++){
          if(Math.abs(c[i][0]-c[i-1][0])>180)continue; // avoid false world-spanning date-line links
          const line=document.createElementNS('http://www.w3.org/2000/svg','line');
          for(const [key,val] of Object.entries({x1:(c[i-1][0]+180)*2,y1:(90-c[i-1][1])*2,x2:(c[i][0]+180)*2,y2:(90-c[i][1])*2,stroke:r.operability_status==='AT_RISK'?'#ffad69':'#61d5c9','stroke-width':2}))line.setAttribute(key,val);
          svg.append(line);
        }
      }
    }catch(e){this.status('Offline or unavailable: '+e.message);}
  }
}
customElements.define('minetrace-monitor',MineTraceMonitor);
