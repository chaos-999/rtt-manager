"""WireGuard 单路径配置生成与部署。

核心算法（割集/前后缀）：
  给定一条简单路径 path = [N0, N1, ..., Nk-1]（无重复节点的链），
  对路径上的每个节点 Ni（索引 i），它的邻居为：
    - 左邻居 Ni-1（若 i > 0）
    - 右邻居 Ni+1（若 i < k-1）

  对每个邻居，该邻居 [Peer] 的 AllowedIPs =
    断开 Ni—邻居 这条边后，邻居那一侧的所有节点。
  因路径是无分支的链，等价于：
    - 右邻居 Ni+1 一侧 = 后缀 [Ni+1, Ni+2, ..., Nk-1]
    - 左邻居 Ni-1 一侧 = 前缀 [Ni-1, Ni-2, ..., N0]

  Endpoint 只由"邻居是否有公网 IP"这一数据事实决定，不区分物理类型。
"""
import os
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor

from . import ssh
from .tasks import find_key, probe_nodes, check_ip_conflicts
from .paths import app_dir

CONFIG_PATH = os.path.join(app_dir(), "config.json")

MTU = 1380
DEFAULT_PORT = 51820


def _node_map(cfg):
    return {n["name"]: n for n in cfg.get("nodes", [])}


def _has_edge(cfg, a, b):
    for e in cfg.get("edges", []):
        if (e["source"] == a and e["target"] == b) or (e["source"] == b and e["target"] == a):
            return True
    return False


def validate_path(cfg, path):
    """校验路径，返回 (ok, error)。

    规则：至少 2 个节点；节点存在；无重复；相邻节点必须有边连接。
    """
    if len(path) < 2:
        return False, "路径至少需要 2 个节点"
    node_map = _node_map(cfg)
    for name in path:
        if name not in node_map:
            return False, f"节点不存在: {name}"
    if len(set(path)) != len(path):
        return False, "路径不能有重复节点"
    for i in range(len(path) - 1):
        if not _has_edge(cfg, path[i], path[i + 1]):
            return False, f"{path[i]} 与 {path[i+1]} 之间没有边连接"
    return True, ""


def build_conf_text(node, peers, private_key=None, iface="wg0"):
    """生成单个节点的 conf 文本。

    node: 本节点 dict
    peers: [(peer_dict, allowed_ips_list)]，allowed_ips 已按"邻居在前"排序
    private_key: 私钥字符串，None 时用占位符
    iface: 接口名（wg0/wg1），用于生成精确路由

    PostUp/PreDown 作用：解决多接口在同一 /24 网段时的路由二义性。
    为每个目标 IP 建 /32 精确路由，强制绑定到本接口，避免内核把包交给
    错误的接口（如北京 wg1 抢走本应走 wg0 的包，报 Required key not available）。
    """
    key = private_key if private_key else "<PRIVATE_KEY>"
    lines = ["[Interface]",
             f"Address = {node.get('wg_ip', '')}/24",
             f"ListenPort = {node.get('listen_port', DEFAULT_PORT)}",
             f"PrivateKey = {key}",
             f"MTU = {MTU}"]

    # 收集所有目标 IP（去重、保序），生成精确路由
    all_ips = []
    for _, allowed in peers:
        for ip in allowed:
            if ip and ip not in all_ips:
                all_ips.append(ip)
    if all_ips:
        add = "; ".join(f"ip route replace {ip}/32 dev {iface}" for ip in all_ips)
        dele = "; ".join(f"ip route del {ip}/32 dev {iface} 2>/dev/null" for ip in all_ips)
        lines.append(f"PostUp = {add}")
        lines.append(f"PreDown = {dele}")

    for peer, allowed in peers:
        lines.append("")
        lines.append("[Peer]")
        lines.append(f"PublicKey = {peer.get('public_key', '')}")
        if peer.get("ip"):
            lines.append(f"Endpoint = {peer['ip']}:{peer.get('listen_port', DEFAULT_PORT)}")
        lines.append("AllowedIPs = " + ", ".join(f"{ip}/32" for ip in allowed))
        lines.append("PersistentKeepalive = 25")
    return "\n".join(lines) + "\n"


def build_path_conf(cfg, path, private_keys=None):
    """为整条路径生成每个节点的 conf。

    private_keys: {node_name: private_key}，缺省时该节点用占位符。
    返回 {node_name: conf_text}
    """
    node_map = _node_map(cfg)
    k = len(path)
    private_keys = private_keys or {}
    confs = {}

    for i, name in enumerate(path):
        node = node_map[name]
        peers = []
        # 右邻居 Ni+1：一侧 = 后缀 [i+1 .. k-1]
        if i < k - 1:
            right = path[i + 1:]
            allowed = [node_map[x].get("wg_ip", "") for x in right]
            peers.append((node_map[path[i + 1]], allowed))
        # 左邻居 Ni-1：一侧 = 前缀 [i-1 .. 0]
        if i > 0:
            left = path[:i][::-1]
            allowed = [node_map[x].get("wg_ip", "") for x in left]
            peers.append((node_map[path[i - 1]], allowed))

        confs[name] = build_conf_text(node, peers, private_keys.get(name))
    return confs


def _is_forwarder(path, name):
    """中间节点（非端点）需要开内核转发。"""
    return 0 < path.index(name) < len(path) - 1


def forwarders(path):
    """返回路径中需要开内核转发的节点列表（中间节点）。"""
    return [name for name in path if _is_forwarder(path, name)]


def ensure_keys(node, key_path):
    """幂等确保节点存在私钥/公钥，返回 (private_key, error)。

    只在 privatekey 不存在时才生成，绝不覆盖，避免公私钥变化导致全网断联。
    """
    cmd = (
        "if [ ! -f /etc/wireguard/privatekey ]; then "
        "umask 077 && wg genkey > /etc/wireguard/privatekey && "
        "wg pubkey < /etc/wireguard/privatekey > /etc/wireguard/publickey; fi; "
        "cat /etc/wireguard/privatekey"
    )
    code, out, err = ssh.run_ssh(node["ip"], key_path, cmd)
    if code != 0:
        return None, (err or out).strip()
    return out.strip(), None


def enable_forwarding(node, key_path):
    """中间节点开内核转发 + iptables（幂等，-C 先查重）。返回 (ok, script, output)。"""
    script = (
        "sysctl -w net.ipv4.ip_forward=1\n"
        "echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf\n"
        "iptables -C FORWARD -i wg0 -o wg0 -j ACCEPT 2>/dev/null || iptables -A FORWARD -i wg0 -o wg0 -j ACCEPT\n"
        "echo FORWARD_OK"
    )
    cmd = script.replace("\n", "; ")
    code, out, err = ssh.run_ssh(node["ip"], key_path, cmd)
    return code == 0, script, (out + err).strip()


def _restart_script():
    return (
        "chmod 600 /etc/wireguard/wg0.conf\n"
        "ip link delete wg0 2>/dev/null || true\n"
        "wg-quick up wg0\n"
        "systemctl enable wg-quick@wg0 2>/dev/null\n"
        "echo UP_OK"
    )


def deploy_node(node, conf_text, key_path, is_forwarder):
    """上传 conf 并暴力重启，返回 steps 列表（每步含脚本命令 + 输出）。"""
    steps = []

    # 1. 上传 conf
    fd, tmp = tempfile.mkstemp(suffix=".conf")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(conf_text)
        rc, o, e = ssh.push_file(node["ip"], key_path, tmp, "/etc/wireguard/wg0.conf")
    finally:
        os.unlink(tmp)
    steps.append({
        "name": "上传 wg0.conf",
        "script": f"scp {tmp} root@{node['ip']}:/etc/wireguard/wg0.conf",
        "ok": rc == 0,
        "output": (o + e).strip() or "上传完成"
    })
    if rc != 0:
        return steps

    # 2. 暴力重启
    restart_script = _restart_script()
    code, out, err = ssh.run_ssh(node["ip"], key_path, restart_script.replace("\n", "; "))
    steps.append({
        "name": "重启 WireGuard（暴力清理）",
        "script": restart_script,
        "ok": code == 0,
        "output": (out + err).strip()
    })
    if code != 0:
        return steps

    # 3. 中间节点开内核转发
    if is_forwarder:
        ok, fwd_script, fwd_out = enable_forwarding(node, key_path)
        steps.append({
            "name": "开启内核转发",
            "script": fwd_script,
            "ok": ok,
            "output": fwd_out
        })
    else:
        steps.append({
            "name": "开启内核转发",
            "script": "(端点节点，无需开启转发)",
            "ok": True,
            "output": "跳过"
        })

    return steps


def deploy_path(cfg, path):
    """部署整条路径：SSH 取私钥 -> 生成 conf -> 上传 -> 重启 -> 转发。

    取私钥和部署均并行执行（各节点独立），保持结果顺序。

    返回 {"results": [{name, ok, steps: [{name, script, ok, output}]}]}
    """
    node_map = _node_map(cfg)

    # 部署前校验：内网 IP 冲突（只提示，不修改配置）
    conflicts = check_ip_conflicts(cfg.get("nodes", []))
    if conflicts:
        msg = "; ".join(f"{ip} 被 {a}、{b} 同时使用" for ip, a, b in conflicts)
        return {"ok": False, "error": f"内网 IP 冲突，已拦截：{msg}", "results": []}

    # 部署前探活：路径上任一节点不可达则整体失败（避免部署后断链）
    _, unreachable = probe_nodes(cfg, path)
    if unreachable:
        names = "、".join(u["name"] for u in unreachable)
        return {"ok": False, "error": f"节点探活失败，已拦截：{names}", "results": []}

    # 先并行幂等获取所有节点的私钥
    def _fetch_key(name):
        node = node_map[name]
        key_path = find_key(cfg, node)
        if not key_path:
            return name, None, "找不到 SSH 密钥"
        pk, err = ensure_keys(node, key_path)
        if pk is None:
            return name, None, err
        return name, pk, None

    private_keys = {}
    with ThreadPoolExecutor(max_workers=len(path)) as ex:
        for name, pk, err in ex.map(_fetch_key, path):
            if err is not None:
                return {"ok": True, "results": [{"name": name, "ok": False,
                        "steps": [{"name": "获取私钥", "script": "wg genkey / cat privatekey", "ok": False, "output": err}]}]}
            private_keys[name] = pk

    confs = build_path_conf(cfg, path, private_keys)

    # 并行部署各节点
    def _deploy(name):
        node = node_map[name]
        key_path = find_key(cfg, node)
        steps = deploy_node(node, confs[name], key_path, _is_forwarder(path, name))
        ok = all(s["ok"] for s in steps)
        return {"name": name, "ok": ok, "steps": steps}

    with ThreadPoolExecutor(max_workers=len(path)) as ex:
        results = list(ex.map(_deploy, path))

    # 部署成功后，用当前路径的边覆盖 active_edges，供 tcp_rtt 生成时识别"实际部署的邻居"
    # 覆盖而非累积：单路径语义下，新部署路径 = 当前唯一生效拓扑，历史边应被清掉
    if all(r["ok"] for r in results):
        active = []
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            active.append({"source": a, "target": b})
        cfg["active_edges"] = active
        try:
            from .tasks import save_config, save_path_history
            save_config(cfg)
            save_path_history(path)
        except Exception:
            pass

    return {"ok": True, "results": results}
