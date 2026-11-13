/* Immutable view protocol. No task writes, grants, or availability decisions. */
(function (root) {
  'use strict';
  function validateManifest(m) {
    if (!m || m.schema !== 'super-ledger/workbench-view@1' || !/^[a-f0-9]{32}$/.test(m.snapshotId) ||
        !/^[a-f0-9]{64}$/.test(m.files?.summary?.sha256 || '') || !/^[a-f0-9]{64}$/.test(m.files?.tasks?.sha256 || '') || !m.auditedAt ||
        m.admissionEvaluated !== false) throw new Error('视图协议不完整，请更新服务后重试。');
    return m;
  }
  function validateShard(value, sid, kind, taskKey) {
    if (!value || value.snapshotId !== sid || value.schema !== `super-ledger/workbench-${kind}@1` ||
        (taskKey && value.taskKey !== taskKey)) throw new Error('数据代号或任务身份不匹配，已保留原视图。');
    return value;
  }
  async function digest(bytes) {
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    return Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join('');
  }
  async function shard(url, sid, kind, taskKey, expectedHash, signal) {
    const response = await fetch(url, {signal});
    if (response.status === 410) {const error=new Error('该代视图已回收，正在刷新当前任务。');error.code='snapshot-expired';throw error;}
    if (!response.ok) throw new Error(`读取 ${kind} 失败（HTTP ${response.status}），可重试。`);
    const bytes = await response.arrayBuffer();
    if (expectedHash && await digest(bytes) !== expectedHash) throw new Error('分片 SHA 校验失败，已拒绝本次刷新。');
    return validateShard(JSON.parse(new TextDecoder().decode(bytes)), sid, kind, taskKey);
  }
  function filterRows(rows, filters) {
    const q = (filters.q || '').trim().toLocaleLowerCase();
    return rows.filter(r => (!filters.focus || filters.focus==='all' || workPhase(r)===filters.focus) && (!filters.packageId || r.packageId === filters.packageId) &&
      (!filters.owner || (r.worker?.owner || '').toLocaleLowerCase().includes(filters.owner.toLocaleLowerCase())) &&
      (!q || [r.taskId, r.packageId, r.title, r.worker?.owner, r.worker?.client, r.delivery?.blocker, r.delivery?.nextAction].join(' ').toLocaleLowerCase().includes(q)) &&
      (filters.view === 'all' || filters.view === 'maintenance' ||
       (filters.view === 'review' && r.state==='waiting' && r.executionPlan?.lane==='independent-review') ||
       (filters.view === 'publication' && r.state==='waiting' && (['publication-review','root-scene'].includes(r.executionPlan?.lane) || r.milestones?.currentAttemptIntegrated && !r.milestones?.currentSceneVerified)) ||
       (filters.view === 'implementation' && ['waiting','idle'].includes(r.state) && ['bounded-implementation','targeted-source','source-assessment'].includes(r.executionPlan?.lane)) ||
       (filters.view === 'coordination' && (r.executionPlan?.lane==='handoff-repair' || r.state==='running')) ||
       (filters.view === 'integrated' ? r.milestones?.integrated :
        filters.view === 'verified' ? r.milestones?.verified : r.state === filters.view)));
  }
  function workPhase(r) { return r.phase || r.executionPlan?.workstream?.phase || ''; }
  function sortWorkRows(rows) {
    const phase=Object.fromEntries((globalThis.WorkbenchConfig?.phases || []).map((p,i)=>[p.id,i]));
    return [...rows].sort((a,b)=>(phase[workPhase(a)]??3)-(phase[workPhase(b)]??3) || (a.workPriority??99)-(b.workPriority??99) || a.packageId.localeCompare(b.packageId,undefined,{numeric:true}) || a.taskId.localeCompare(b.taskId,undefined,{numeric:true}));
  }
  async function freshHandoff(taskKey) {
    if(decodeSelection(taskKey)!==taskKey)throw new Error('任务身份无效或不是实施切片。');
    const response=await fetch('/api/workbench/identity/'+taskKey,{cache:'no-store'});
    if(!response.ok)throw new Error('最新身份读取失败，请复制身份查询命令。');
    const value=await response.json();
    if(value.schema!=='super-ledger/identity@1' || value.readOnly!==true || value.admissionEvaluated!==false || value.writeAuthorized!==false || value.packageId+'/'+value.taskId!==taskKey || value.state!=='waiting' || !/^[a-f0-9]{64}$/.test(value.revision || '') || !/^[a-f0-9]{64}$/.test(value.reportSha256 || ''))throw new Error('执行状态或交付已变化，请先刷新并核对报告。');
    return [...globalThis.WorkbenchConfig.commandPrefix,'take-handoff',value.packageId,value.taskId,'--expected-revision',value.revision,'--report-sha',value.reportSha256,'--owner','<different-actual-owner>','--client','<actual-client>','--json'];
  }
  function decodeSelection(hash) {
    const value=hash.replace(/^#/, '');
    return /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\/[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(value)?value:'';
  }
  function publicPath(path) {
    if(typeof path!=='string' || !path.startsWith('ledger-work/') || /[\\?#:\x00-\x1f]/.test(path) || path.split('/').some(p=>p==='..' || p==='.' || p.startsWith('.')))return null;
    return '/api/evidence/'+path.split('/').map(encodeURIComponent).join('/');
  }
  const api = {validateManifest, validateShard, digest, shard, filterRows, decodeSelection, publicPath, workPhase, sortWorkRows, freshHandoff};
  root.WorkbenchData = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
