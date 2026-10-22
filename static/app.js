let config = null;

// ================= 基础工具 =================
function selectedNodes() {
  const boxes = document.querySelectorAll('#node-list input[type=checkbox]');
  const names = [];
  boxes.forEach(b => { if (b.checked) names.push(b.dataset.name); });
  return names;
}

function log(msg, cls = '') {
  const el = document.getElementById('log');
  el.innerHTML += '\n' + `<span class="${cls}">${msg}</span>`;
  el.scrollTop = el.scrollHeight;
}

function logClear() {
  document.getElementById('log').innerHTML = '';
}

function showLoading() {
  document.getElementById('log-spinner').classList.remove('hidden');
}

function hideLoading() {
  document.getElementById('log-spinner').classList.add('hidden');
}

async function saveConfig() {
  await fetch('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config)
  });
}

// ================= 节点列表（左侧勾选） =================
function renderNodes() {
  const list = document.getElementById('node-list');
  list.innerHTML = '';
  (config.nodes || []).forEach(n => {
    const li = document.createElement('li');
    li.innerHTML = `<input type="checkbox" data-name="${n.name}" checked> <span class="node-dot" style="background:${roleColor(n.role)}"></span> <span>${n.name}</span> <span class="ip">${n.ip || ''}</span>`;
    list.appendChild(li);
  });
}

// ================= 配置弹窗（节点表格） =================
function renderNodeEditor() {
  const box = document.getElementById('node-editor');
  box.innerHTML = '';
  (config.nodes || []).forEach(n => {
    const row = document.createElement('div');
    row.className = 'node-edit';
    row.innerHTML = `
      <input type="text" data-field="name" value="${n.name || ''}">
      <input type="text" data-field="ip" value="${n.ip || ''}">
      <input type="text" data-field="key_dir" value="${n.key_dir || ''}">
      <input type="text" data-field="role" value="${n.role || ''}">
      <input type="text" data-field="lat" value="${n.lat !== undefined ? n.lat : ''}">
      <input type="text" data-field="lng" value="${n.lng !== undefined ? n.lng : ''}">
      <button class="del" title="删除">×</button>
    `;
    row.querySelector('.del').addEventListener('click', () => {
      const idx = Array.from(box.children).indexOf(row);
      config.nodes.splice(idx, 1);
      renderNodeEditor();
    });
    box.appendChild(row);
  });
}

function fillConfigForm() {
  document.getElementById('cfg-key-base').value = config.key_base || '';
  document.getElementById('cfg-results-dir').value = config.results_dir || '';
  document.getElementById('cfg-default-count').value = (config.defaults && config.defaults.count) || 1000;
  document.getElementById('cfg-default-time').value = (config.defaults && config.defaults.time) || '15:30:00';
  renderNodeEditor();
}

function collectConfigForm() {
  config.key_base = document.getElementById('cfg-key-base').value;
  config.results_dir = document.getElementById('cfg-results-dir').value;
  config.defaults = config.defaults || {};
  config.defaults.count = parseInt(document.getElementById('cfg-default-count').value) || 1000;
  config.defaults.time = document.getElementById('cfg-default-time').value || '15:30:00';

  // 按 index 合并，仅更新 name/ip/key_dir/role，保留 wg_ip 等其它字段
  const rows = document.querySelectorAll('#node-editor .node-edit');
  const newNodes = [];
  rows.forEach((r, i) => {
    const get = f => r.querySelector(`[data-field="${f}"]`).value.trim();
    const name = get('name'), ip = get('ip');
    if (!name && !ip) return;
    const old = config.nodes[i] || {};
    const node = { ...old, name, ip, key_dir: get('key_dir'), role: get('role') };
    const lat = get('lat'), lng = get('lng');
    if (lat !== '' && !isNaN(parseFloat(lat))) node.lat = parseFloat(lat); else delete node.lat;
    if (lng !== '' && !isNaN(parseFloat(lng))) node.lng = parseFloat(lng); else delete node.lng;
    newNodes.push(node);
  });
  config.nodes = newNodes;
}

async function loadConfig() {
  const r = await fetch('/api/config');
  config = await r.json();
  config.edges = config.edges || [];
  config.nodes = (config.nodes || []).map(n => ({ listen_port: 51820, dynamic: false, routes: [], ...n }));
  renderNodes();
  fillConfigForm();
}

// ================= 操作动作（连通/NTP/下发等） =================
async function runAction(action) {
  const nodes = selectedNodes();
  logClear();
  log(`执行操作：${action}，目标节点：${nodes.length ? nodes.join(', ') : '(全部)'}`, 'warn');
  let url, method = 'GET', body = null;

  if (action === 'test') {
    url = '/api/nodes/test' + (nodes.length ? '?nodes=' + encodeURIComponent(nodes.join(',')) : '');
  } else if (action === 'ntp') {
    url = '/api/nodes/ntp' + (nodes.length ? '?nodes=' + encodeURIComponent(nodes.join(',')) : '');
  } else if (action === 'schedule') {
    method = 'POST'; url = '/api/tasks/schedule';
    body = { start_time: document.getElementById('start-time').value, count: parseInt(document.getElementById('count').value) || 1000, nodes };
  } else if (action === 'clean') {
    method = 'POST'; url = '/api/tasks/clean'; body = { nodes };
  } else if (action === 'list-timers') {
    method = 'GET'; url = '/api/tasks/timers' + (nodes.length ? '?nodes=' + encodeURIComponent(nodes.join(',')) : '');
  } else if (action === 'fetch-results') {
    method = 'POST'; url = '/api/tasks/fetch_results';
    body = { time_str: document.getElementById('fetch-time').value, nodes };
  } else if (action === 'fetch-script') {
    // 单独处理：先预览脚本，确认后下发
    previewTcpRtt(nodes);
    return;
  } else if (action === 'deploy-echo') {
    method = 'POST'; url = '/api/tasks/deploy_echo'; body = { nodes };
  }

  const opts = { method };
  if (body) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  showLoading();
  try {
    const r = await fetch(url, opts);
    const data = await r.json();
    if (action === 'list-timers') {
      (data.results || []).forEach(res => {
        log(`[${res.name}]`, 'warn');
        if (res.timers && res.timers.length) {
          res.timers.forEach(t => log(`  ${t.unit}  →  ${t.next}`, 'ok'));
        } else {
          log('  （无定时任务）', 'fail');
        }
      });
      // 提取所有定时任务的时间戳，填充到"测量时间"下拉
      const times = new Set();
      (data.results || []).forEach(res => {
        (res.timers || []).forEach(t => {
          const m = t.unit.match(/sync-(\d{6})-/);
          if (m) times.add(m[1]);
        });
      });
      fillFetchTimeList([...times].sort());
    } else {
      (data.results || []).forEach(res => {
        const cls = res.ok ? 'ok' : 'fail';
        log(`[${res.name}] ${res.ok ? '成功' : '失败'}: ${res.detail}`, cls);
      });
    }
    log('--- 完成 ---', 'warn');
  } catch (e) {
    log('请求出错: ' + e.message, 'fail');
  } finally {
    hideLoading();
  }
}

function fillFetchTimeList(times) {
  const dl = document.getElementById('fetch-time-list');
  dl.innerHTML = '';
  times.forEach(t => {
    const opt = document.createElement('option');
    opt.value = t;
    dl.appendChild(opt);
  });
}

// ================= 拓扑编辑 =================
let cy = null;
let connectMode = false;
let connectSource = null;
let pathMode = false;
let pathNodes = [];

const ROLE_COLORS = {
  gateway: '#f59e0b',
  server: '#ef4444',
  relay: '#8b5cf6',
  client: '#22c55e'
};

function roleColor(role) {
  return ROLE_COLORS[role] || '#64748b';
}

let topoLoaded = false;

function openTopo() {
  document.getElementById('topo-modal').classList.remove('hidden');
  if (!cy) initCy();
  // 只在第一次打开时加载，之后保留画布状态（边/位置不因关闭而丢失）
  if (!topoLoaded) {
    loadTopo();
    topoLoaded = true;
  }
}

function initCy() {
  cy = cytoscape({
    container: document.getElementById('topo-canvas'),
    style: [
      {
        selector: 'node',
        style: {
          'label': 'data(label)',
          'color': '#fff',
          'font-size': 14,
          'text-valign': 'bottom',
          'text-margin-y': 8,
          'background-color': 'data(color)',
          'width': 46, 'height': 46,
          'border-width': 2, 'border-color': '#fff',
          'text-wrap': 'wrap'
        }
      },
      { selector: 'node:selected', style: { 'border-width': 4, 'border-color': '#38bdf8' } },
      { selector: 'node.connect-source', style: { 'border-width': 4, 'border-color': '#fbbf24' } },
      { selector: 'node.path-node', style: { 'border-width': 4, 'border-color': '#22d88a' } },
      {
        selector: 'edge',
        style: {
          'width': 3, 'line-color': '#64748b',
          'curve-style': 'bezier'
        }
      },
      { selector: 'edge:selected', style: { 'line-color': '#38bdf8' } }
    ],
    layout: { name: 'preset' },
    wheelSensitivity: 0.25,
    zoom: 1,
    minZoom: 0.3,
    maxZoom: 3
  });

  cy.on('dbltap', 'node', evt => editNode(evt.target));
  cy.on('cxttap', 'node', evt => { if (confirm(`删除节点 ${evt.target.data('name')}？`)) evt.target.remove(); });
  cy.on('cxttap', 'edge', evt => evt.target.remove());
  cy.on('tap', 'node', evt => {
    if (connectMode) { handleConnect(evt.target); return; }
    if (pathMode) { addPathNode(evt.target); }
  });
  cy.on('tap', evt => {
    if (connectMode && evt.target === cy && connectSource) {
      connectSource.removeClass('connect-source');
      connectSource = null;
    }
  });
}

function loadTopo() {
  cy.elements().remove();
  let hasPos = false;
  (config.nodes || []).forEach(n => {
    if (n.pos_x !== undefined && n.pos_y !== undefined) hasPos = true;
    cy.add({
      group: 'nodes',
      data: {
        id: n.name,
        label: `${n.name}\n${n.wg_ip || ''}`,
        color: roleColor(n.role),
        name: n.name,
        role: n.role || '',
        ip: n.ip || '',
        wg_ip: n.wg_ip || '',
        public_key: n.public_key || '',
        listen_port: n.listen_port || 51820,
        key_dir: n.key_dir || '',
        dynamic: !!n.dynamic,
        routes: n.routes || []
      },
      position: { x: n.pos_x || Math.random() * 500, y: n.pos_y || Math.random() * 400 }
    });
  });
  (config.edges || []).forEach(e => {
    cy.add({ group: 'edges', data: { source: e.source, target: e.target } });
  });
  if (!hasPos) cy.layout({ name: 'cose', animate: false, padding: 40 }).run();
}

function handleConnect(target) {
  if (!connectSource) {
    connectSource = target;
    target.addClass('connect-source');
    return;
  }
  if (connectSource.id() === target.id()) {
    connectSource.removeClass('connect-source');
    connectSource = null;
    return;
  }
  const exists = cy.edges().some(e =>
    (e.data('source') === connectSource.id() && e.data('target') === target.id()) ||
    (e.data('source') === target.id() && e.data('target') === connectSource.id())
  );
  if (!exists) {
    cy.add({ group: 'edges', data: { source: connectSource.id(), target: target.id() } });
  }
  connectSource.removeClass('connect-source');
  connectSource = null;
}

let editingNode = null;

function editNode(node) {
  editingNode = node;
  const d = node.data();
  document.getElementById('np-name').value = d.name || '';
  document.getElementById('np-role').value = d.role || '';
  document.getElementById('np-ip').value = d.ip || '';
  document.getElementById('np-wg-ip').value = d.wg_ip || '';
  document.getElementById('np-pubkey').value = d.public_key || '';
  document.getElementById('np-keydir').value = d.key_dir || '';
  document.getElementById('np-port').value = d.listen_port || 51820;
  document.getElementById('np-dynamic').value = d.dynamic ? '1' : '';
  document.getElementById('node-props-modal').classList.remove('hidden');
}

function saveNodeProps() {
  if (!editingNode) return;
  const name = document.getElementById('np-name').value.trim();
  const wg_ip = document.getElementById('np-wg-ip').value.trim();
  const oldId = editingNode.data('id');

  // 改名时同步 edge 的 source/target
  if (name && name !== oldId) {
    cy.edges().forEach(e => {
      if (e.data('source') === oldId) e.data('source', name);
      if (e.data('target') === oldId) e.data('target', name);
    });
    editingNode.data('id', name);
  }

  editingNode.data({
    name,
    label: `${name}\n${wg_ip}`,
    color: roleColor(document.getElementById('np-role').value.trim()),
    role: document.getElementById('np-role').value.trim(),
    ip: document.getElementById('np-ip').value.trim(),
    wg_ip,
    public_key: document.getElementById('np-pubkey').value.trim(),
    listen_port: parseInt(document.getElementById('np-port').value) || 51820,
    key_dir: document.getElementById('np-keydir').value.trim(),
    dynamic: document.getElementById('np-dynamic').value.trim() === '1'
  });
  document.getElementById('node-props-modal').classList.add('hidden');
}

function saveTopo() {
  config.nodes = cy.nodes().map(n => {
    const d = n.data();
    const p = n.position();
    return {
      name: d.name,
      ip: d.ip, wg_ip: d.wg_ip,
      public_key: d.public_key,
      listen_port: d.listen_port,
      dynamic: d.dynamic,
      key_dir: d.key_dir,
      role: d.role,
      routes: d.routes || [],
      pos_x: p.x, pos_y: p.y
    };
  });
  config.edges = cy.edges().map(e => ({ source: e.data('source'), target: e.data('target') }));
  return saveConfig();
}

// ================= 路径选择与部署 =================
function setPathMode(on) {
  pathMode = on;
  document.getElementById('btn-topo-path').classList.toggle('active', on);
  document.getElementById('btn-topo-path').textContent = on ? '选路径(点节点)' : '选路径';
  if (on) {
    document.getElementById('path-bar').classList.remove('hidden');
  }
}

function addPathNode(node) {
  const name = node.data('name');
  const idx = pathNodes.indexOf(name);
  if (idx >= 0) {
    // 已存在则截断（回到该节点重新开始）
    pathNodes = pathNodes.slice(0, idx + 1);
  } else {
    pathNodes.push(name);
  }
  renderPath();
}

function renderPath() {
  document.getElementById('path-display').textContent = pathNodes.join(' ⇄ ');
  cy.nodes().forEach(n => n.removeClass('path-node'));
  cy.nodes().forEach(n => {
    if (pathNodes.includes(n.data('name'))) n.addClass('path-node');
  });
}

function clearPath() {
  pathNodes = [];
  cy.nodes().forEach(n => n.removeClass('path-node'));
  document.getElementById('path-display').textContent = '';
}

function collectTopoState() {
  const nodes = cy.nodes().map(n => {
    const d = n.data();
    return {
      name: d.name, ip: d.ip, wg_ip: d.wg_ip,
      public_key: d.public_key, listen_port: d.listen_port,
      dynamic: d.dynamic, key_dir: d.key_dir, role: d.role
    };
  });
  const edges = cy.edges().map(e => ({ source: e.data('source'), target: e.data('target') }));
  return { nodes, edges };
}

async function previewPath() {
  if (pathNodes.length < 2) { alert('请至少选择 2 个节点'); return; }
  const state = collectTopoState();
  const r = await fetch('/api/wg/preview', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: pathNodes, nodes: state.nodes, edges: state.edges })
  });
  const data = await r.json();
  if (!data.ok) { alert('路径错误: ' + data.error); return; }
  let text = '';
  text += `路径：${data.path.join(' ⇄ ')}\n`;
  text += `（双向连接，方向不影响配置）\n`;
  if (data.forwarders && data.forwarders.length) {
    text += `\n需要开启内核转发的中间节点：${data.forwarders.join('、')}\n`;
  } else {
    text += `\n无中间节点，所有节点均为端点，无需开启转发\n`;
  }
  for (const [name, conf] of Object.entries(data.confs)) {
    text += `\n########## ${name} ##########\n` + conf;
  }
  document.getElementById('conf-title').textContent = 'WireGuard 配置预览';
  document.getElementById('conf-preview').textContent = text;
  document.getElementById('btn-conf-deploy').style.display = 'none';  // wg 预览无需"确认下发"
  pendingDeploy = null;
  document.getElementById('conf-modal').classList.remove('hidden');
}

async function deployPath() {
  if (pathNodes.length < 2) { alert('请至少选择 2 个节点'); return; }
  if (!confirm(`确认部署路径：\n${pathNodes.join(' ⇄ ')}\n\n将覆盖这些节点的 wg0.conf 并重启 WireGuard。`)) return;
  const state = collectTopoState();
  const btn = document.getElementById('btn-path-deploy');
  btn.disabled = true;
  btn.textContent = '部署中...';
  showLoading();
  let data;
  try {
    const r = await fetch('/api/wg/deploy', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: pathNodes, nodes: state.nodes, edges: state.edges })
    });
    data = await r.json();
  } finally {
    btn.disabled = false;
    btn.textContent = '部署';
    hideLoading();
  }
  if (!data.ok) { alert('路径错误: ' + data.error); return; }
  // 部署后关闭拓扑弹窗，回到主界面查看控制台输出
  document.getElementById('topo-modal').classList.add('hidden');
  logClear();
  log(`部署路径：${pathNodes.join(' ⇄ ')}（双向）`, 'warn');
  (data.results || []).forEach(res => {
    log(`\n===== ${res.name} =====`, 'warn');
    (res.steps || []).forEach(s => {
      const cls = s.ok ? 'ok' : 'fail';
      log(`  [${s.name}] ${s.ok ? '✓' : '✗'}`, cls);
      if (s.script) log(`    脚本:\n${s.script}`);
      if (s.output) log(`    输出: ${s.output}`);
    });
    log(`  → ${res.name} ${res.ok ? '部署成功' : '部署失败'}`, res.ok ? 'ok' : 'fail');
  });
  log('--- 部署结束 ---', 'warn');
}

// ================= 事件绑定 =================
document.querySelectorAll('button[data-action]').forEach(btn => {
  btn.addEventListener('click', () => runAction(btn.dataset.action));
});

document.getElementById('check-all').addEventListener('change', (e) => {
  document.querySelectorAll('#node-list input[type=checkbox]').forEach(b => b.checked = e.target.checked);
});

// 配置弹窗
document.getElementById('btn-config').addEventListener('click', () => {
  fillConfigForm();
  document.getElementById('config-modal').classList.remove('hidden');
});
document.getElementById('btn-close-config').addEventListener('click', () => {
  document.getElementById('config-modal').classList.add('hidden');
});
document.getElementById('btn-add-node').addEventListener('click', () => {
  config.nodes.push({ name: '', ip: '', key_dir: '', role: '' });
  renderNodeEditor();
});
document.getElementById('btn-save-config').addEventListener('click', async () => {
  collectConfigForm();
  await saveConfig();
  document.getElementById('config-modal').classList.add('hidden');
  renderNodes();
  // 配置可能增删了节点，若拓扑画布已初始化则重新同步
  if (cy) {
    loadTopo();
  }
  logClear(); log('配置已保存', 'ok');
});

// 拓扑弹窗
document.getElementById('btn-topo').addEventListener('click', openTopo);
document.getElementById('btn-topo-close').addEventListener('click', () => {
  document.getElementById('topo-modal').classList.add('hidden');
});
document.getElementById('btn-topo-add-node').addEventListener('click', () => {
  const name = prompt('节点名称：');
  if (!name) return;
  const existing = cy.getElementById(name);
  if (existing.length) { alert('节点已存在'); return; }
  cy.add({
    group: 'nodes',
    data: {
      id: name, name, label: name, color: '#64748b',
      role: 'client', ip: '', wg_ip: '', public_key: '', listen_port: 51820, key_dir: '', dynamic: false, routes: []
    },
    position: { x: 250 + Math.random() * 100, y: 200 + Math.random() * 100 }
  });
});
document.getElementById('btn-topo-connect').addEventListener('click', () => {
  connectMode = !connectMode;
  document.getElementById('btn-topo-connect').classList.toggle('active', connectMode);
  document.getElementById('btn-topo-connect').textContent = connectMode ? '连边模式(点两个节点)' : '连边模式';
  if (!connectMode && connectSource) { connectSource.removeClass('connect-source'); connectSource = null; }
});
document.getElementById('btn-topo-layout').addEventListener('click', () => {
  cy.layout({ name: 'cose', animate: true, padding: 40 }).run();
});
document.getElementById('btn-topo-save').addEventListener('click', async () => {
  await saveTopo();
  renderNodes();
  logClear(); log('拓扑已保存', 'ok');
});
document.getElementById('btn-topo-path').addEventListener('click', () => setPathMode(!pathMode));
document.getElementById('btn-path-clear').addEventListener('click', clearPath);
document.getElementById('btn-path-preview').addEventListener('click', previewPath);
document.getElementById('btn-path-deploy').addEventListener('click', deployPath);
document.getElementById('btn-conf-close').addEventListener('click', () => {
  document.getElementById('conf-modal').classList.add('hidden');
});

// ================= tcp_rtt 预览 + 确认下发 =================
let pendingDeploy = null; // { type: 'tcp_rtt', nodes: [...] } 待确认的下发信息

async function previewTcpRtt(nodes) {
  const r = await fetch('/api/tcp_rtt/generate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  });
  const data = await r.json();
  if (!data.ok) { alert('生成失败'); return; }
  document.getElementById('conf-title').textContent = 'tcp_rtt.sh 预览（确认后下发）';
  document.getElementById('conf-preview').textContent = data.script;
  document.getElementById('btn-conf-deploy').style.display = '';
  document.getElementById('conf-modal').classList.remove('hidden');
  pendingDeploy = { type: 'tcp_rtt', nodes };
}

async function confirmDeploy() {
  if (!pendingDeploy) return;
  const pd = pendingDeploy;
  pendingDeploy = null;

  if (pd.type === 'tcp_rtt') {
    document.getElementById('conf-modal').classList.add('hidden');
    logClear();
    log(`生成并分发 tcp_rtt.sh，目标节点：${pd.nodes.length ? pd.nodes.join(', ') : '(全部)'}`, 'warn');
    showLoading();
    let data;
    try {
      const r = await fetch('/api/tcp_rtt/deploy', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected: pd.nodes })
      });
      data = await r.json();
    } finally {
      hideLoading();
    }
    (data.results || []).forEach(res => {
      const cls = res.ok ? 'ok' : 'fail';
      log(`[${res.name}] ${res.ok ? '成功' : '失败'}: ${res.detail}`, cls);
    });
    log('--- 完成 ---', 'warn');
  }
}

// 复制预览全部内容
document.getElementById('btn-conf-deploy').addEventListener('click', confirmDeploy);

document.getElementById('btn-conf-copy').addEventListener('click', async () => {
  const text = document.getElementById('conf-preview').textContent;
  try {
    await navigator.clipboard.writeText(text);
    alert('已复制到剪贴板');
  } catch (e) {
    // 降级：用 execCommand
    const pre = document.getElementById('conf-preview');
    const range = document.createRange();
    range.selectNodeContents(pre);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    document.execCommand('copy');
    sel.removeAllRanges();
    alert('已复制到剪贴板');
  }
});

// 在预览区按 Ctrl+A 只选中预览内容（而非整个页面）
document.getElementById('conf-preview').addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
    e.preventDefault();
    const range = document.createRange();
    range.selectNodeContents(e.target);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }
});

// ================= 结果清理（检测 + 手动清理） =================
document.getElementById('btn-results-check').addEventListener('click', async () => {
  const el = document.getElementById('results-stats');
  const cleanBtn = document.getElementById('btn-results-clean');
  const nodes = selectedNodes();
  showLoading();
  try {
    const url = '/api/results/stats' + (nodes.length ? '?nodes=' + encodeURIComponent(nodes.join(',')) : '');
    const r = await fetch(url);
    const d = await r.json();
    logClear();
    const L = d.local || {};
    log(`[本地] 数量=${L.count}  最早=${L.earliest || '无'}`, L.exceeds ? 'warn' : 'ok');
    (d.remote || []).forEach(x => {
      if (!x.ok) { log(`[${x.name}] 查询失败: ${x.detail || ''}`, 'fail'); return; }
      log(`[${x.name}] 数量=${x.count}  最早=${x.earliest || '无'}`, x.exceeds ? 'warn' : 'ok');
    });
    log(d.exceeds ? '→ 已触发清理阈值（超过 500 个或超 30 天），清理按钮已激活' : '→ 未触发清理阈值',
        d.exceeds ? 'warn' : 'ok');
    cleanBtn.disabled = !d.exceeds;
    cleanBtn.classList.toggle('active', d.exceeds);
    el.textContent = d.exceeds ? '检测完成：需要清理' : '检测完成：无需清理';
    el.style.color = d.exceeds ? '#fbbf24' : '#34d399';
  } catch (e) {
    log('检测出错: ' + e.message, 'fail');
  } finally {
    hideLoading();
  }
});

document.getElementById('btn-results-clean').addEventListener('click', async () => {
  if (!confirm('确认清理？本地和远端都将保留最新 500 个结果、删除超过 30 天的。')) return;
  const nodes = selectedNodes();
  const cleanBtn = document.getElementById('btn-results-clean');
  const el = document.getElementById('results-stats');
  cleanBtn.disabled = true;
  cleanBtn.classList.remove('active');
  showLoading();
  try {
    const r = await fetch('/api/results/clean', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nodes })
    });
    const d = await r.json();
    logClear();
    log(`本地清理：删除 ${d.local_removed} 个文件夹`, 'ok');
    (d.remote || []).forEach(x => {
      log(`[远端 ${x.name}] ${x.ok ? '成功' : '失败'}: ${x.detail}`, x.ok ? 'ok' : 'fail');
    });
    log('--- 清理完成 ---', 'warn');
  } catch (e) {
    log('清理出错: ' + e.message, 'fail');
  } finally {
    hideLoading();
  }
  // 清理后自动重新检测
  document.getElementById('btn-results-check').click();
});

// ================= 数据可视化（中国地图 + 测距同心圆） =================
let mapChart = null;
const CITY_COORDS = {
  '北京': [116.40, 39.90],
  '上海': [121.47, 31.23],
  '深圳': [114.06, 22.54],
  '杭州': [120.15, 30.27],
  '成都': [104.07, 30.57],
  '青岛': [120.38, 36.07]
};

function coordsOf(name) {
  if (CITY_COORDS[name]) return CITY_COORDS[name];
  const n = ((config && config.nodes) || []).find(x => x.name === name);
  if (n && n.lng !== undefined && n.lat !== undefined) return [Number(n.lng), Number(n.lat)];
  return null;
}

function haversineM(lat1, lng1, lat2, lng2) {
  const R = 6371000;
  const rlat1 = lat1 * Math.PI / 180, rlat2 = lat2 * Math.PI / 180;
  const dlat = (lat2 - lat1) * Math.PI / 180;
  const dlng = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(dlat / 2) ** 2 + Math.cos(rlat1) * Math.cos(rlat2) * Math.sin(dlng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function destPoint(lat, lng, bearingDeg, distM) {
  const R = 6371000;
  const d = distM / R;
  const brng = bearingDeg * Math.PI / 180;
  const rlat1 = lat * Math.PI / 180, rlng1 = lng * Math.PI / 180;
  const rlat2 = Math.asin(Math.sin(rlat1) * Math.cos(d) + Math.cos(rlat1) * Math.sin(d) * Math.cos(brng));
  const rlng2 = rlng1 + Math.atan2(Math.sin(brng) * Math.sin(d) * Math.cos(rlat1),
                                   Math.cos(d) - Math.sin(rlat1) * Math.sin(rlat2));
  return [rlng2 * 180 / Math.PI, rlat2 * 180 / Math.PI];
}

function circleCoords(lat, lng, radiusM, segs) {
  segs = segs || 72;
  const pts = [];
  for (let i = 0; i <= segs; i++) {
    pts.push(destPoint(lat, lng, i * 360 / segs, radiusM));
  }
  return pts;
}

async function openViz() {
  document.getElementById('map-modal').classList.remove('hidden');
  const r = await fetch('/api/results/batches');
  const d = await r.json();
  const sel = document.getElementById('viz-batch');
  sel.innerHTML = '';
  (d.batches || []).forEach(b => {
    const o = document.createElement('option');
    o.value = b.name;
    o.textContent = `${b.name}（${b.files} CSV）`;
    sel.appendChild(o);
  });
  renderVizNodeList();
  if (!mapChart) {
    mapChart = echarts.init(document.getElementById('map-canvas'));
    window.addEventListener('resize', () => { if (mapChart) mapChart.resize(); });
  }
  mapChart.resize();
}

let lastVizData = null;  // { batch, nodeData, links, missing }

function renderVizNodeList() {
  const ul = document.getElementById('viz-node-list');
  // 保留上次的勾选状态；首次打开（无旧项）默认全选
  const prev = {};
  ul.querySelectorAll('input[type=checkbox]').forEach(b => { prev[b.dataset.name] = b.checked; });
  ul.innerHTML = '';
  for (const n of ((config && config.nodes) || [])) {
    const checked = (n.name in prev) ? prev[n.name] : true;
    const li = document.createElement('li');
    li.innerHTML = `<input type="checkbox" data-name="${n.name}" ${checked ? 'checked' : ''}> <span>${n.name}</span>`;
    li.querySelector('input').addEventListener('change', () => { syncVizCheckAll(); renderViz(); });
    ul.appendChild(li);
  }
  syncVizCheckAll();
}

function syncVizCheckAll() {
  const boxes = document.querySelectorAll('#viz-node-list input[type=checkbox]');
  const all = boxes.length > 0 && Array.from(boxes).every(b => b.checked);
  document.getElementById('viz-check-all').checked = all;
}

function selectedVizCenters() {
  const s = new Set();
  document.querySelectorAll('#viz-node-list input[type=checkbox]').forEach(b => {
    if (b.checked) s.add(b.dataset.name);
  });
  return s;
}

async function genViz() {
  const batch = document.getElementById('viz-batch').value;
  if (!batch) { alert('请选择数据批次'); return; }
  showLoading();
  try {
    if (!window.__mapRegistered) {
      const geo = await fetch('/static/vendor/china.json').then(x => x.json());
      echarts.registerMap('china', geo);
      window.__mapRegistered = true;
    }
    const r = await fetch('/api/results/data?batch=' + encodeURIComponent(batch));
    const d = await r.json();
    if (!d.ok) { alert(d.error || '读取失败'); return; }

    const nodeData = {};
    const missing = new Set();
    for (const n of ((config && config.nodes) || [])) {
      const c = coordsOf(n.name);
      if (c) nodeData[n.name] = c;
      else missing.add(n.name);
    }
    lastVizData = { batch, nodeData, links: d.links || [], missing };
    renderViz();

    logClear();
    log(`生成可视化：${batch}，共 ${(d.links || []).length} 条链路`, 'ok');
    if (missing.size) log(`未找到坐标的节点（已跳过）：${[...missing].join('、')}`, 'warn');
  } finally {
    hideLoading();
  }
}

function renderViz() {
  if (!lastVizData || !mapChart) return;
  const { nodeData, links } = lastVizData;
  const centers = selectedVizCenters();  // 勾选为参考节点的集合（只有它们才画圆）

  const circleSeries = [];
  const linkSeries = [];
  const labelData = [];
  const LINK_COLORS = ['#4dd0ff', '#ff9f5c', '#7cff9b', '#c084fc',
                       '#ffd84d', '#ff6b9d', '#5cffd6', '#a0e7ff'];
  let colorIdx = 0;

  for (const l of links) {
    const a = coordsOf(l.src), b = coordsOf(l.dst);
    if (!a || !b) continue;
    const color = LINK_COLORS[colorIdx % LINK_COLORS.length];
    colorIdx++;
    const dist = haversineM(a[1], a[0], b[1], b[0]);
    const lo = Math.max(0, l.avg - 3 * (l.stddev || 0));
    const hi = l.avg + 3 * (l.stddev || 0);
    const text = `${l.src}-${l.dst} avg=${l.avg.toFixed(1)}ms [${lo.toFixed(1)}~${hi.toFixed(1)}]`;
    const info = { src: l.src, dst: l.dst, avg: l.avg, lo, hi };

    // 节点间连线（始终显示）
    linkSeries.push({ coords: [a, b], lineStyle: { color } });

    // 只画「被勾选为参考节点」为圆心的圆
    if (centers.has(l.src)) {
      circleSeries.push({ coords: circleCoords(a[1], a[0], dist, 360),
                          lineStyle: { color }, name: `${l.src} ⇄ ${l.dst}`, info });
      labelData.push({ value: destPoint(a[1], a[0], 0, dist),
                       label: { formatter: text, color },
                       name: `${l.src} ⇄ ${l.dst}`, info });
    }
    if (centers.has(l.dst)) {
      circleSeries.push({ coords: circleCoords(b[1], b[0], dist, 360),
                          lineStyle: { color }, name: `${l.src} ⇄ ${l.dst}`, info });
      labelData.push({ value: destPoint(b[1], b[0], 0, dist),
                       label: { formatter: text, color },
                       name: `${l.src} ⇄ ${l.dst}`, info });
    }
  }

  mapChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      formatter: p => {
        const dd = p.data;
        if (dd && dd.info) {
          const i = dd.info;
          return `<b>${i.src} ⇄ ${i.dst}</b><br/>avg = ${i.avg.toFixed(2)} ms<br/>3σ = ${i.lo.toFixed(2)} ~ ${i.hi.toFixed(2)} ms`;
        }
        return p.name || '';
      }
    },
    geo: {
      map: 'china', roam: true, zoom: 1.2,
      itemStyle: { areaColor: '#1e2229', borderColor: '#3a414d' },
      emphasis: { itemStyle: { areaColor: '#2a2f3a' }, label: { show: false } },
      label: { show: false }
    },
    series: [
      {
        type: 'lines', coordinateSystem: 'geo', polyline: false, silent: true,
        lineStyle: { color: '#22d3ee', width: 2, opacity: 0.9, type: 'dashed' },
        data: linkSeries
      },
      {
        type: 'lines', coordinateSystem: 'geo', polyline: true,
        lineStyle: { width: 2, opacity: 0.8 },
        emphasis: { lineStyle: { width: 4, opacity: 1 } },
        data: circleSeries
      },
      {
        type: 'scatter', coordinateSystem: 'geo', symbolSize: 11,
        itemStyle: { color: '#f59e0b', borderColor: '#fff', borderWidth: 1 },
        label: { show: true, formatter: '{b}', position: 'right', color: '#fff', fontSize: 13 },
        data: Object.entries(nodeData).map(([name, c]) => ({ name, value: c }))
      },
      {
        type: 'scatter', coordinateSystem: 'geo', symbolSize: 10,
        itemStyle: { color: 'rgba(0,0,0,0)' },
        emphasis: { label: { fontSize: 14 } },
        label: { show: true, color: '#fde047', fontSize: 12, position: 'top' },
        data: labelData
      }
    ]
  }, true);
}

function vizZoom(delta) {
  if (!mapChart) return;
  const opt = mapChart.getOption();
  const cur = (opt.geo && opt.geo[0] && opt.geo[0].zoom) || 1.2;
  mapChart.setOption({ geo: { zoom: Math.max(0.3, Math.min(8, cur + delta)) } });
}

document.getElementById('btn-viz').addEventListener('click', openViz);
document.getElementById('btn-viz-close').addEventListener('click', () => {
  document.getElementById('map-modal').classList.add('hidden');
});
document.getElementById('btn-viz-gen').addEventListener('click', genViz);
document.getElementById('btn-viz-zoom-in').addEventListener('click', () => vizZoom(0.3));
document.getElementById('btn-viz-zoom-out').addEventListener('click', () => vizZoom(-0.3));
document.getElementById('btn-viz-reset').addEventListener('click', () => genViz());

document.getElementById('viz-check-all').addEventListener('change', (e) => {
  document.querySelectorAll('#viz-node-list input[type=checkbox]').forEach(b => b.checked = e.target.checked);
  renderViz();
});
// ================= 多定时任务（时钟转盘 + 批量下发） =================
let scheduledTimes = [];

function renderTimeList() {
  const ul = document.getElementById('time-list');
  ul.innerHTML = '';
  scheduledTimes.forEach((t, i) => {
    const li = document.createElement('li');
    li.innerHTML = `<span>${t}</span><button class="del" title="删除">×</button>`;
    li.querySelector('.del').addEventListener('click', () => {
      scheduledTimes.splice(i, 1);
      renderTimeList();
    });
    ul.appendChild(li);
  });
}

const CLOCK_ITEM_H = 36;

function buildClockColumn(el, max) {
  el.innerHTML = '';
  const padTop = document.createElement('div');
  padTop.className = 'clock-pad';
  el.appendChild(padTop);
  for (let i = 0; i <= max; i++) {
    const d = document.createElement('div');
    d.className = 'clock-item';
    d.dataset.val = i;
    d.textContent = String(i).padStart(2, '0');
    d.addEventListener('click', () => el.scrollTo({ top: i * CLOCK_ITEM_H, behavior: 'smooth' }));
    el.appendChild(d);
  }
  const padBot = document.createElement('div');
  padBot.className = 'clock-pad';
  el.appendChild(padBot);
}

function clockIndex(el) {
  return Math.round(el.scrollTop / CLOCK_ITEM_H);
}

function clockValue(el) {
  const maxIdx = el.querySelectorAll('.clock-item').length - 1;
  const idx = Math.max(0, Math.min(clockIndex(el), maxIdx));
  return String(idx).padStart(2, '0');
}

function updateClockPreview() {
  const h = clockValue(document.getElementById('clock-h'));
  const m = clockValue(document.getElementById('clock-m'));
  const s = clockValue(document.getElementById('clock-s'));
  document.getElementById('clock-preview').textContent = `${h}:${m}:${s}`;
}

function bindClockScroll(el) {
  el.addEventListener('scroll', () => {
    const idx = clockIndex(el);
    el.querySelectorAll('.clock-item').forEach((it, i) => it.classList.toggle('active', i === idx));
    updateClockPreview();
  });
}

let clockInited = false;
function openClock() {
  const hEl = document.getElementById('clock-h');
  const mEl = document.getElementById('clock-m');
  const sEl = document.getElementById('clock-s');
  if (!clockInited) {
    buildClockColumn(hEl, 23);
    buildClockColumn(mEl, 59);
    buildClockColumn(sEl, 59);
    bindClockScroll(hEl);
    bindClockScroll(mEl);
    bindClockScroll(sEl);
    clockInited = true;
  }
  const now = new Date(Date.now() + 60000);
  hEl.scrollTop = now.getHours() * CLOCK_ITEM_H;
  mEl.scrollTop = now.getMinutes() * CLOCK_ITEM_H;
  sEl.scrollTop = now.getSeconds() * CLOCK_ITEM_H;
  [hEl, mEl, sEl].forEach(e => e.dispatchEvent(new Event('scroll')));
  document.getElementById('clock-modal').classList.remove('hidden');
}

document.getElementById('btn-add-time').addEventListener('click', openClock);
document.getElementById('btn-clock-cancel').addEventListener('click', () => {
  document.getElementById('clock-modal').classList.add('hidden');
});
document.getElementById('btn-clock-ok').addEventListener('click', () => {
  const h = clockValue(document.getElementById('clock-h'));
  const m = clockValue(document.getElementById('clock-m'));
  const s = clockValue(document.getElementById('clock-s'));
  const t = `${h}:${m}:${s}`;
  if (!scheduledTimes.includes(t)) {
    scheduledTimes.push(t);
    scheduledTimes.sort();
    renderTimeList();
  }
  document.getElementById('clock-modal').classList.add('hidden');
});

document.getElementById('btn-schedule-batch').addEventListener('click', async () => {
  if (!scheduledTimes.length) { alert('请先添加至少一个定时'); return; }
  const count = parseInt(document.getElementById('count').value) || 1000;
  const nodes = selectedNodes();
  if (!confirm(`将向 ${nodes.length ? nodes.length + ' 个' : '全部'}节点下发 ${scheduledTimes.length} 个定时任务：\n${scheduledTimes.join('、')}\n\n次数：${count}`)) return;
  showLoading();
  logClear();
  log(`批量下发 ${scheduledTimes.length} 个定时，次数=${count}`, 'warn');
  try {
    for (const t of scheduledTimes) {
      log(`\n[${t}]`, 'warn');
      const r = await fetch('/api/tasks/schedule', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_time: t, count, nodes })
      });
      const d = await r.json();
      (d.results || []).forEach(x => {
        log(`  ${x.name}: ${x.ok ? '成功' : '失败'}`, x.ok ? 'ok' : 'fail');
      });
    }
    log('\n--- 批量下发完成 ---', 'warn');
  } catch (e) {
    log('下发出错: ' + e.message, 'fail');
  } finally {
    hideLoading();
  }
});

// 全互联部署（O(n^2) 两两直连）
document.getElementById('btn-mesh-deploy').addEventListener('click', async () => {
  const nodes = selectedNodes();
  if (nodes.length < 2) { alert('请至少勾选 2 个节点'); return; }
  if (!confirm(`将把勾选的 ${nodes.length} 个节点部署为全互联（每对点对点直连），\n覆盖它们的 wg0.conf，并把 active_edges 置为完全图。\n\n确认继续？`)) return;
  showLoading();
  try {
    const r = await fetch('/api/mesh/deploy', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nodes })
    });
    const d = await r.json();
    logClear();
    if (!d.ok) { log('全互联部署失败: ' + (d.error || ''), 'fail'); return; }
    log('全互联部署完成：', 'ok');
    (d.results || []).forEach(x => {
      log(`[${x.name}] ${x.ok ? '成功' : '失败'}`, x.ok ? 'ok' : 'fail');
      (x.steps || []).forEach(s => {
        if (!s.ok) log(`    ${s.name}: ${s.output || ''}`, 'fail');
      });
    });
    log(`active_edges 已置为完全图（${(d.active_edges || []).length} 条边）`, 'ok');
    log('下一步：点「生成并分发 tcp_rtt.sh」→「下发定时任务」', 'warn');
  } catch (e) {
    log('请求出错: ' + e.message, 'fail');
  } finally {
    hideLoading();
  }
});

// 节点属性弹窗
document.getElementById('btn-np-save').addEventListener('click', saveNodeProps);
document.getElementById('btn-np-cancel').addEventListener('click', () => {
  document.getElementById('node-props-modal').classList.add('hidden');
});

// ================= 认证：首次启动引导 + 管理员登录 =================
let authed = false;

async function initAuth() {
  let status;
  try {
    const r = await fetch('/api/auth/status');
    status = await r.json();
  } catch (e) {
    return;  // 服务异常时不阻塞
  }

  if (status.first) {
    // 首次启动：显示引导，预填已有配置
    try {
      const r = await fetch('/api/config');
      const cfg = await r.json();
      document.getElementById('setup-key-base').value = cfg.key_base || '';
      document.getElementById('setup-results-dir').value = cfg.results_dir || '';
    } catch (e) {}
    document.getElementById('setup-modal').classList.remove('hidden');
    return;
  }

  if (status.has_password) {
    document.getElementById('login-modal').classList.remove('hidden');
    return;
  }
}

document.getElementById('btn-setup-save').addEventListener('click', async () => {
  const keyBase = document.getElementById('setup-key-base').value.trim();
  const resultsDir = document.getElementById('setup-results-dir').value.trim();
  const pwd = document.getElementById('setup-password').value;
  const pwd2 = document.getElementById('setup-password2').value;
  if (!keyBase || !resultsDir) { alert('请填写密钥目录和结果保存目录'); return; }
  if (!pwd) { alert('请设置管理员密码'); return; }
  if (pwd !== pwd2) { alert('两次密码不一致'); return; }
  const r = await fetch('/api/auth/setup', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key_base: keyBase, results_dir: resultsDir, password: pwd })
  });
  const data = await r.json();
  if (data.ok) {
    document.getElementById('setup-modal').classList.add('hidden');
    authed = true;
    await loadConfig();
  } else {
    alert('设置失败');
  }
});

document.getElementById('btn-login').addEventListener('click', async () => {
  const pwd = document.getElementById('login-password').value;
  const errEl = document.getElementById('login-error');
  const r = await fetch('/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: pwd })
  });
  const data = await r.json();
  if (data.ok) {
    authed = true;
    document.getElementById('login-modal').classList.add('hidden');
    await loadConfig();
  } else {
    errEl.textContent = data.error || '密码错误';
    document.getElementById('login-password').value = '';
  }
});

document.getElementById('login-password').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') document.getElementById('btn-login').click();
});

initAuth();
