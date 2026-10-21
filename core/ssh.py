"""SSH / SCP 封装：通过 subprocess 调用 Windows 自带的 ssh.exe / scp.exe。

选择 subprocess 而非 paramiko 的原因：
1. 复用系统 OpenSSH，密钥文件（OpenSSH 格式 .pem）直接可用，无需转换。
2. 与本机已有的手动操作行为完全一致，规避代理、known_hosts 等差异。
"""
import subprocess
import os


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


def run_ssh(ip, key_path, command, timeout=60):
    """在远端执行命令，返回 (exit_code, stdout, stderr)。

    命令通过 stdin 传入 bash，规避 CRLF 问题。
    """
    args = _ssh_args(key_path) + [f"root@{ip}", "tr -d '\\r' | bash -s"]
    try:
        proc = subprocess.run(
            args,
            input=command.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return proc.returncode, proc.stdout.decode("utf-8", errors="replace"), proc.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return -1, "", "SSH 连接超时"
    except FileNotFoundError:
        return -1, "", "未找到 ssh.exe，请确认已安装 OpenSSH Client"


def push_file(ip, key_path, local_path, remote_path, timeout=60):
    """上传文件到远端。"""
    args = _scp_args(key_path) + [local_path, f"root@{ip}:{remote_path}"]
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return proc.returncode, proc.stdout.decode("utf-8", errors="replace"), proc.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return -1, "", "SCP 连接超时"
    except FileNotFoundError:
        return -1, "", "未找到 scp.exe，请确认已安装 OpenSSH Client"


def pull_files(ip, key_path, remote_glob, local_dir, timeout=120):
    """从远端拉取文件到本地目录。remote_glob 支持通配符。"""
    os.makedirs(local_dir, exist_ok=True)
    args = _scp_args(key_path) + [f"root@{ip}:{remote_glob}", local_dir]
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return proc.returncode, proc.stdout.decode("utf-8", errors="replace"), proc.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return -1, "", "SCP 连接超时"
    except FileNotFoundError:
        return -1, "", "未找到 scp.exe"
