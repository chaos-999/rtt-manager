"""全互联（mesh）WireGuard 配置生成与部署。

与 wgconf.py 的「链式路径」模式完全分离，独立实现，避免相互影响（分权制衡）。
全互联模式：
  - 每个节点只保留单个 wg0 接口
  - Peer = 其余所有节点，AllowedIPs = 对方 wg_ip/32（点对点直连）
  - 不需要穿透路由、不需要开内核转发
  - 部署成功后将 config 的 active_edges 置为完全图，供 tcp_rtt 推导"测所有邻居"

本模块只调用 wgconf 的现成能力（build_conf_text / ensure_keys / deploy_node），
不修改 wgconf 的任何逻辑。
"""
from concurrent.futures import ThreadPoolExecutor

from . import wgconf
from .tasks import find_key, save_config, probe_nodes, check_ip_conflicts


def _pick_nodes(cfg, selected=None, nodes=None):
    """取本次参与全互联的节点：优先 nodes，其次按 selected 过滤，否则全部。"""
    if nodes is not None:
        return list(nodes)
    all_nodes = cfg.get("nodes", [])
    if selected:
        return [n for n in all_nodes if n["name"] in selected]
    return list(all_nodes)


def build_mesh_confs(cfg, private_keys=None, nodes=None):
    """生成参与节点的全互联 conf。返回 {name: conf_text}（每个 Peer = 其余参与节点）。"""
    target = _pick_nodes(cfg, nodes=nodes)
    private_keys = private_keys or {}
    confs = {}
    for n in target:
        peers = [
            (other, [other.get("wg_ip", "")])
            for other in target
            if other["name"] != n["name"]
        ]
        confs[n["name"]] = wgconf.build_conf_text(
            n, peers, private_keys.get(n["name"]), iface="wg0"
        )
    return confs


def full_mesh_edges(cfg, nodes=None):
    """返回完全图的边列表（参与节点两两相连）。"""
    target = _pick_nodes(cfg, nodes=nodes)
    edges = []
    for i, a in enumerate(target):
        for b in target[i + 1:]:
            edges.append({"source": a["name"], "target": b["name"]})
    return edges


def deploy_mesh(cfg, selected=None):
    """部署全互联：并行取私钥 -> 生成 conf -> 并行部署 -> active_edges=完全图。

    selected 为空时部署全部节点；否则只部署选中节点，完全图也只含选中节点。
    返回 {"ok": bool, "error": str|None, "results": [{name, ok, steps}]}
    """
    nodes = _pick_nodes(cfg, selected=selected)
    if len(nodes) < 2:
        return {"ok": False, "error": "至少需要 2 个节点", "results": []}

    # 部署前校验：内网 IP 冲突（只提示，不修改配置）
    conflicts = check_ip_conflicts(cfg.get("nodes", []))
    if conflicts:
        msg = "; ".join(f"{ip} 被 {a}、{b} 同时使用" for ip, a, b in conflicts)
        return {"ok": False, "error": f"内网 IP 冲突，已拦截：{msg}", "results": []}

    # 探活：剔除不可达节点，其余照常部署
    reachable, unreachable = probe_nodes(cfg, [n["name"] for n in nodes])
    probe_fail = [
        {"name": u["name"], "ok": False,
         "steps": [{"name": "探活", "script": "echo 1", "ok": False,
                    "output": "节点不可达，已从本次部署剔除"}]}
        for u in unreachable
    ]
    nodes = [n for n in nodes if n["name"] in set(reachable)]
    if len(nodes) < 2:
        return {"ok": False, "error": "可用节点不足 2 个（探活剔除后）", "results": probe_fail}

    # 1) 并行幂等获取各节点私钥（复用 wgconf.ensure_keys）
    def _fetch_key(n):
        key_path = find_key(cfg, n)
        if not key_path:
            return n["name"], None, "找不到 SSH 密钥"
        pk, err = wgconf.ensure_keys(n, key_path)
        if pk is None:
            return n["name"], None, err
        return n["name"], pk, None

    private_keys = {}
    with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
        for name, pk, err in ex.map(_fetch_key, nodes):
            if err is not None:
                return {"ok": False, "error": f"{name}: {err}", "results": []}
            private_keys[name] = pk

    # 2) 生成全互联 conf
    confs = build_mesh_confs(cfg, private_keys, nodes=nodes)

    # 3) 并行部署（全互联是点对点直连，不开内核转发）
    def _deploy(n):
        key_path = find_key(cfg, n)
        steps = wgconf.deploy_node(n, confs[n["name"]], key_path, is_forwarder=False)
        ok = all(s["ok"] for s in steps)
        return {"name": n["name"], "ok": ok, "steps": steps}

    with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
        results = list(ex.map(_deploy, nodes))

    # 4) 全部成功 -> active_edges 置为完全图
    if all(r["ok"] for r in results):
        cfg["active_edges"] = full_mesh_edges(cfg, nodes=nodes)
        try:
            save_config(cfg)
        except Exception:
            pass

    return {"ok": True, "error": None, "results": results + probe_fail}
