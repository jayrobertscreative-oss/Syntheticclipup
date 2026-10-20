// Synthetic Clip Up web app. Every number and clip shown here comes from the server.
const NAV=[
 ["dashboard","Dashboard","i-home"],["clipper","AI Auto Clipper","i-scissors"],["generator","AI Video Generator","i-spark",7],
 ["editor","Video Editor","i-film",4],["captions","Caption Studio","i-cc",3],["projects","My Projects","i-folder"],
 ["templates","Templates","i-grid",6],["brand","Brand Kit","i-palette",6],["exports","Export History","i-down",3],
 "-",["billing","Subscription & Credits","i-card",5],["settings","Settings","i-gear",2],["help","Help & Support","i-help",2]];
const PHASE={2:"Accounts & Projects",3:"AI Clipping MVP",4:"Video Editor",5:"Monetisation",6:"Advanced AI",7:"Original Video Generation"};
const PLANNED={
 generator:["Script to video","Story-style videos with narration","Faceless content","AI voiceover from licensed voices"],
 editor:["Timeline with trim and split","Crop, reposition and resize","Text overlays and caption styling","Undo, redo and saved edits"],
 captions:["Editable transcript and timing","Caption restyling after render","More word-highlight animations"],
 templates:["Template library by category","Saved aspect ratio, captions, fonts and colours","Your own custom templates"],
 brand:["Logo, colours and fonts","Saved watermark and caption style","Multiple brand profiles on higher plans"],
 exports:["Export history across projects","720p option","Batch export"],
 billing:["Free, Creator, Pro and Agency plans","Credits estimated before every job","Stripe checkout and billing portal"],
 settings:["Account details and password","Notification preferences","Data export and account deletion"],
 help:["FAQ","Contact and billing support","Report a processing problem with job ID"]};
const STYLES=["Creator Bold","Purple Pulse","Gaming Energy","Podcast Clean","Minimal","Cinematic"];

const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtTime=s=>{s=Math.max(0,s||0);const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=Math.floor(s%60);return(h?h+":":"")+String(m).padStart(h?2:1,"0")+":"+String(x).padStart(2,"0")};
const fmtTs=s=>fmtTime(s)+"."+Math.floor((s%1)*10);
const fmtSize=b=>b>1e9?(b/1e9).toFixed(2)+" GB":(b/1e6).toFixed(1)+" MB";
const fmtDate=t=>new Date(t*1000).toLocaleDateString(undefined,{day:"numeric",month:"short",year:"numeric"});
const ago=t=>{const d=Date.now()/1000-t;return d<60?"just now":d<3600?Math.floor(d/60)+"m ago":d<86400?Math.floor(d/3600)+"h ago":fmtDate(t)};
let key="";try{key=localStorage.getItem("scu-key")||""}catch(e){}
let route="dashboard", param=null, pollTimer=null, health=null, pending=null;

async function api(path,opts={}){
  const r=await fetch(path,{...opts,headers:{...(opts.headers||{}),...(key?{"X-SCU-Key":key}:{})}});
  let body=null;try{body=await r.json()}catch(e){}
  if(r.status===401){showKeyPrompt();throw new Error(body?.error||"Access key required")}
  if(!r.ok) throw new Error(body?.error||`Request failed (${r.status})`);
  return body;
}
function showKeyPrompt(){
  $("#banner").innerHTML=`<div class="banner"><div class="notice warn"><svg><use href="#i-info"/></svg><div style="flex:1">This server is private. Enter its access key.
   <form class="keyform" id="keyForm"><label class="field" style="min-width:200px"><input id="keyIn" type="password" aria-label="Access key" placeholder="Access key"></label><button class="btn primary">Unlock</button></form></div></div></div>`;
  $("#keyForm").onsubmit=e=>{e.preventDefault();key=$("#keyIn").value.trim();try{localStorage.setItem("scu-key",key)}catch(_){}$("#banner").innerHTML="";boot()};
}
function renderBanner(){
  if(!health) return;
  const missing=[];
  if(!health.ffmpeg) missing.push("FFmpeg isn't installed on the server");
  if(!health.speech_to_text) missing.push("speech-to-text has no API key (OPENAI_API_KEY)");
  if(!health.analysis) missing.push("highlight analysis has no API key (ANTHROPIC_API_KEY)");
  $("#banner").innerHTML=missing.length?`<div class="banner"><div class="notice warn"><svg><use href="#i-info"/></svg><span>Clip generation will fail until this is fixed: ${missing.join("; ")}.</span></div></div>`:"";
}

function renderNav(){
  $("#nav").innerHTML=NAV.map(n=>n==="-"?'<div class="navgap"></div>':
   `<button class="nav" data-go="${n[0]}" ${route===n[0]||(route==="project"&&n[0]==="projects")?'aria-current="page"':''} title="${n[1]}"><svg><use href="#${n[2]}"/></svg><span>${n[1]}</span>${n[3]?`<em class="soon">P${n[3]}</em>`:''}</button>`).join("");
}
function go(r,p=null){route=r;param=p;try{history.replaceState(null,"",p?`#${r}-${p}`:`#${r}`)}catch(e){}render()}

function statStrip(s){
  const c=[["Total projects",s.projects],["Clips generated",s.clips],["Clips downloaded",s.downloads],["Minutes processed",s.minutes],["Remaining credits","—"],["Current plan","Free"]];
  $("#planMins").textContent=s.minutes;
  return `<dl class="stats" aria-label="Account statistics">${c.map(([k,v])=>`<div class="stat"><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>`;
}
const pillFor=st=>({queued:"s-queued",processing:"s-processing",ready:"s-ready",failed:"s-failed"}[st]||"s-draft");
function projCards(list){
  if(!list.length) return `<div class="empty"><svg viewBox="0 0 24 24"><use href="#i-folder"/></svg><strong>No projects yet</strong><span>Upload a video you own to create your first clips.</span><button class="btn primary" data-go="clipper">Upload video</button></div>`;
  return `<div class="grid">${list.map(p=>`<article class="proj">
   <div class="thumb" style="background:var(--bg2)">${p.thumb_url?`<img src="${p.thumb_url}" alt="" style="width:100%;height:100%;object-fit:cover">`:`<svg viewBox="0 0 24 24"><use href="#i-play"/></svg>`}${p.duration?`<span class="dur">${fmtTime(p.duration)}</span>`:""}</div>
   <div class="body"><h3>${esc(p.name)}</h3>
   <div class="meta"><span>${fmtDate(p.created_at)}</span><span class="pill ${pillFor(p.status)}">${p.status[0].toUpperCase()+p.status.slice(1)}</span></div>
   <div class="meta"><span>${p.clips?p.clips+" clips":p.status==="failed"?"Failed":"No clips yet"}</span><button class="btn" style="height:32px;padding:0 12px;font-size:13px" data-project="${p.id}">Open project</button></div></div></article>`).join("")}</div>`;
}
function feedHtml(rows){
  if(!rows.length) return `<div class="feed"><ul><li><span></span><p>Nothing yet<span>Finished and failed jobs appear here.</span></p><time></time></li></ul></div>`;
  return `<div class="feed"><ul>${rows.map(r=>`<li><span class="dot" style="background:${r.status==="completed"?"var(--ok)":"var(--err)"}"></span><p>${r.status==="completed"?"Processing finished":"Processing failed"}<span>${esc(r.name)} · ${r.status==="completed"?r.n+" clips":esc((r.error||"").split(": ").slice(1).join(": ")||r.error)}</span></p><time>${ago(r.finished_at)}</time></li>`).join("")}</ul></div>`;
}

const V={};
V.dashboard=async()=>{
  const [s,projects,act]=await Promise.all([api("/api/stats"),api("/api/projects"),api("/api/activity")]);
  return `<div><h1>Welcome back!</h1><p class="sub">Ready to create your next video?</p></div>
  <section class="create" aria-labelledby="qc">
    <div style="position:relative;z-index:1;min-width:0">
      <div class="eyebrow" id="qc">Quick create</div>
      <h2 style="font-size:22px;margin-top:6px">Turn a long video into short clips</h2>
      <form class="urlrow" id="urlForm" novalidate>
        <label class="field"><svg><use href="#i-link"/></svg><input id="url" type="url" placeholder="Paste a YouTube link to check it" aria-label="YouTube URL"></label>
        <button class="btn primary" type="submit" id="urlBtn"><svg width="16" height="16" style="stroke:#fff;fill:none;stroke-width:2"><use href="#i-scissors"/></svg>Generate AI clips</button>
      </form>
      <div class="msg" id="urlMsg" role="status"></div>
      <div id="ytCard"></div>
      <div class="quick">
        <button class="chip" data-go="clipper"><svg><use href="#i-up"/></svg>Upload video</button>
        <button class="chip" data-go="generator"><svg><use href="#i-pen"/></svg>Create from script <span class="soon">P7</span></button>
        <button class="chip" data-go="projects"><svg><use href="#i-folder"/></svg>Open existing project</button>
      </div>
    </div>
    <img class="glyph" src="/static/scu-logo.jpg" alt="">
  </section>
  ${statStrip(s)}
  <div class="cols">
    <section><div class="head"><h2>Recent projects</h2><button class="link" data-go="projects">View all</button></div>${projCards(projects.slice(0,4))}</section>
    <section><div class="head"><h2>Recent activity</h2></div>${feedHtml(act)}</section>
  </div>`;
};
V.projects=async()=>{
  const q=($("#search").value||"").toLowerCase();
  const list=(await api("/api/projects")).filter(p=>!q||p.name.toLowerCase().includes(q));
  return `<div class="head" style="margin:0"><div><h1>My Projects</h1><p class="sub">${q?`Matching “${esc(q)}”`:"Every upload and its clips."}</p></div><button class="btn primary" data-go="clipper">New project</button></div>${projCards(list)}`;
};
V.clipper=async()=>`
  <div><div class="eyebrow">AI Auto Clipper</div><h1 style="margin-top:6px">Upload a video</h1><p class="sub">MP4 or MOV that you own. Speech is transcribed, the best moments are picked by AI, and real MP4 clips are rendered.</p></div>
  <label class="drop" id="drop" for="file">
    <svg viewBox="0 0 24 24"><use href="#i-up"/></svg>
    <strong style="font-family:var(--display)">Drop your video here or tap to browse</strong>
    <span style="color:var(--muted);font-size:13px">MP4 or MOV · up to 2 GB · 20 s to 3 h</span>
    <input type="file" id="file" accept="video/mp4,video/quicktime,.mp4,.mov,.m4v" hidden>
  </label>
  <div class="msg" id="fileMsg" role="status"></div>
  <dl class="fileinfo" id="info" hidden></dl>
  <form class="form" id="settings" hidden>
    <label>Content category<select id="cat"><option>Podcast</option><option>Gaming</option><option>Streaming highlights</option><option>Educational</option><option>Business marketing</option><option>General social</option></select></label>
    <label>Clip length<select id="len"><option value="15">15 s</option><option value="30" selected>30 s</option><option value="45">45 s</option><option value="60">60 s</option></select></label>
    <label>Number of clips<select id="num"><option>3</option><option>5</option><option>8</option><option>10</option></select></label>
    <label>Aspect ratio<select id="ar"><option value="9:16">9:16 vertical</option><option value="1:1">1:1 square</option><option value="16:9">16:9 landscape</option></select></label>
    <label>Framing<select id="fit"><option value="crop">Centre crop</option><option value="pad">Fit with padding</option></select></label>
    <label>Captions<select id="cap"><option value="">No captions</option>${STYLES.map((s,i)=>`<option ${i===0?"selected":""}>${s}</option>`).join("")}</select></label>
    <label>Language<select id="lang"><option value="auto">Auto-detect</option><option value="en">English</option><option value="es">Spanish</option><option value="fr">French</option><option value="de">German</option></select></label>
  </form>
  <div id="go" hidden style="display:grid;gap:14px">
    <label class="consent"><input type="checkbox" id="own">I own this video or have permission to process it.</label>
    <div class="upbar" id="upbar" hidden><i></i></div>
    <div><button class="btn primary" id="startBtn" disabled>Generate AI clips</button></div>
  </div>`;
V.project=async()=>{
  const p=await api(`/api/projects/${param}`);
  const running=p.status==="queued"||p.status==="processing";
  const reached=new Set(p.events.map(e=>e.stage));
  const cur=p.job?.stage, failed=p.status==="failed";
  const detail=k=>{const e=[...p.events].reverse().find(e=>e.stage===k);return e?.detail?esc(e.detail):""};
  const tl=p.stages.map(s=>{
    let cls="";
    if(failed&&s.key===cur) cls="fail";
    else if(s.key===cur&&running) cls="now";
    else if(reached.has(s.key)) cls="done";
    return `<li class="${cls}"><span class="mark"></span><span>${s.label}</span><small>${cls?detail(s.key):""}</small></li>`;}).join("");
  const err=failed?`<div class="notice bad"><svg><use href="#i-info"/></svg><div style="flex:1"><strong>Processing failed</strong><br>${esc((p.job.error||"").split(": ").slice(1).join(": ")||p.job.error)}<div style="margin-top:10px"><button class="btn" id="retryBtn">Retry</button></div></div></div>`:"";
  const ar={"9:16":"r916","1:1":"r11","16:9":"r169"};
  const clips=p.clips.length&&!running?`<section><div class="head"><h2>${p.clips.length} clips</h2><span class="tiny">Scores estimate short-form potential. They don't predict views.</span></div><div class="clips">${p.clips.map(c=>`
    <article class="clip">
      <video class="${ar[c.aspect]}" controls preload="metadata" playsinline poster="${c.thumb_url||""}" src="${c.video_url}"></video>
      <div class="body">
        <div class="meta"><span class="tiny">#${c.rank} · ${esc(c.category||"")}</span><span class="tiny">${fmtTs(c.start)} → ${fmtTs(c.end)} · ${c.duration.toFixed(1)} s</span></div>
        <h3>${esc(c.title)}</h3>
        ${c.hook?`<p class="hook">${esc(c.hook)}</p>`:""}
        <div class="score" aria-label="AI engagement score ${c.score} out of 100"><span>${c.score}</span><span class="bar"><i style="width:${c.score}%"></i></span></div>
        <p class="why">${esc(c.reason)}</p>
        <div class="actions"><button class="btn" disabled title="The editor arrives in Phase 4">Edit</button><a class="btn primary" href="${c.download_url}">Download MP4</a></div>
      </div></article>`).join("")}</div></section>`:"";
  if(running) pollTimer=setTimeout(()=>{if(route==="project"&&param===p.id) render(true)},2000);
  return `<div><div class="eyebrow">Project</div><h1 style="margin-top:6px">${esc(p.name)}</h1>
    <p class="sub">${[p.duration?fmtTime(p.duration):null,p.width?`${p.width}×${p.height}`:null,p.size?fmtSize(p.size):null,`${p.settings.length} s clips`,p.settings.aspect,p.settings.captions?p.settings.caption_style:"No captions"].filter(Boolean).join(" · ")}</p></div>
    ${err}
    ${p.clips.length&&!running?"":`<ol class="timeline" aria-live="polite">${tl}</ol>`}
    ${clips}`;
};
function phaseView(id){
  const n=NAV.find(x=>x[0]===id);
  return `<section class="phase"><div class="eyebrow">Phase ${n[3]} · ${PHASE[n[3]]}</div><h1>${n[1]}</h1><p class="sub" style="margin:0">This area is planned but not built yet. It will include:</p><ul>${PLANNED[id].map(x=>`<li>${x}</li>`).join("")}</ul><div><button class="btn" data-go="dashboard">Back to dashboard</button></div></section>`;
}

async function render(isPoll=false){
  clearTimeout(pollTimer);
  renderNav();
  try{
    const html=V[route]?await V[route]():phaseView(route);
    const keepScroll=isPoll?window.scrollY:0;
    // On polls, leave playing videos alone once clips exist.
    if(isPoll&&document.querySelector(".clip video")&&route==="project") return;
    $("#view").innerHTML=html; wire(); window.scrollTo(0,keepScroll);
  }catch(e){
    $("#view").innerHTML=`<div class="notice bad"><svg><use href="#i-info"/></svg><span>${esc(e.message)}</span></div>`;
  }
}

function wire(){
  const f=$("#urlForm");
  if(f) f.onsubmit=async e=>{
    e.preventDefault();const v=$("#url").value.trim(),m=$("#urlMsg"),card=$("#ytCard");card.innerHTML="";
    if(!v){m.className="msg err";m.textContent="Paste a YouTube link first.";return}
    m.className="msg";m.textContent="Checking the link with YouTube…";$("#urlBtn").disabled=true;
    try{
      const r=await api("/api/youtube/inspect",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:v})});
      if(!r.ok){m.className="msg err";m.textContent=r.error;return}
      m.textContent="";const md=r.metadata;
      card.innerHTML=`<div class="yt">${md?.thumbnail?`<img src="${esc(md.thumbnail)}" alt="">`:`<div class="thumb" style="background:var(--card);border-radius:8px"><svg viewBox="0 0 24 24"><use href="#i-play"/></svg></div>`}
        <div style="min-width:0"><h3>${md?esc(md.title):"Video "+esc(r.video_id)}</h3>
        ${md?`<p>${esc(md.channel)} · ${fmtTime(md.duration_s)} · ${esc(md.privacy)}${md.license==="creativeCommon"?" · Creative Commons licence":""}</p>`:""}
        <p class="${r.accessible?"ok":r.accessible===false?"no":""}">${esc(r.access_note)}</p>
        <p><strong style="color:var(--fg)">Can it be clipped from the link? No.</strong> ${esc(r.media_note)}</p>
        <div style="margin-top:10px"><button class="btn primary" data-go="clipper">Upload the original file</button></div></div></div>`;
    }catch(err){m.className="msg err";m.textContent=err.message}
    finally{$("#urlBtn").disabled=false}
  };
  const file=$("#file");
  if(file){
    const drop=$("#drop");
    ["dragover","dragenter"].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.add("over")}));
    ["dragleave","drop"].forEach(t=>drop.addEventListener(t,()=>drop.classList.remove("over")));
    drop.addEventListener("drop",e=>{e.preventDefault();if(e.dataTransfer.files[0])pick(e.dataTransfer.files[0])});
    file.onchange=()=>file.files[0]&&pick(file.files[0]);
    $("#own").onchange=e=>$("#startBtn").disabled=!(e.target.checked&&pending);
    $("#startBtn").onclick=startUpload;
  }
  const rb=$("#retryBtn");
  if(rb) rb.onclick=async()=>{rb.disabled=true;try{await api(`/api/projects/${param}/retry`,{method:"POST"});render()}catch(e){alertMsg(e.message)}};
}
function alertMsg(t){const m=$("#fileMsg")||$("#urlMsg");if(m){m.className="msg err";m.textContent=t}}

function pick(fl){
  const m=$("#fileMsg");pending=null;
  if(!/\.(mp4|mov|m4v)$/i.test(fl.name)){m.className="msg err";m.textContent="That file isn't an MP4 or MOV. Choose a different video.";return}
  if(fl.size>2*1024**3){m.className="msg err";m.textContent="That file is over 2 GB. Trim it or export at a lower bitrate, then try again.";return}
  m.className="msg";m.textContent="Reading video details…";
  const url=URL.createObjectURL(fl),v=document.createElement("video");v.preload="metadata";
  const show=(d,r)=>{pending=fl;
    $("#info").innerHTML=[["File",esc(fl.name)],["Size",fmtSize(fl.size)],["Duration",d],["Resolution",r]].map(([k,x])=>`<div><dt>${k}</dt><dd>${x}</dd></div>`).join("");
    $("#info").hidden=$("#settings").hidden=$("#go").hidden=false;
    $("#startBtn").disabled=!$("#own").checked;m.textContent="Choose your clip settings.";URL.revokeObjectURL(url)};
  v.onloadedmetadata=()=>show(isFinite(v.duration)?fmtTime(v.duration):"Checked on upload",v.videoWidth?`${v.videoWidth}×${v.videoHeight}`:"Checked on upload");
  v.onerror=()=>show("Checked on upload","Checked on upload");
  v.src=url;
}
function startUpload(){
  if(!pending) return;
  const m=$("#fileMsg"),btn=$("#startBtn"),bar=$("#upbar");
  const cap=$("#cap").value;
  const qs=new URLSearchParams({filename:pending.name,rights:"1",length:$("#len").value,count:$("#num").value,aspect:$("#ar").value,
    fit:$("#fit").value,captions:cap?"1":"0",caption_style:cap||"Creator Bold",category:$("#cat").value,language:$("#lang").value});
  const xhr=new XMLHttpRequest();
  xhr.open("POST","/api/projects?"+qs);
  if(key) xhr.setRequestHeader("X-SCU-Key",key);
  xhr.setRequestHeader("Content-Type","application/octet-stream");
  btn.disabled=true;bar.hidden=false;m.className="msg";
  xhr.upload.onprogress=e=>{if(e.lengthComputable){const pc=Math.round(e.loaded/e.total*100);bar.firstElementChild.style.width=pc+"%";m.textContent=`Uploading… ${pc}% (${fmtSize(e.loaded)} of ${fmtSize(e.total)})`}};
  xhr.onload=()=>{let b={};try{b=JSON.parse(xhr.responseText)}catch(_){}
    if(xhr.status===201){pending=null;go("project",b.project_id)}
    else{m.className="msg err";m.textContent=b.error||`Upload failed (${xhr.status}).`;btn.disabled=false;bar.hidden=true}};
  xhr.onerror=()=>{m.className="msg err";m.textContent="Upload interrupted. Check your connection and try again.";btn.disabled=false;bar.hidden=true};
  xhr.send(pending);
}

document.addEventListener("click",e=>{
  const p=e.target.closest("[data-project]");if(p){go("project",p.dataset.project);$("#app").classList.remove("open");return}
  const g=e.target.closest("[data-go]");if(!g)return;$("#app").classList.remove("open");go(g.dataset.go);
});
$("#menuBtn").onclick=()=>{const a=$("#app");if(matchMedia("(max-width:760px)").matches)a.classList.toggle("open");else a.classList.toggle("collapsed")};
$("#scrim").onclick=()=>$("#app").classList.remove("open");
$("#search").addEventListener("keydown",e=>{if(e.key==="Enter")go("projects")});

async function boot(){
  const h=location.hash.slice(1);
  if(h){const i=h.indexOf("-");route=i>0?h.slice(0,i):h;param=i>0?h.slice(i+1):null}
  try{health=await api("/api/health");renderBanner()}catch(e){}
  render();
}
boot();
