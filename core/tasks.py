"""各业务任务：连通性、NTP、下发、清理、部署 echo、分发脚本、拉取结果。

所有命令均从现有 PowerShell 脚本的原生命令移植而来。
"""
import os
import json
import time
import shutil
from concurrent.futures import ThreadPoolExecutor
from . import ssh

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 管理员密码存放位置：logs 目录下的隐藏文件（明文，隐蔽存储）
PWD_PATH = os.path.join(BASE_DIR, "logs", ".admin_pwd")


def _map_nodes(cfg, selected, worker):
    """并行执行 worker(node) 于所有选中节点，保持顺序返回结果列表。

    worker(node) 返回结果 dict（或 None 表示跳过）。
    用线程池并行，把串行 N 节点耗时降为最慢单节点耗时。
    """
    nodes = [n for n in cfg["nodes"] if not selected or n["name"] in selected]
    if not nodes:
        return []
    with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
        return [r for r in ex.map(worker, nodes) if r is not None]


def get_password():
    """读取管理员密码；不存在返回 None。"""
    if os.path.isfile(PWD_PATH):
        with open(PWD_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def set_password(pwd):
    """写入管理员密码（明文，隐藏文件）。"""
    os.makedirs(os.path.dirname(PWD_PATH), exist_ok=True)
    with open(PWD_PATH, "w", encoding="utf-8") as f:
        f.write(pwd)


def is_first_start():
    cfg = load_config()
    return bool(cfg.get("start_first", True))


def mark_started():
    cfg = load_config()
    cfg["start_first"] = False
    save_config(cfg)


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def find_key(cfg, node):
    """查找节点私钥：优先 _preliminary_test.pem，其次 preliminary_test.pem，最后任意 .pem。"""
    base = cfg.get("key_base", "")
    d = os.path.join(base, node.get("key_dir", ""))
    if not os.path.isdir(d):
        return None
    for cand in ("_preliminary_test.pem", "preliminary_test.pem"):
        p = os.path.join(d, cand)
        if os.path.isfile(p):
            return p
    for fn in os.listdir(d):
        if fn.lower().endswith(".pem"):
            return os.path.join(d, fn)
    return None


def _check_ssh(cfg, node):
    key = find_key(cfg, node)
    if not key:
        return False, "找不到密钥"
    code, out, err = ssh.run_ssh(node["ip"], key, "echo OK && hostname")
    if code == 0 and "OK" in out:
        return True, out.strip().splitlines()[-1]
    return False, (err or out).strip()


# ---------------- 连通性测试 ----------------
def test_connectivity(cfg, selected=None):
    def worker(n):
        key = find_key(cfg, n)
        if not key:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "找不到密钥"}
        cmd = (
            "echo '--- wg show ---'; sudo wg show 2>/dev/null | head -20; "
            "echo '--- ip_forward ---'; sysctl net.ipv4.ip_forward 2>/dev/null; "
            "echo '--- tcp-echo ---'; systemctl is-active tcp-echo 2>/dev/null; "
            "echo '--- tcp_rtt ---'; test -x /root/tcp_rtt.sh && echo present || echo missing"
        )
        code, out, err = ssh.run_ssh(n["ip"], key, cmd)
        return {"name": n["name"], "ip": n["ip"], "ok": code == 0, "detail": out + ("\n[stderr] " + err if err else "")}
    return _map_nodes(cfg, selected, worker)


# ---------------- NTP 测试 ----------------
def test_ntp(cfg, selected=None):
    def worker(n):
        key = find_key(cfg, n)
        if not key:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "找不到密钥"}
        code, out, err = ssh.run_ssh(n["ip"], key, "chronyc tracking 2>/dev/null | grep 'System time' || echo '未安装 chrony 或无数据'")
        return {"name": n["name"], "ip": n["ip"], "ok": code == 0, "detail": out.strip()}
    return _map_nodes(cfg, selected, worker)


# ---------------- 下发定时测量任务 ----------------
def schedule_task(cfg, start_time, count, selected=None):
    """对应 sync_start.ps1：systemd-run --on-calendar 定时启动 tcp_rtt.sh。"""
    time_str = start_time.replace(":", "")

    def worker(n):
        key = find_key(cfg, n)
        if not key:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "找不到密钥"}
        cmd = (
            f"{_remote_clean_cmd()}; "
            f"systemd-run --on-calendar=\"{start_time}\" "
            f"--unit=\"sync-{time_str}-$(date +%s)\" /bin/bash -c "
            f"\"TAG={time_str} /root/tcp_rtt.sh {count} > /root/rtt_results/sync_{time_str}_$(hostname).log 2>&1\""
        )
        code, out, err = ssh.run_ssh(n["ip"], key, cmd)
        return {"name": n["name"], "ip": n["ip"], "ok": code == 0, "detail": (out + err).strip()}
    return _map_nodes(cfg, selected, worker)


# ---------------- 清理定时器 ----------------
def clean_timers(cfg, selected=None):
    """对应 sync_clean.ps1：停掉并删除所有 sync-* 定时器。"""
    def worker(n):
        key = find_key(cfg, n)
        if not key:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "找不到密钥"}
        cmd = (
            "systemctl list-timers 'sync-*' --all --no-legend 2>/dev/null | awk '{print $NF}' | xargs -r systemctl stop; "
            "rm -f /etc/systemd/system/sync-* /run/systemd/transient/sync-*; "
            "systemctl daemon-reload; systemctl reset-failed; echo CLEANED"
        )
        code, out, err = ssh.run_ssh(n["ip"], key, cmd)
        return {"name": n["name"], "ip": n["ip"], "ok": code == 0, "detail": (out + err).strip()}
    return _map_nodes(cfg, selected, worker)


# ---------------- 获取定时任务列表 ----------------
def list_timers(cfg, selected=None):
    """列出各节点已下发的 sync-* 定时任务。

    返回 {name, ok, detail, timers: [{unit, next}]}
    """
    def worker(n):
        key = find_key(cfg, n)
        if not key:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "找不到密钥", "timers": []}
        code, out, err = ssh.run_ssh(
            n["ip"], key,
            "systemctl list-timers 'sync-*' --all --no-pager --no-legend 2>/dev/null"
        )
        timers = []
        if code == 0:
            for line in out.splitlines():
                parts = line.split()
                # 列：NEXT(3列) LEFT(2列) LAST(3列) PASSED(2列) UNIT ACTIVATES
                # 找 UNIT 列（含 .timer 的字段）
                unit = None
                for p in parts:
                    if ".timer" in p:
                        unit = p
                        break
                if unit:
                    nxt = " ".join(parts[:3])  # NEXT 通常是 "Thu 2026-10-22 15:31:20 CST"
                    timers.append({"unit": unit, "next": nxt})
        return {"name": n["name"], "ip": n["ip"], "ok": code == 0, "detail": (err or "").strip(), "timers": timers}
    return _map_nodes(cfg, selected, worker)


# ---------------- 部署 tcp_echo 服务 ----------------
TCP_ECHO_PY = """#!/usr/bin/env python3
import socket
import sys
import threading

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9000


def handle(conn, addr):
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            conn.sendall(data)
    except Exception:
        pass
    finally:
        conn.close()


def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', PORT))
    s.listen(128)
    print(f"TCP echo server on 0.0.0.0:{PORT}", flush=True)
    while True:
        conn, addr = s.accept()
        threading.Thread(target=handle, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
"""

TCP_ECHO_SVC = """[Unit]
Description=TCP Echo Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /root/tcp_echo.py 9000
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
"""


def deploy_echo(cfg, selected=None):
    """对应 deploy_echo.ps1：上传 tcp_echo.py + systemd 服务并启动。"""
    import tempfile
    tmp_dir = tempfile.mkdtemp()
    py_path = os.path.join(tmp_dir, "tcp_echo.py")
    svc_path = os.path.join(tmp_dir, "tcp-echo.service")
    with open(py_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(TCP_ECHO_PY)
    with open(svc_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(TCP_ECHO_SVC)

    def worker(n):
        key = find_key(cfg, n)
        if not key:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "找不到密钥"}
        rc1, o1, e1 = ssh.push_file(n["ip"], key, py_path, "/root/tcp_echo.py")
        rc2, o2, e2 = ssh.push_file(n["ip"], key, svc_path, "/etc/systemd/system/tcp-echo.service")
        if rc1 != 0 or rc2 != 0:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": (o1 + e1 + o2 + e2).strip()}
        cmd = (
            "sed -i 's/\\r//g' /root/tcp_echo.py /etc/systemd/system/tcp-echo.service; "
            "systemctl daemon-reload; systemctl enable --now tcp-echo; systemctl is-active tcp-echo"
        )
        code, out, err = ssh.run_ssh(n["ip"], key, cmd)
        return {"name": n["name"], "ip": n["ip"], "ok": code == 0 and "active" in out, "detail": (out + err).strip()}

    try:
        return _map_nodes(cfg, selected, worker)
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------- 分发最新 tcp_rtt.sh ----------------
def fetch_script(cfg, selected=None):
    """对应 fetch_auto.ps1：上传最新 tcp_rtt.sh 到 /root/ 并安装为全局命令。"""
    script_path = cfg.get("script_path", "")
    if not os.path.isfile(script_path):
        return [{"name": "(本地)", "ip": "-", "ok": False, "detail": f"脚本不存在: {script_path}"}]

    def worker(n):
        key = find_key(cfg, n)
        if not key:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "找不到密钥"}
        rc, o, e = ssh.push_file(n["ip"], key, script_path, "/root/tcp_rtt.sh")
        if rc != 0:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": (o + e).strip()}
        cmd = "sed -i 's/\\r//g' /root/tcp_rtt.sh; cp /root/tcp_rtt.sh /usr/local/bin/tcp_rtt.sh; chmod +x /usr/local/bin/tcp_rtt.sh /root/tcp_rtt.sh; echo DEPLOY_OK"
        code, out, err = ssh.run_ssh(n["ip"], key, cmd)
        return {"name": n["name"], "ip": n["ip"], "ok": code == 0 and "DEPLOY_OK" in out, "detail": (out + err).strip()}
    return _map_nodes(cfg, selected, worker)


# ---------------- 拉取结果 ----------------
def fetch_results(cfg, time_str, selected=None):
    """对应 get_results.ps1：拉取指定时间的结果文件，成功后自动打开资源管理器。"""
    results_dir = cfg.get("results_dir", "")
    target_dir = os.path.join(results_dir, f"Meas_{time_str}")
    os.makedirs(target_dir, exist_ok=True)
    pulled_flag = []

    def worker(n):
        key = find_key(cfg, n)
        if not key:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "找不到密钥"}
        # 1. 检查是否生成 log 文件
        code, out, err = ssh.run_ssh(n["ip"], key, f"ls /root/rtt_results/sync_{time_str}*.log 2>/dev/null")
        if code == 0 and f"sync_{time_str}" in out:
            # 先拉日志
            rc, o, e = ssh.pull_files(n["ip"], key, f"/root/rtt_results/sync_{time_str}*", target_dir)
            ok = rc == 0
            # 从日志里解析实际生成的 CSV 路径（日志末尾有 "汇总：/root/rtt_results/xxx.csv"）
            # 不依赖文件名时间戳，避免定时任务实际执行时间与下发时间秒级偏差导致拉不到
            _, gout, _ = ssh.run_ssh(n["ip"], key,
                f"grep -ho '/root/rtt_results/[^ ]*\\.csv' /root/rtt_results/sync_{time_str}*.log 2>/dev/null | head -1")
            ok2 = False
            if gout.strip():
                csv_path = gout.strip().splitlines()[0]
                prefix = csv_path.rsplit("/", 1)[-1]
                if prefix.endswith(".csv"):
                    prefix = prefix[:-4]
                rc2, o2, e2 = ssh.pull_files(n["ip"], key, f"/root/rtt_results/{prefix}*.csv", target_dir)
                ok2 = rc2 == 0
            if ok or ok2:
                pulled_flag.append(True)
            return {"name": n["name"], "ip": n["ip"], "ok": ok or ok2,
                    "detail": "已拉取日志+CSV" if (ok and ok2) else ("已拉取日志(无CSV)" if ok else (o + e).strip())}
        # 2. 检查任务是否还在运行
        code2, out2, _ = ssh.run_ssh(n["ip"], key, f"systemctl list-units 'sync-*' --all --no-legend | grep '{time_str}'")
        if code2 == 0 and "running" in out2:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "任务正在运行中"}
        elif code2 == 0 and "failed" in out2:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "任务执行失败"}
        return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "未找到该时间的任务或结果"}

    results = _map_nodes(cfg, selected, worker)

    # 拉取到至少一个文件后，自动打开结果文件夹
    if pulled_flag and os.path.isdir(target_dir):
        try:
            os.startfile(target_dir)  # Windows 资源管理器
        except Exception:
            pass
    return results


# ---------------- 本地结果清理 ----------------
def list_batches(cfg):
    """列出本地已拉取的测量批次（Meas_* 文件夹）。"""
    results_dir = cfg.get("results_dir", "")
    batches = []
    if results_dir and os.path.isdir(results_dir):
        for name in os.listdir(results_dir):
            p = os.path.join(results_dir, name)
            if name.startswith("Meas_") and os.path.isdir(p):
                try:
                    cnt = len([f for f in os.listdir(p) if f.endswith(".csv") and ".raw." not in f])
                    batches.append({"name": name, "files": cnt, "mtime": os.path.getmtime(p)})
                except OSError:
                    continue
    batches.sort(key=lambda x: x["mtime"], reverse=True)
    return batches


def read_batch_data(cfg, batch):
    """读取某个批次的摘要 CSV，返回去重后的 src→dst 链路测量数据。"""
    import csv as csvmod
    results_dir = cfg.get("results_dir", "")
    batch_dir = os.path.join(results_dir, batch)
    if not os.path.isdir(batch_dir):
        return {"ok": False, "error": "批次不存在"}

    links = {}
    for fn in os.listdir(batch_dir):
        if not fn.endswith(".csv") or ".raw." in fn:
            continue
        p = os.path.join(batch_dir, fn)
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for row in csvmod.DictReader(f):
                    src = (row.get("src") or "").strip()
                    dst = (row.get("dst") or "").strip()
                    if not src or not dst or src == dst:
                        continue
                    try:
                        mn = float(row.get("min_ms") or 0)
                        avg = float(row.get("avg_ms") or 0)
                        mx = float(row.get("max_ms") or 0)
                        sd = float(row.get("stddev_ms") or 0)
                    except (ValueError, TypeError):
                        continue
                    if mn == 0 and avg == 0 and mx == 0:
                        continue
                    key = tuple(sorted([src, dst]))
                    if key not in links:
                        links[key] = {"src": src, "dst": dst, "min": mn, "avg": avg,
                                      "max": mx, "stddev": sd}
        except Exception:
            continue
    return {"ok": True, "batch": batch, "links": list(links.values())}


def results_stats(cfg, max_count=500, max_days=30):
    """统计本地结果目录：数量、最早时间、是否触发清理阈值。"""
    results_dir = cfg.get("results_dir", "")
    entries = []
    if results_dir and os.path.isdir(results_dir):
        for name in os.listdir(results_dir):
            p = os.path.join(results_dir, name)
            if name.startswith("Meas_") and os.path.isdir(p):
                try:
                    entries.append((os.path.getmtime(p), name))
                except OSError:
                    continue
    count = len(entries)
    earliest = None
    exceeds = False
    if entries:
        entries.sort(key=lambda x: x[0])
        earliest = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entries[0][0]))
        age_days = (time.time() - entries[0][0]) / 86400.0
        exceeds = count > max_count or age_days > max_days
    return {
        "count": count,
        "earliest": earliest,
        "exceeds": exceeds,
        "max_count": max_count,
        "max_days": max_days,
        "results_dir": results_dir,
    }


def clean_local_results(cfg, max_count=500, max_days=30):
    """清理本地结果目录下的 Meas_* 文件夹。

    规则：按目录修改时间从新到旧，保留最新 max_count 个；
    超过 max_days 天的也一并删除。返回被删除的文件夹名列表。
    """
    results_dir = cfg.get("results_dir", "")
    if not results_dir or not os.path.isdir(results_dir):
        return []

    entries = []
    for name in os.listdir(results_dir):
        p = os.path.join(results_dir, name)
        if name.startswith("Meas_") and os.path.isdir(p):
            try:
                entries.append((os.path.getmtime(p), name, p))
            except OSError:
                continue

    # 按修改时间从新到旧
    entries.sort(key=lambda x: x[0], reverse=True)
    now = time.time()
    removed = []
    for idx, (mtime, name, p) in enumerate(entries):
        age_days = (now - mtime) / 86400.0
        if idx >= max_count or age_days > max_days:
            try:
                shutil.rmtree(p)
                removed.append(name)
            except Exception:
                pass
    return removed


# ---------------- 远端结果清理 ----------------
def _remote_clean_cmd(max_count=500, max_days=30):
    """生成远端清理 shell 片段：删除 30 天前的 CSV，并保留最新 max_count 个。

    末尾统一带 2>/dev/null || true，确保只读盘/权限异常时彻底静默、绝不失败，
    不会影响调用方（下发任务、启动清理）的主流程。
    """
    return (
        f"find /root/rtt_results -maxdepth 1 -name '*.csv' -mtime +{max_days} -delete 2>/dev/null || true; "
        f"ls -1t /root/rtt_results/*.csv 2>/dev/null | tail -n +{max_count + 1} | xargs -r rm -f 2>/dev/null || true"
    )


def clean_remote_results(cfg, selected=None, max_count=500, max_days=30):
    """并行清理各节点 /root/rtt_results 下的旧 CSV。"""
    def worker(n):
        key = find_key(cfg, n)
        if not key:
            return {"name": n["name"], "ip": n["ip"], "ok": False, "detail": "找不到密钥"}
        cmd = _remote_clean_cmd(max_count, max_days) + "; echo CLEAN_OK"
        code, out, err = ssh.run_ssh(n["ip"], key, cmd)
        return {"name": n["name"], "ip": n["ip"], "ok": code == 0 and "CLEAN_OK" in out,
                "detail": (out + err).strip() or "已清理"}
    return _map_nodes(cfg, selected, worker)


def remote_results_stats(cfg, selected=None, max_count=500, max_days=30):
    """并行统计各节点 /root/rtt_results/*.csv 的数量、最早修改时间、是否超阈值。"""
    def worker(n):
        key = find_key(cfg, n)
        if not key:
            return {"name": n["name"], "ok": False, "count": 0, "earliest": None,
                    "age_days": -1, "exceeds": False, "detail": "找不到密钥"}
        cmd = (
            "count=$(ls -1 /root/rtt_results/*.csv 2>/dev/null | wc -l | tr -d ' '); "
            "oldest=$(stat -c '%Y' /root/rtt_results/*.csv 2>/dev/null | sort -n | head -1); "
            "earliest=$(stat -c '%y' /root/rtt_results/*.csv 2>/dev/null | sort | head -1 | cut -d'.' -f1); "
            "now=$(date +%s); "
            "if [ -n \"$oldest\" ]; then age=$(( (now - oldest) / 86400 )); else age=-1; fi; "
            "echo \"COUNT=$count\"; echo \"EARLIEST=$earliest\"; echo \"AGE_DAYS=$age\""
        )
        code, out, err = ssh.run_ssh(n["ip"], key, cmd)
        d = {"name": n["name"], "ok": code == 0, "count": 0,
             "earliest": None, "age_days": -1, "detail": (err or "").strip()}
        if code == 0:
            for line in out.splitlines():
                if line.startswith("COUNT="):
                    try:
                        d["count"] = int(line[6:].strip())
                    except ValueError:
                        pass
                elif line.startswith("EARLIEST="):
                    v = line[9:].strip()
                    d["earliest"] = v or None
                elif line.startswith("AGE_DAYS="):
                    try:
                        d["age_days"] = int(line[9:].strip())
                    except ValueError:
                        pass
        d["exceeds"] = d["count"] > max_count or d["age_days"] > max_days
        return d
    return _map_nodes(cfg, selected, worker)
