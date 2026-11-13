'use strict';
/* The page only observes. Formal CLI remains the sole native task writer. */
const D = globalThis.WorkbenchData;
const C = globalThis.WorkbenchConfig;
const cacheKey = name => 'super-ledger:'+C.projectId+':'+name;
const $ = id => document.getElementById(id);
const API = '/api/workbench/';
const labels = {waiting:'等待接手',running:'执行中',idle:'未领取',ended:'正式结束'};
const evidenceLabels = {current:'当前匹配',changed:'产物或输入已变',missing:'文件缺失',invalid:'证据无效','not-rechecked':'历史登记，本次未复核','not-ended':'尚未结束',unverified:'历史证据不完整','needs-revalidation':'需要重新验收'};
const deliveryLabels = {review:'待独立审核',source:'待补源',implementation:'待继续实施',integration:'待核候选/合入',external:'外部阻塞',dependency:'依赖阻塞'};
const viewLabels = [['waiting','优先接手收尾'],['review','待独立审核'],['publication','待发布 / 复验'],['implementation','实施 / 补源'],['coordination','占用 / 交接修复'],['all','全部任务'],['integrated','已合入'],['verified','已实测'],['ended','正式结束'],['maintenance','台账维护']];
let preferences = {};
try { preferences = JSON.parse(localStorage.getItem(cacheKey('preferences')) || '{}'); } catch {}
const state = {view:preferences.view || 'all',focus:preferences.focus || 'all',q:preferences.q || '',packageId:preferences.packageId || '',owner:preferences.owner || '',page:0,selection:D.decodeSelection(location.hash)};
let model = null, manifest = null, etag = '', refreshing = false, lastRead = '', connectionState = 'loading';
let detailSequence = 0, currentDetail = null, retryTimer = null, retries = 0, detailAbort = null;
const detailCache = new Map();
let maintenanceValue=null,maintenanceETag='',maintenanceJSON='';
let expiredReloadPending=false;
const laneLabels={'independent-review':'独立收尾','publication-review':'核发布 / 复验','bounded-implementation':'有界实施','targeted-source':'定向补源','handoff-repair':'修复交接','package-review':'整包审核',active:'核执行占用',closed:'已结束','root-scene':'根场景复验','source-assessment':'实施前核对'};
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key,value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2),value);
    else if (value !== null && value !== undefined) node.setAttribute(key,String(value));
  }
  for (const child of Array.isArray(children) ? children : [children]) if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}
function button(text,action,attrs={}) { return el('button',{type:'button',onclick:action,...attrs},[text]); }
function savePreferences() {
  try {localStorage.setItem(cacheKey('preferences'),JSON.stringify({view:state.view,focus:state.focus,q:state.q,packageId:state.packageId,owner:state.owner}));} catch {}
}
function localTime(value) {const d=new Date(value);return value && !Number.isNaN(d.valueOf()) ? d.toLocaleString('zh-CN',{hour12:false}) : '未记录';}
function age(value) {const n=Math.floor((Date.now()-new Date(value).valueOf())/60000);return Number.isFinite(n) ? n<0 ? '登记时间在未来，待核' : n<1 ? '刚登记' : `登记 ${n} 分钟前` : '时间未知';}
function status(text,kind='loading') {connectionState=kind;$('connection').textContent=text;$('connection').dataset.state=kind;}
function isCurrent() {return connectionState==='current' && manifest?.readiness?.ready===true && Date.now()-new Date(manifest.auditedAt).valueOf()<=300000;}
function cacheSnapshot() {
  try {localStorage.setItem(cacheKey('readonly-cache'),JSON.stringify({summary:model.summary,rows:model.rows,manifest}));} catch {}
}
function restoreReadonly() {
  try {
    const saved=JSON.parse(localStorage.getItem(cacheKey('readonly-cache')) || 'null');
    if (!saved) return;
    D.validateManifest(saved.manifest);D.validateShard(saved.summary,saved.manifest.snapshotId,'summary');D.validateShard({schema:'super-ledger/workbench-tasks@1',snapshotId:saved.manifest.snapshotId},saved.manifest.snapshotId,'tasks');
    if (!Array.isArray(saved.rows) || saved.rows.length!==saved.summary.counts.total) return;
    model={summary:saved.summary,rows:saved.rows};manifest=saved.manifest;
    status('正在显示上次成功读取的缓存，仅供查看；正在重新连接服务。','offline');renderAll();
  } catch {}
}
async function refreshRoster(manual=false) {
  if (refreshing) return;
  refreshing=true;$('refresh').disabled=true;$('refresh').textContent='正在读取…';
  const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),10000);
  try {
    const response=await fetch(API+'manifest',{headers:etag?{'If-None-Match':etag}:{},cache:'no-cache',signal:abort.signal});
    if (response.status!==304) {
      if (!response.ok) throw new Error(`服务尚无可用视图（HTTP ${response.status}），后台将继续构建。`);
      const next=D.validateManifest(await response.json());
      if (!model || next.snapshotId!==manifest?.snapshotId) {
        const base=API+'snapshots/'+next.snapshotId+'/';
        const [summary,tasks]=await Promise.all([
          D.shard(base+'summary',next.snapshotId,'summary',null,next.files.summary.sha256,abort.signal),
          D.shard(base+'tasks',next.snapshotId,'tasks',null,next.files.tasks.sha256,abort.signal)
        ]);
        if (!Array.isArray(tasks.items) || tasks.items.length!==summary.counts.total || tasks.items.length!==tasks.total) throw new Error('任务总数不一致，拒绝混用不同快照。');
        const keys=new Set(tasks.items.map(r=>r.packageId+'/'+r.taskId));if(keys.size!==tasks.items.length)throw new Error('任务键重复，拒绝本次视图。');
        model={summary,rows:tasks.items};manifest=next;detailCache.clear();renderAll();
        if(state.selection) loadDetail(state.selection,false);
      } else manifest=next;
      etag=response.headers.get('ETag') || '';
    }
    if (!model || !manifest) throw new Error('尚未取得有效快照。');
    lastRead=new Date().toISOString();retries=0;clearTimeout(retryTimer);
    const current=manifest.readiness?.ready && Date.now()-new Date(manifest.auditedAt).valueOf()<=300000;
    status(current ? `服务已连接 · ${model.rows.length} 条任务已核对${manual?' · 手动刷新完成':''}` : '服务已连接 · 当前显示历史快照；权威数据已变化或审计过期，后台正在更新。',current?'current':'stale');
    updateFreshness();cacheSnapshot();updateCommandAvailability();
    if(state.selection && currentDetail?.taskKey!==state.selection && $('detail').getAttribute('aria-busy')!=='true')loadDetail(state.selection,false);
    if(state.view==='maintenance')await renderMaintenance(false);
  } catch(error) {
    const reason=error.name==='AbortError'?'请求超时':error.message;
    status(`${reason} ${model?'保留上次视图，仅供查看。':'页面会继续重试，也可点击“刷新状态”。'}`,'error');
    updateCommandAvailability();retries++;clearTimeout(retryTimer);retryTimer=setTimeout(()=>refreshRoster(),Math.min(15000,1000*2**Math.min(retries,4)));
  } finally {clearTimeout(timeout);refreshing=false;$('refresh').disabled=false;$('refresh').textContent='刷新状态';if(expiredReloadPending){expiredReloadPending=false;setTimeout(()=>refreshRoster(true),0);}}
}
function updateFreshness() {
  $('freshness').textContent=`快照生成 ${localTime(manifest?.generatedAt)} · 证据核对 ${localTime(manifest?.auditedAt)} · 最后成功读取 ${localTime(lastRead)} · 视图 ${manifest?.snapshotId || '未取得'}`;
}
function renderProgress() {
  const c=model.summary.counts,f=model.summary.endedFreshness || {};
  $('total-label').textContent=`${c.total} 条原任务 · ${model.summary.packages.length} 个工作包`;
  const rows=[
    ['交付报告',c.everDelivered,c.delivered,'累计含历史交付；当前列为正式 waiting 报告'],
    ['公共合入',c.integrated,c.currentAttemptIntegrated,'累计为曾合入的任务；当前列仅本 attempt 且产物匹配'],
    ['有限验证',c.verified,c.currentVerified,'登记过有效 module/scene 验证；范围见任务交付包'],
    [`${C.runtime?.name || '运行时'} 实测`,c.sceneVerified,c.currentSceneVerified,'只有正式登记的 scene 证据计入'],
    ['原任务正式结束',c.ended,f.current || 0,`当前证据匹配 ${f.current||0} · 待重验 ${f['needs-revalidation']||0} · 历史证据不完整 ${f.unverified||0}`]
  ];
  const table=el('table',{class:'progress-table'},[el('thead',{},[el('tr',{},['阶段','累计任务','审计时匹配','统计边界'].map(x=>el('th',{scope:'col'},[x])))]),el('tbody',{},rows.map(r=>el('tr',{},r.map((x,i)=>el('td',{class:i===1||i===2?'number':''},[x])))))]);
  $('progress').replaceChildren(table);
}
function renderExecutionOverview() {
  const value=model.summary.execution;
  if(!value){$('execution-overview').replaceChildren();return;}
  const batch=value.privateBatch || [];
  $('execution-overview').replaceChildren(el('p',{class:'explain'},['候选建议（未启动）· 复用已有成果，公共发布与运行时实测按项目配置协调。']),el('div',{class:'batch-links'},batch.map((r,index)=>button(`${index+1} · ${r.taskId}`,()=>selectTask(r.packageId+'/'+r.taskId,true),{class:'quiet',title:r.nextDeliverable,'data-focus-key':'batch-'+r.packageId+'-'+r.taskId}))),el('p',{class:'explain'},['先领取一个有界交付，再核原合同；这些建议不增加完成数量，也不自动运行Agent。']));
}
function renderPackages() {
  const old=$('package-filter').value;
  const packages=model.summary.packages.filter(p=>state.focus==='all' || p.phase===state.focus);
  if(state.packageId && !packages.some(p=>p.id===state.packageId)){state.packageId='';savePreferences();}
  $('package-filter').replaceChildren(el('option',{value:''},['本阶段全部工作包']),...packages.map(p=>el('option',{value:p.id},[`${p.id} · ${p.title}`])));
  $('package-filter').value=state.packageId;
  $('all-packages').setAttribute('aria-pressed',String(!state.packageId));
  $('packages').replaceChildren(...packages.map(p=>button('',()=>choosePackage(p.id),{'aria-pressed':state.packageId===p.id,'data-package':p.id})).map((b,i)=>{const p=packages[i];const plan=model.summary.execution?.packages?.find(x=>x.packageId===p.id);b.append(el('span',{class:'package-id'},[p.id]),document.createTextNode(p.title));if(plan)b.append(el('span',{class:'package-remaining'},[`原责任剩余 ${plan.remainingOriginalTasks.length} / ${plan.implementationTasks}`]));return b;}));
  $('focus-filter').value=state.focus;
}
function choosePackage(value) {state.packageId=value;state.page=0;$('package-filter').value=value;savePreferences();if(model)renderPackages();renderQueue();}
function renderViews() {
  $('views').replaceChildren(...viewLabels.map(([key,title])=>button(title,()=>{state.view=key;state.page=0;savePreferences();renderViews();renderQueue();},{'aria-pressed':state.view===key,'data-view':key})));
}
function renderQueue() {
  if (!model) return;
  $('execution-overview').hidden=state.view==='maintenance' || Boolean(state.packageId);
  if (state.view==='maintenance') {renderMaintenance();return;}
  const rows=D.sortWorkRows(D.filterRows(model.rows,state));
  const pages=Math.max(1,Math.ceil(rows.length/25));state.page=Math.min(state.page,pages-1);
  $('queue-count').textContent=`筛选 ${rows.length} / 总计 ${model.rows.length}`;
  const nodes=rows.slice(state.page*25,(state.page+1)*25).map(r=>{
    const key=r.packageId+'/'+r.taskId,m=r.milestones || {},chips=[];
    if(m.integrated)chips.push(el('span',{class:'chip'+(m.currentAttemptIntegrated?' current':'')},[m.currentAttemptIntegrated?'本轮合入匹配':'曾合入']));
    if(m.verified)chips.push(el('span',{class:'chip'+(m.currentVerified?' current':'')},[m.currentVerified?'验证当前匹配':'历史验证']));
    if(m.sceneVerified)chips.push(el('span',{class:'chip'+(m.currentSceneVerified?' current':'')},[m.currentSceneVerified?'场景证据匹配':'历史场景实测']));
    const plan=r.executionPlan;
    const name=el('span',{},[el('span',{class:'identity'},[`${r.taskId} · ${r.packageId}${plan?' · '+(laneLabels[plan.lane] || plan.lane):''}`]),el('span',{class:'name'},[r.title]),plan?el('span',{class:'next-deliverable'},[plan.nextDeliverable]):null,el('span',{class:'meta'},[`${r.worker?.owner || '无执行者'}${r.worker?.client?' · '+r.worker.client:''} · ${age(r.updated)}`]),chips.length?el('span',{class:'chips'},chips):null]);
    return taskButton(key,r,name);
  });
  const empty=model.rows.length?el('p',{class:'empty'},['当前筛选没有任务。可清空搜索或切换“全部任务”。']):el('div',{class:'empty'},[el('p',{},[model.summary.packages.length?'工作包已创建，下一步用 task create 添加第一条任务。':'项目已创建，下一步用 package create 创建第一个工作包。']),el('p',{},['先运行 project show 获取最新revision；目录变更需配置的协调者和原因。']),el('pre',{},[[...C.commandPrefix,'project','show'].map(shellQuote).join(' ')]),el('a',{href:'/README.md',target:'_blank',rel:'noopener'},['查看从零建账命令'])]);
  $('task-list').replaceChildren(...(nodes.length?nodes:[empty]));
  $('pagination').replaceChildren(button('上一页',()=>{state.page--;renderQueue();},{disabled:state.page===0?'':null}),el('span',{},[`${state.page+1} / ${pages} 页 · 每页 25 条`]),button('下一页',()=>{state.page++;renderQueue();},{disabled:state.page>=pages-1?'':null}));
}
function taskButton(key,r,name) {
  return el('button',{type:'button',class:'task-row'+(state.selection===key?' selected':''),'data-task-key':key,'aria-label':`${r.taskId} ${r.title} ${labels[r.state] || r.state}`,onclick:()=>selectTask(key,true)},[name,el('span',{class:'row-state '+r.state},[labels[r.state] || r.state,el('br'),deliveryLabels[r.delivery?.status] || ''])]);
}
async function selectTask(key,scroll) {
  state.selection=key;history.replaceState(null,'','#'+key);renderQueue();await loadDetail(key,scroll);
}
async function loadDetail(key,scroll) {
  if (!manifest || !model || !model.rows.some(r=>r.packageId+'/'+r.taskId===key)) return;
  const sid=manifest.snapshotId,seq=++detailSequence;detailAbort?.abort();detailAbort=new AbortController();
  $('detail').setAttribute('aria-busy','true');
  const requestAbort=detailAbort,timeout=setTimeout(()=>requestAbort.abort(),10000);
  try {
    const cacheKey=sid+'/'+key;
    let data=detailCache.get(cacheKey);
    if(!data) {data=await D.shard(API+'snapshots/'+sid+'/details/'+key,sid,'details',key,null,detailAbort.signal);detailCache.set(cacheKey,data);}
    if(seq!==detailSequence || sid!==manifest.snapshotId || key!==state.selection)return;
    currentDetail=data;renderDetail(data);if(scroll && innerWidth<=640)$('detail').scrollIntoView({block:'start'});
  } catch(error) {
    if(await recoverExpired(error))return;
    if(error.name!=='AbortError' && seq===detailSequence)$('detail').replaceChildren(el('h2',{id:'detail-title'},['交付包暂时无法读取']),el('p',{class:'error'},[error.message]),button('重试交付包',()=>loadDetail(key,false)));
  } finally {clearTimeout(timeout);if(seq===detailSequence)$('detail').setAttribute('aria-busy','false');}
}
function fileLink(path,label) {
  const href=D.publicPath(path);return href?el('a',{href,target:'_blank',rel:'noopener',class:'file-link'},[label || path]):el('span',{class:'label'},[label || path || '未提供']);
}
function textList(values) {return el('ul',{},(values || []).map(v=>el('li',{},[typeof v==='string'?v:JSON.stringify(v)])));}
function fold(title,children,key) {return el('details',{'data-fold-key':key},[el('summary',{},[title]),...children]);}
function renderDetail(d) {
  const focused=document.activeElement?.getAttribute('data-focus-key'),scroll=$('detail').scrollTop;
  const open=new Set([...$('detail').querySelectorAll('details[open]')].map(x=>x.dataset.foldKey));
  const t=d.task,i=d.identity,s=d.slot,p=d.package;
  const plan=d.executionPlan || i.executionPlan;
  const execution=el('section',{},[el('h3',{},['本轮只交付什么']),plan?el('p',{class:'status-note'},[plan.nextDeliverable]):el('p',{class:'explain'},['执行组织尚未生成；先核对原合同和既有报告。']),plan?el('p',{class:'explain'},[`责任：${plan.responsibleRole} · ${plan.workstream.label} · 公共发布与运行时验收协调`]):null,plan?.currentGap?el('p',{},['原登记剩余：'+plan.currentGap]):null,plan?.reuseReport?fileLink(plan.reuseReport,'优先复用已有交付，不从头重写'):null,i.registeredEndedReferences?.length?el('p',{class:'status-note'},['登记说明涉及已结束依赖：'+i.registeredEndedReferences.join('、')+'。以本次依赖观察和正式门禁为准，勿重复等待。']):null,el('p',{class:'explain'},['执行建议不新增原任务分母，不授予权限，不替代原合同验收。']),button('复制本轮任务提示词',()=>copyTaskPrompt(d),{'data-focus-key':'copy-task-prompt'})]);
  const current=el('section',{},[el('h3',{},['当前执行与交付']),el('dl',{},[
    el('dt',{},['状态 / 实际客户端']),el('dd',{},[`${labels[i.state] || i.state} · ${s.worker?.owner || s.subagentId || '无'} · ${s.worker?.client || s.client || '未知'}`]),
    el('dt',{},['当前 attempt / generation']),el('dd',{class:'mono'},[`${s.attempt || '未提供'} / ${s.generation ?? '未知'}`]),
    el('dt',{},['当前专属写入范围']),el('dd',{class:'mono'},[(s.attemptWriteScope || (s.scope ? [s.scope] : [])).join('\n') || '尚未取得 grant']),
    el('dt',{},['本轮交付状态']),el('dd',{},[deliveryLabels[i.delivery?.status] || '未登记正式 waiting 交付'])]),
    d.currentReport?fileLink(d.currentReport.path,'打开本轮正式报告'):el('p',{class:'explain'},[d.reportError || (i.state==='running'?'执行中的 note 不是正式交付报告。':'本轮无可核对的正式交付报告。')]),
    d.currentReport?el('p',{class:'mono explain'},['SHA256 '+d.currentReport.sha256]):null,
    s.note?fileLink(s.note,'当前 note / 进展说明'):null,
    i.delivery?.nextAction?el('p',{class:'status-note'},['下一步：'+i.delivery.nextAction]):null,
    i.delivery?.blocker?el('p',{class:'status-note'},['登记阻塞：'+i.delivery.blocker]):null,
    i.blockers?.length?el('p',{class:'status-note'},['正式结束的依赖未满足：'+i.blockers.join('、')]):null]);
  const acceptance=el('section',{},[el('h3',{},['原合同与验收']),el('p',{},[t.objective || t.title]),el('ol',{},d.acceptanceChecklist.map(r=>el('li',{},[r.text]))),el('p',{class:'explain'},['此处展示原验收句；“已合入/有限验证”不会自动将这些句子标为通过。']),fold('源输入、消费者与反例',[el('h3',{},['源输入']),textList(t.inputs),el('h3',{},['实际消费者']),el('pre',{},[typeof t.consumer==='string'?t.consumer:JSON.stringify(t.consumer || {},null,2)]),el('h3',{},['必须覆盖的反例']),textList(t.counterexamples),el('h3',{},['任务依赖']),textList(t.dependencies)],'contract')]);
  const inherited=el('section',{},[el('h3',{},['继承交付与发布']),d.inheritedHandoff?.submission?.path?fileLink(d.inheritedHandoff.submission.path,'打开上一代冻结交付报告'):el('p',{class:'explain'},['当前执行槽没有正式继承交付。']),
    d.inheritedHandoff?.submission?.sha256?el('p',{class:'mono explain'},['冻结 SHA256 '+d.inheritedHandoff.submission.sha256]):null,
    el('p',{class:'explain'},[`${d.historyCount} 条执行历史 · ${d.integrations.length} 条正式合入。当前报告和继承报告分别核对。`]),
    ...d.integrations.slice(0,5).map(r=>el('div',{},[el('p',{class:'mono explain'},[`${r.id} · ${evidenceLabels[r.artifactState] || r.artifactState} · ${r.attempt || ''}`]),r.report?fileLink(r.report,'对应实施报告'):null,r.patchPath?fileLink(r.patchPath,'候选 patch'):null])),
    fold('按需读取执行历史',[button('加载历史',()=>loadPage(d,'history',0),{'data-focus-key':'history-load'}),el('div',{id:'history-content'})],'history'),
    fold('按需读取发布清单、前后像与依赖',[button('加载发布清单',()=>loadPage(d,'releases',0),{'data-focus-key':'releases-load'}),el('div',{id:'releases-content'})],'releases')]);
  const verification=el('section',{},[el('h3',{},['已登记验证与完成新鲜度']),el('p',{class:'status-note'},[`正式状态：${labels[i.state] || i.state} · 当前完成证据：${evidenceLabels[i.endedStatus?.status] || '未知'}${i.endedStatus?.reason?' · '+i.endedStatus.reason:''}`]),
    ...(d.verifications || []).map(v=>el('div',{},[el('p',{class:'label'},[`${v.tier==='scene'?'场景':'模块'} · ${evidenceLabels[v.artifactState] || v.artifactState} · ${v.checks} 项 · ${v.scope}`]),fileLink(v.report?.path,'验证报告'),el('p',{class:'explain'},[`审核 attempt ${v.attempt} · 实施 attempt ${v.subjectAttempt || v.attempt}`]),v.drift?.length?fold(`查看 ${v.drift.length} 项变化`,[textList(v.drift.map(x=>x.path+' · '+(x.reason==='missing'?'缺失':'内容已变')))],'drift-'+v.id):null])),
    !(d.verifications || []).length?el('p',{class:'explain'},['尚无正式登记的有限验证。未登记实测不计入已验证。']):null]);
  const commands=el('section',{},[el('h3',{},['正式 CLI 操作']),el('p',{class:'explain'},['先刷新身份，再用当前 grant 执行动作。模板不授予权限；本页不存储 token，也不修改任务。']),
    ...Object.entries(d.commands).filter(([,v])=>Array.isArray(v)).map(([name,args])=>el('div',{class:'command'},[button(name==='identity'?'复制身份查询':name==='inspect'?'复制完整门禁查询':'查询最新身份并复制接手命令',()=>name==='takeHandoff'?copyFreshHandoff(d.taskKey):copyText(args.map(shellQuote).join(' ')),{'data-command':name,'data-focus-key':'cmd-'+name,disabled:name==='takeHandoff'&&['error','offline'].includes(connectionState)?'':null}),el('pre',{},[args.map(shellQuote).join(' ')])]))]);
  const docs=el('section',{},[el('h3',{},['文档与证据']),...(p.documents || []).map(x=>fileLink(typeof x==='string'?x:x.path,typeof x==='string'?x:(x.title || x.path))),
    ...(p.figures || []).slice(0,12).map(x=>{const path=typeof x==='string'?x:x.path;return button(typeof x==='string'?x:(x.caption || x.title || path),event=>openImage(path,typeof x==='string'?x:(x.caption || x.title || path),event.currentTarget),{class:'quiet','data-focus-key':'image-'+path});}),
    el('a',{href:'README.md',target:'_blank'},['进度口径与独立验收规则'])]);
  $('detail').replaceChildren(el('p',{class:'task-id'},[`${i.packageId} / ${i.taskId}`]),el('h2',{id:'detail-title'},[t.title]),button('返回任务队列',()=>{$('task-list').scrollIntoView({block:'start'});$('task-list').focus({preventScroll:true});},{class:'quiet','data-focus-key':'back-to-queue'}),el('p',{class:'boundary'},['只读交付包 · CLI 将重新核对源门槛、依赖、执行权和原验收句。']),execution,current,acceptance,inherited,verification,commands,docs);
  for(const node of $('detail').querySelectorAll('details'))node.open=open.has(node.dataset.foldKey);
  $('detail').scrollTop=scroll;
  if(focused)$('detail').querySelector(`[data-focus-key="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
}
function shellQuote(arg) {return /^[A-Za-z0-9_./:@=-]+$/.test(arg)?arg:"'"+arg.replaceAll("'","''")+"'";}
async function copyText(text) {
  try {await navigator.clipboard.writeText(text);status('已复制到剪贴板。正式动作仍由 CLI 核验。',isCurrent()?'current':'stale');}
  catch {status('剪贴板不可用，可选中命令文本复制。','stale');}
}
function updateCommandAvailability() {for(const b of document.querySelectorAll('[data-command=takeHandoff]'))b.disabled=['error','offline'].includes(connectionState);}
async function copyFreshHandoff(key) {
  try {
    const args=await D.freshHandoff(key),command=args.map(shellQuote).join(' ');
    let output=$('fresh-handoff-command');
    if(!output){output=el('pre',{id:'fresh-handoff-command',tabindex:'0','aria-label':'最新身份对应的接手命令'});(document.querySelector('[data-command="takeHandoff"]')?.parentElement || $('detail')).append(output);}
    output.textContent=command;await copyText(command);
  }
  catch(error){status(error.message+' 可先复制身份查询命令。','stale');}
}
function copyTaskPrompt(d) {
  const plan=d.executionPlan || d.identity.executionPlan;
  const text=[`工作目录 ${C.projectRoot}。当前目标 ${d.task.id}：${d.task.title}。`,
    d.task.role==='gate'?'这是整包gate，按项目配置安排审核，不作为普通实施任务领取。':`先以真实独有owner/client运行 ${C.commandPrefix.map(shellQuote).join(' ')} show ${d.identity.packageId} ${d.task.id} --identity，再凭fresh CAS正式领取；新grant退出0后才写。`,
    '运行时验收：'+(C.runtime?.verificationMethod || '按项目配置')+' · '+(C.runtime?.entrypoint || ''),
    '本轮交付：'+(plan?.nextDeliverable || d.task.objective),
    '优先复用：'+(plan?.reuseReport || '本条既有报告、正式合入及现成通用模块'),
    '登记剩余：'+(plan?.currentGap || '核原报告和当前依赖，不从头重做整包'),
    '先读原合同逐句验收。只写本次attempt；公共代码交根受控串行发布。通过配置的运行时和MCP真实操作与截图验收；提交可复现步骤，未亲测不得声称通过。',
    '保留原资源/原函数身份、失败、命令退出码、输入产物SHA；达到本轮有限交付后正式wait释放，保留其他OPEN，不把合入或报告当ended。运行逆向目标前遵守当前项目的执行授权与隔离约束。',
    '汇报仅任务ID、实际变化、证据、提交SHA和剩余缺口。'].join('\n');
  return copyText(text);
}
async function recoverExpired(error) {
  if(error.code!=='snapshot-expired')return false;
  detailCache.clear();etag='';status('旧代视图已回收，正在读取当前同一任务。','stale');
  if(refreshing)expiredReloadPending=true;else await refreshRoster(true);
  return true;
}
async function loadPage(d,kind,offset) {
  const key=d.taskKey,sid=d.snapshotId,target=$(kind+'-content');if(!target)return;
  target.setAttribute('aria-busy','true');
  try {
    const value=await D.shard(API+`snapshots/${sid}/${kind}/${key}?offset=${offset}&limit=10`,sid,kind,key);
    if(state.selection!==key || manifest.snapshotId!==sid)return;
    target.replaceChildren(el('p',{class:'explain'},[`共 ${value.total} 条 · 本页 ${value.items.length} 条`]),...value.items.map((r,n)=>el('details',{},[el('summary',{},[r.id || `${offset+n+1} · ${r.mode || '执行记录'}`]),el('pre',{},[JSON.stringify(r,null,2)])])),
      ...(value.nextOffset!==null?[button('读取下一页',()=>loadPage(d,kind,value.nextOffset))]:[]));
  } catch(error) {if(await recoverExpired(error))return;if(state.selection===key)target.replaceChildren(el('p',{class:'error'},[error.message]),button('重试',()=>loadPage(d,kind,offset)));}
  finally {target.removeAttribute('aria-busy');}
}
async function renderMaintenance(loading=true) {
  $('queue-count').textContent='独立维护 · 不计入项目任务';$('pagination').replaceChildren();
  if(loading)$('task-list').replaceChildren(el('p',{class:'explain'},['读取正式维护登记…']));
  try {
    const response=await fetch(API+'maintenance',{cache:'no-cache',headers:maintenanceETag?{'If-None-Match':maintenanceETag}:{}});
    if(response.status!==304){if(!response.ok)throw new Error('维护登记读取失败');maintenanceValue=await response.json();maintenanceETag=response.headers.get('ETag') || '';}
    const value=maintenanceValue;if(state.view!=='maintenance')return;if(!value || !Array.isArray(value.tasks))throw new Error('维护登记协议不完整');
    const serialized=JSON.stringify(value);if(!loading && serialized===maintenanceJSON)return;maintenanceJSON=serialized;
    const active=document.activeElement,focusHref=$('task-list').contains(active)?active.getAttribute('href'):null;
    $('task-list').replaceChildren(...value.tasks.map(t=>{const recent=(t.events || []).filter(e=>e.type==='progress').at(-1);const receipts=(value.receipts || []).filter(r=>r.taskId===t.taskId && r.attempt===t.attempt);return el('div',{class:'maintenance-item'},[el('h3',{},[`${t.taskId} · ${{running:'执行中',completed:'已完成'}[t.state] || t.state}`]),el('p',{class:'explain'},[`${t.owner} · ${t.client} · 更新 ${localTime(t.updatedAt)}`]),fileLink(recent?.note || t.scope+'/progress.md','最近实际进展与验收记录'),t.completion?.report?.path?fileLink(t.completion.report.path,'正式完成报告'):null,...receipts.slice(-2).map(r=>fileLink(t.scope+'/'+r.id+'/manifest.json','发布收据 '+r.id)),el('p',{class:'explain'},[`${t.events?.length || 0} 条正式事件 · ${receipts.length} 次受控发布 · 独立维护通道`])]);}),el('p',{class:'explain'},[`维护合入 ${value.receipts.length} 次${value.pending?' · 存在待恢复发布，请根用现grant正式recover':''}；不会改变项目进度。`]));
    if(focusHref)$('task-list').querySelector(`a[href="${CSS.escape(focusHref)}"]`)?.focus({preventScroll:true});
  } catch(error) {if(state.view==='maintenance')$('task-list').replaceChildren(el('p',{class:'error'},[error.message]),button('重试维护登记',renderMaintenance));}
}
let imageOpener=null,imageFocusKey=null;
function openImage(path,caption,opener) {
  const url=D.publicPath(path);if(!url)return;imageOpener=opener;imageFocusKey=opener?.getAttribute('data-focus-key');const picture=el('img',{id:'evidence-image',src:url,alt:caption});picture.addEventListener('error',()=>{$('image-content').replaceChildren(el('p',{class:'error'},['图片未能加载，请核对原文件。']),fileLink(path,'打开原文件'));});$('image-content').replaceChildren(picture);$('image-caption').textContent=caption;$('image-dialog').showModal();
}
$('close-image').addEventListener('click',()=>$('image-dialog').close());
$('image-dialog').addEventListener('close',()=>{const replacement=imageFocusKey?document.querySelector(`[data-focus-key="${CSS.escape(imageFocusKey)}"]`):null;(replacement || (imageOpener?.isConnected?imageOpener:$('task-list'))).focus({preventScroll:true});$('image-content').replaceChildren();});
function renderAll() {
  const active=document.activeElement,position={x:scrollX,y:scrollY};
  let selector=active?.id?'#'+CSS.escape(active.id):null;
  if(!selector)for(const key of ['data-task-key','data-view','data-package','data-focus-key']){const value=active?.getAttribute(key);if(value){selector=`[${key}="${CSS.escape(value)}"]`;break;}}
  renderProgress();renderExecutionOverview();renderPackages();renderViews();renderQueue();updateFreshness();
  if(selector && !$('image-dialog').open)document.querySelector(selector)?.focus({preventScroll:true});
  window.scrollTo(position.x,position.y);
}
$('search').value=state.q;$('owner-filter').value=state.owner;
let searchTimer;
for(const [id,key] of [['search','q'],['owner-filter','owner']])$(id).addEventListener('input',event=>{state[key]=event.target.value;state.page=0;savePreferences();clearTimeout(searchTimer);searchTimer=setTimeout(renderQueue,120);});
$('package-filter').addEventListener('change',event=>choosePackage(event.target.value));
$('focus-filter').value=state.focus;$('focus-filter').addEventListener('change',event=>{state.focus=event.target.value;state.packageId='';state.page=0;savePreferences();renderPackages();renderQueue();});
$('all-packages').addEventListener('click',()=>choosePackage(''));
$('refresh').addEventListener('click',()=>refreshRoster(true));
$('diagnostic').addEventListener('click',()=>copyText(JSON.stringify({url:location.href,connectionState,lastRead,service:manifest?.service,snapshotId:manifest?.snapshotId,auditedAt:manifest?.auditedAt,readiness:manifest?.readiness,counts:model?.summary.counts},null,2)));
window.addEventListener('hashchange',()=>{const key=D.decodeSelection(location.hash);if(key){state.selection=key;renderQueue();loadDetail(key,false);}});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshRoster();});window.addEventListener('online',()=>refreshRoster());
document.title=C.title+' · Super Ledger';document.querySelector('h1').textContent=C.title;document.querySelector('.top p').textContent=C.subtitle;
$('focus-filter').replaceChildren(el('option',{value:'all'},['全部阶段']),...C.phases.map(p=>el('option',{value:p.id},[p.title])));
renderViews();restoreReadonly();refreshRoster();
setInterval(()=>{if(!document.hidden)refreshRoster();},15000);
// Stable observation entrypoints used by browser verification and maintainers.
globalThis.milestoneSnapshot=()=>model?{counts:model.summary.counts,tasks:model.rows}:null;
globalThis.workbenchObservation=()=>({snapshotId:manifest?.snapshotId,connectionState,refreshing,selection:state.selection,lastRead,detailTask:currentDetail?.taskKey});
