# rtt-manager —— 蜘蛛网络控制台

集成化 Web 工具：一键配置密钥路径 / tcp_rtt 脚本路径，一键下发定时测量任务、抓取结果、测试连通性 / NTP，替代手动敲 SSH 指令。

## 一、环境要求（迁移到新主机只需 3 项）

1. **Python 3.10+**
2. **OpenSSH Client**（Windows 10/11 自带，命令行 `ssh`、`scp` 可用）
3. **Python 依赖**：`fastapi`、`uvicorn`

### 依赖安装

```powershell
pip install -r requirements.txt
```

## 二、启动

双击 `start.bat`，程序**后台运行**，不出现控制台窗口，仅显示在**系统托盘**（任务栏右下角隐藏图标）。

- 托盘图标右键菜单：**打开控制台**（自动打开浏览器 http://127.0.0.1:8000）、**重启服务**、**退出**。
- 日志写入 `logs/app.log`，后台排查用。

也可手动前台运行（带控制台，调试用）：

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

托盘后台模式依赖 `pystray`、`pillow`，均已写入 `requirements.txt`。

## 三、首次启动与管理员登录

首次启动（`config.json` 中 `start_first` 为 `true`）时，浏览器会弹出**首次启动引导**，要求填写：

- 密钥目录（`key_base`）
- 结果保存目录（`results_dir`）
- 管理员密码（唯一账号，单账号体系）

完成设置后 `start_first` 置为 `false`，之后每次启动显示**管理员登录**界面，输入密码进入。

### 密码存储位置

管理员密码以**明文**存储，但放在隐蔽位置：

```
logs/.admin_pwd
```

这是一个隐藏文件（`.` 开头的点文件），与日志同目录、不起眼。**明文存储仅为当前阶段的临时方案**，后续可改为哈希或环境变量。忘记密码时，删除该文件后重启，会重新进入首次启动引导（需重新设置密码，节点等其它配置保留）。

## 三、配置文件（所有可选项均不写死在代码里）

| 文件 | 作用 | 说明 |
|---|---|---|
| `python_path.txt` | Python 解释器路径 | 第一行写完整路径，如 `D:\anaconda3\python.exe`。`start.bat` 优先读它，找不到才回退到 PATH 里的 `python`。**迁移主机只改这一个文件即可。** |
| `config.json` | 节点、密钥目录、脚本路径、结果目录、默认参数 | 也可通过网页右上角「配置」按钮修改，改动即时生效。 |
| `requirements.txt` | Python 依赖清单 | 新主机执行 `pip install -r requirements.txt`。 |

### config.json 字段说明

| 字段 | 含义 |
|---|---|
| `key_base` | 密钥根目录（如 `C:\Users\...\Desktop\密钥对`） |
| `script_path` | 最新版 tcp_rtt.sh 的本地路径 |
| `results_dir` | 拉取结果保存目录 |
| `defaults.count / time` | 默认测量次数 / 下发时间 |
| `nodes` | 节点列表（name / ip / key_dir / role） |

密钥查找规则：每个节点的 `key_dir` 目录下优先 `_preliminary_test.pem`，其次 `preliminary_test.pem`，最后任意 `.pem`。

| 字段 | 含义 |
|---|---|
| `key_base` | 密钥根目录（如 `C:\Users\...\Desktop\密钥对`） |
| `script_path` | 最新版 tcp_rtt.sh 的本地路径 |
| `results_dir` | 拉取结果保存目录 |
| `defaults.count / time` | 默认测量次数 / 下发时间 |
| `nodes` | 节点列表（name / ip 公网IP / wg_ip 内网IP / public_key / listen_port / dynamic / key_dir / role / routes） |
| `edges` | 拓扑连接关系（source / target，用节点 name 标识） |

密钥查找规则：每个节点的 `key_dir` 目录下优先 `_preliminary_test.pem`，其次 `preliminary_test.pem`，最后任意 `.pem`。

## 四、功能与对应原脚本

| 网页按钮 | 原脚本 |
|---|---|
| 连通性测试 | （新增：wg show + ip_forward + tcp-echo + 脚本检查） |
| NTP 测试 | `testNTP.ps1` |
| 下发定时任务 | `sync_start.ps1` |
| 清理定时器 | `sync_clean.ps1` |
| 拉取结果 | `get_results.ps1` |
| 分发最新 tcp_rtt.sh | `fetch_auto.ps1` |
| 部署 tcp_echo 服务 | `deploy_echo.ps1` |
| **拓扑编辑** | （新增：可拖动节点/连边的拓扑图，可视化定义节点连接关系） |

## 五、拓扑编辑器

右上角「拓扑编辑」按钮打开全屏拓扑画布：

- **拖拽节点**移动位置；**双击节点**编辑属性（名称/角色/公网IP/内网IP/公钥/密钥目录/端口/转发路由）。
- **连边模式**：点「连边模式」后依次点两个节点建立连接（连线方向 = 谁连谁）。
- **右键**节点/边可删除；**自动布局**重排；**保存拓扑**写回 config.json。
- 节点颜色按角色区分：gateway 橙 / server 红 / relay 紫 / client 绿。

> 依赖 Cytoscape.js（`static/vendor/` 已本地化，离线可用）。拓扑图与 config.json 的 `nodes` + `edges` 双向同步。

### 选路径生成 WireGuard 配置

在拓扑图里点「选路径」，然后**按顺序点击节点**组成一条路径（绿色高亮 + 序号）：

- **预览配置**：后台用「割集」算法为路径上每个节点生成 wg0.conf（AllowedIPs = 邻居 + 经邻居可达的下游），弹窗展示。
- **部署**：SSH 幂等获取私钥 → 上传 conf → 暴力重启（`ip link delete wg0`，避免 `wg-quick down` 卡死）→ 中间节点自动开内核转发 + iptables。

> 单条路径独立生成，不兼顾全网其它路径，避免 AllowedIPs 冲突。

## 五、注意事项

- **代理**：若开着 Clash 等代理，需将阿里云节点 IP 加入直连白名单，否则 ssh/scp 会断连。
- **CRLF**：下发命令统一走 `tr -d '\r' | bash -s`，上传脚本后执行 `sed -i 's/\r//g'`，避免回车符问题。
- **端口**：需能直连节点公网 IP 的 22 端口；阿里云安全组放行 UDP 51820。
