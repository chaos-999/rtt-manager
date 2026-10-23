"""SSH / SCP 封装：通过 subprocess 调用 Windows 自带的 ssh.exe / scp.exe。

选择 subprocess 而非 paramiko 的原因：
1. 复用系统 OpenSSH，密钥文件（OpenSSH 格式 .pem）直接可用，无需转换。
2. 与本机已有的手动操作行为完全一致，规避代理、known_hosts 等差异。

自带重试：连接类失败（超时 / 拒绝 / 不可达 / 重置等）自动重试，
默认 3 次、间隔 1 秒；业务性失败（命令返回非 0 且非连接错误）不重试。
"""
import subprocess
import os
import time

RETRIES = 3
RETRY_DELAY = 1.0

_CONN_ERROR_HINTS = (
    "connection timed out",
    "connection refused",
    "no route to host",
    "network is unreachable",
    "connection reset",
    "broken pipe",
    "connection closed",
    "operation timed out",
    "timed out",
)


def _should_retry(code, err):
    """判断是否值得重试：进程超时或 stderr 命中连接类错误。"""
    if code == -1:
        return True
    if code != 0:
        e = (err or "").lower()
        return any(h in e for h in _CONN_ERROR_HINTS)
    return False


def _run(args, input_bytes=None, timeout=60, retries=RETRIES):
    """执行命令，连接类失败自动重试。返回 (exit_code, stdout, stderr)。"""
    last = (-1, "", "未知错误")
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        try:
            proc = subprocess.run(
                args,
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            code = proc.returncode
            out = proc.stdout.decode("utf-8", errors="replace")
            err = proc.stderr.decode("utf-8", errors="replace")
            last = (code, out, err)
            if not _should_retry(code, err):
                return last
        except subprocess.TimeoutExpired:
            last = (-1, "", "命令执行超时")
        except FileNotFoundError:
            return -1, "", "未找到 ssh.exe/scp.exe，请确认已安装 OpenSSH Client"
        if attempt < attempts - 1:
            time.sleep(RETRY_DELAY)
    return last


def _ssh_args(key_path):
    return [
        "ssh",
        "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=8",
        "-o", "BatchMode=yes",
    ]


def _scp_args(key_path):
    return [
        "scp",
        "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=8",
        "-o", "BatchMode=yes",
    ]


def run_ssh(ip, key_path, command, timeout=60, retries=RETRIES):
    """在远端执行命令，返回 (exit_code, stdout, stderr)。

    命令通过 stdin 传入 bash，规避 CRLF 问题。
    """
    args = _ssh_args(key_path) + [f"root@{ip}", "tr -d '\\r' | bash -s"]
    return _run(args, input_bytes=command.encode("utf-8"), timeout=timeout, retries=retries)


def push_file(ip, key_path, local_path, remote_path, timeout=60, retries=RETRIES):
    """上传文件到远端。"""
    args = _scp_args(key_path) + [local_path, f"root@{ip}:{remote_path}"]
    return _run(args, timeout=timeout, retries=retries)


def pull_files(ip, key_path, remote_glob, local_dir, timeout=120, retries=RETRIES):
    """从远端拉取文件到本地目录。remote_glob 支持通配符。"""
    os.makedirs(local_dir, exist_ok=True)
    args = _scp_args(key_path) + [f"root@{ip}:{remote_glob}", local_dir]
    return _run(args, timeout=timeout, retries=retries)
