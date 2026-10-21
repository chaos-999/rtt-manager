"""根据拓扑（nodes + edges）自动生成 tcp_rtt.sh。

脚本中硬编码的 case 分支（每节点测哪些邻居）由拓扑的边推导：
  一个节点的 TARGETS = 所有与它相连的节点的 (wg_ip: 名称)。
这样拓扑一变，重新生成脚本即可，消除"拓扑"与"测量脚本"两处数据不一致的问题。
"""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

from . import ssh
from .tasks import find_key

# 脚本头部：到 case "$WG_IP" in 为止
SCRIPT_HEAD = r'''#!/bin/bash
# tcp_rtt.sh
# 蜘蛛网络 TCP 建连后传输 RTT 测量脚本
# 自动识别本机身份，测量所有邻居（由 rtt-manager 根据拓扑自动生成）
# 用法：tcp_rtt.sh [count]      count 默认 100
# 端口：9000（需对端运行 tcp-echo）

COUNT=${1:-100}
PORT=${PORT:-9000}
OUT_DIR="/root/rtt_results"
mkdir -p "$OUT_DIR"

# 识别本机身份（优先 wg0，其次 wg1）
WG_IP=$(ip -4 addr show wg0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
WG1_IP=$(ip -4 addr show wg1 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}')

case "$WG_IP" in
'''

# 脚本尾部：case 的兜底分支 + 测量逻辑
SCRIPT_TAIL = r'''    "")
        # wg0 未识别，尝试用 wg1 识别
        case "$WG1_IP" in
            *) echo "未识别的节点：wg0=$WG_IP wg1=$WG1_IP"; exit 1 ;;
        esac
        ;;
    *) echo "未识别的 WireGuard IP: $WG_IP"; exit 1 ;;
esac

TS=$(date +%Y%m%d_%H%M%S)
CSV="$OUT_DIR/${NODE}_${TS}.csv"
echo "src,dst,ip,port,sent,recv,loss_pct,min_ms,avg_ms,max_ms,stddev_ms,p50_ms,p95_ms" > "$CSV"

echo "节点：$NODE"
echo "时间：$TS"
echo "次数：$COUNT   端口：$PORT"
echo ""

for entry in "${TARGETS[@]}"; do
    IFS=':' read -r ip name <<< "$entry"
    echo "=== $NODE → $name ($ip) ==="

    TMP=$(mktemp)

    python3 - "$ip" "$PORT" "$COUNT" > "$TMP" <<'PYEOF'
import socket, time, sys

target = sys.argv[1]
port = int(sys.argv[2])
count = int(sys.argv[3])

try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    s.settimeout(3)
    s.connect((target, port))
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(2)

rtts = []
PAYLOAD = b"P" * 32

for i in range(count):
    t1 = time.perf_counter_ns()
    try:
        s.sendall(PAYLOAD)
        data = b""
        while len(data) < len(PAYLOAD):
            chunk = s.recv(len(PAYLOAD) - len(data))
            if not chunk:
                break
            data += chunk
    except Exception:
        continue
    t2 = time.perf_counter_ns()
    if data == PAYLOAD:
        rtts.append((t2 - t1) / 1e6)

s.close()

if not rtts:
    print("NORESP")
    sys.exit(0)

rtts.sort()
n = len(rtts)
avg = sum(rtts) / n
var = sum((x - avg) ** 2 for x in rtts) / n
sd = var ** 0.5

print(f"STATS {n} {rtts[0]:.4f} {avg:.4f} {rtts[-1]:.4f} {sd:.4f} "
      f"{rtts[n // 2]:.4f} {rtts[min(int(n * 0.95), n - 1)]:.4f}")
for r in rtts:
    print(f"RTT {r:.4f}")
PYEOF

    if ! grep -q "^STATS" "$TMP"; then
        echo "  无响应"
        echo "$NODE,$name,$ip,$PORT,$COUNT,0,100,,,,,," >> "$CSV"
        rm -f "$TMP"
        continue
    fi

    stats_line=$(grep "^STATS" "$TMP" | head -1)
    read _ n min avg max sd p50 p95 <<< "$stats_line"
    loss=$(awk -v s="$COUNT" -v r="$n" 'BEGIN{printf "%.2f", (s-r)/s*100}')

    echo "  min=$min  avg=$avg  max=$max  stddev=$sd  p50=$p50  p95=$p95  (n=$n/$COUNT, loss=$loss%)"

    echo "$NODE,$name,$ip,$PORT,$COUNT,$n,$loss,$min,$avg,$max,$sd,$p50,$p95" >> "$CSV"

    grep "^RTT" "$TMP" | awk '{print $2}' > /tmp/rtt_data.txt
    awk -v title="$NODE → $name" '
    { v[++n]=$1 }
    END {
        if (n==0) exit
        min=v[1]; max=v[1]
        for (i=2;i<=n;i++) { if (v[i]<min) min=v[i]; if (v[i]>max) max=v[i] }
        nb=10
        rng=max-min
        if (rng<0.05) rng=0.05
        w=rng/nb
        for (i=1;i<=n;i++) {
            b=int((v[i]-min)/w)
            if (b>=nb) b=nb-1
            cnt[b]++
        }
        maxc=0
        for (i=0;i<nb;i++) if (cnt[i]>maxc) maxc=cnt[i]
        printf "\n  %s  (n=%d, min=%.3f, max=%.3f, 桶宽=%.3fms)\n\n", title, n, min, max, w
        for (i=0;i<nb;i++) {
            lo=min+i*w; hi=lo+w
            c=cnt[i]+0
            barLen=(maxc>0)?int(c*50/maxc):0
            bar=""
            for (j=0;j<barLen;j++) bar=bar "#"
            printf "  %7.3f - %7.3f | %5d | %s\n", lo, hi, c, bar
        }
        print ""
    }' /tmp/rtt_data.txt

    rm -f "$TMP"
done

echo ""
echo "汇总：$CSV"
cat "$CSV" | column -t -s',' 2>/dev/null || cat "$CSV"
'''


def _neighbors(cfg):
    """返回 (node_map, adjacency)，adjacency[name] = [邻居名...]。

    优先用 active_edges（实际部署过的路径），没有才回退到 edges（全局拓扑图）。
    这样未参与部署的节点不会出现在测量目标里，避免测不通的报错。
    """
    node_map = {n["name"]: n for n in cfg.get("nodes", [])}
    adj = {n["name"]: [] for n in cfg.get("nodes", [])}
    edges = cfg.get("active_edges") or cfg.get("edges") or []
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in adj and t in adj and s != t:
            if t not in adj[s]:
                adj[s].append(t)
            if s not in adj[t]:
                adj[t].append(s)
    return node_map, adj


def build_script(cfg):
    """根据拓扑生成完整 tcp_rtt.sh 脚本文本。"""
    node_map, adj = _neighbors(cfg)
    lines = [SCRIPT_HEAD]
    for n in cfg.get("nodes", []):
        name = n["name"]
        wg_ip = n.get("wg_ip", "")
        if not wg_ip:
            continue
        targets = " ".join(
            f'"{node_map[nb].get("wg_ip", "")}:{nb}"' for nb in adj[name]
        )
        lines.append(f'    {wg_ip}) NODE="{name}"; TARGETS=({targets}) ;;\n')
    lines.append(SCRIPT_TAIL)
    return "".join(lines)


def deploy_script(cfg, selected=None):
    """生成脚本并分发到各 Linux 节点（并行）。返回 results 列表。"""
    script = build_script(cfg)
    nodes = [n for n in cfg.get("nodes", []) if not selected or n["name"] in selected]

    fd, tmp = tempfile.mkstemp(suffix=".sh")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(script)

        def worker(n):
            key = find_key(cfg, n)
            if not key:
                return {"name": n["name"], "ok": False, "detail": "找不到密钥（无 SSH，跳过）"}
            rc, o, e = ssh.push_file(n["ip"], key, tmp, "/root/tcp_rtt.sh")
            if rc != 0:
                return {"name": n["name"], "ok": False, "detail": (o + e).strip()}
            cmd = "sed -i 's/\\r//g' /root/tcp_rtt.sh; cp /root/tcp_rtt.sh /usr/local/bin/tcp_rtt.sh; chmod +x /usr/local/bin/tcp_rtt.sh /root/tcp_rtt.sh; echo DEPLOY_OK"
            code, out, err = ssh.run_ssh(n["ip"], key, cmd)
            ok = code == 0 and "DEPLOY_OK" in out
            return {"name": n["name"], "ok": ok, "detail": (out + err).strip() or "已分发"}

        if not nodes:
            return []
        with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
            return list(ex.map(worker, nodes))
    finally:
        os.unlink(tmp)
