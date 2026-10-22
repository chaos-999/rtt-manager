# rtt-manager —— 蜘蛛网络控制台

集成化 Web 工具，用于管理基于 WireGuard 的「蜘蛛网络」测量集群：一键配置、下发定时测量任务、拉取结果、测试连通性 / NTP、可视化编辑拓扑、按路径生成并部署 WireGuard 配置、自动生成测量脚本。替代手动 SSH 逐台敲命令。

- 后端：FastAPI（`main.py`）
- 前端：原生 HTML/JS + Cytoscape.js（`static/`）
- 运行方式：本机后台常驻 + 系统托盘
- 通过 Windows 自带 OpenSSH 的 `ssh.exe` / `scp.exe` 操作远端节点

---

## 一、功能概览

| 模块 | 功能 |
|---|---|
| 启动/登录 | 首次启动引导、管理员登录（单账号）、系统托盘常驻 |
| 状态检查 | 连通性测试、NTP 时钟偏差测试 |
| 测量任务 | 下发定时任务、清理定时器、获取定时任务列表 |
| 结果与脚本 | 拉取结果（日志 + 统计 CSV + 原始 RTT）、检测/清理结果、生成并分发 tcp_rtt.sh、部署 tcp_echo 服务 |
| 数据可视化 | 中国地图展示全部节点 + 等时延同心圆（avg ±3σ），可缩放/悬停 |
| 拓扑编辑 | 拖拽节点、连边、增删改节点、自动布局、保存拓扑 |
| WireGuard | 选路径 → 预览/部署 wg0.conf（自动割集算法、精确路由、开转发） |

---

## 二、环境要求

1. **Python 3.10+**
2. **OpenSSH Client**（Windows 10/11 自带，命令行 `ssh`、`scp` 可用）
3. **Python 依赖**：`fastapi`、`uvicorn`、`pystray`、`pillow`

```powershell
pip install -r requirements.txt
```

---

## 三、启动与系统托盘

双击 `start.bat`，程序**后台运行**，不出现控制台窗口，仅显示在**系统托盘**（任务栏右下角隐藏图标）。

托盘图标右键菜单：

- **打开控制台**：自动打开浏览器 `http://127.0.0.1:8000`
- **重启服务**：优雅停止并重启后端 uvicorn（不用手动关掉再开）
- **退出**：停止服务并退出

日志写入 `logs/app.log`（滚动日志，便于后台排查）。

手动前台运行（调试用）：

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

> `start.bat` 优先读 `python_path.txt` 中的 Python 路径，找不到再用 PATH 里的 `python`。迁移主机只需改这一个文件。
> 若开着 Clash 等代理，需将阿里云节点 IP 加入直连白名单，否则 ssh/scp 会断连。

---

## 四、首次启动与管理员登录

首次启动（`config.json` 中 `start_first` 为 `true`）时，浏览器弹出**首次启动引导**，要求填写：

- 密钥目录（`key_base`）
- 结果保存目录（`results_dir`）
- 管理员密码（唯一账号，单账号体系）

完成后 `start_first` 置为 `false`，之后每次启动显示**管理员登录**界面，输入密码进入。

### 密码存储位置

管理员密码以**明文**存储在隐蔽位置：

```
logs/.admin_pwd
```

它是一个点开头的隐藏文件，与日志同目录。**明文存储仅为当前阶段的临时方案**。忘记密码时删除该文件后重启，会重新进入首次启动引导（重新设置密码，其它配置保留）。

---

## 五、配置文件

| 文件 | 作用 |
|---|---|
| `config.json` | 全部业务配置（节点/目录/拓扑/坐标），网页「配置」按钮也可修改 |
| `python_path.txt` | Python 解释器路径（第一行写完整路径，如 `D:\anaconda3\python.exe`） |
| `requirements.txt` | Python 依赖清单 |

### config.json 字段说明

| 字段 | 含义 |
|---|---|
| `start_first` | 是否首次启动（`true` 时进入引导） |
| `key_base` | 密钥根目录（如 `C:\Users\...\Desktop\密钥对`） |
| `results_dir` | 拉取结果的本地保存目录 |
| `defaults.count` | 默认测量次数（如 1000） |
| `defaults.time` | 默认下发时间（HH:mm:ss） |
| `nodes[]` | 节点列表，见下 |
| `edges[]` | 拓扑连接关系（全局拓扑图，`source` / `target` 为节点名） |
| `active_edges[]` | **实际部署生效**的拓扑（部署 WireGuard 路径时自动覆盖写入），tcp_rtt 生成优先用它 |
| `script_path` | 已弃用，可忽略 |

节点 `nodes[]` 字段：

| 字段 | 含义 |
|---|---|
| `name` | 节点名（唯一标识，中文即可） |
| `ip` | 公网 IP（生成 Endpoint 用） |
| `wg_ip` | WireGuard 内网 IP（生成 Address / AllowedIPs 用） |
| `public_key` | 公钥（生成对端 Peer 用） |
| `listen_port` | 监听端口，默认 51820 |
| `dynamic` | 是否动态 IP（true 则生成 conf 时省略 Endpoint） |
| `key_dir` | 密钥目录名（配合 `key_base` 定位私钥） |
| `role` | 角色（gateway / server / relay / client，仅用于着色） |
| `lat` / `lng` | 经纬度（数据可视化定位用，配置页可编辑；未填时回退内置城市坐标） |
| `pos_x` / `pos_y` | 拓扑画布中的坐标 |

**密钥查找规则**：每个节点 `key_base/key_dir/` 目录下优先 `_preliminary_test.pem`，其次 `preliminary_test.pem`，最后任意 `.pem`。

---

## 六、界面功能详解

### 6.1 状态检查

- **连通性测试**：并行 SSH 到勾选节点，检查 `wg show`、`ip_forward`、`tcp-echo` 服务状态、`tcp_rtt.sh` 是否存在。
- **NTP 测试**：并行执行 `chronyc tracking`，显示各节点时钟偏差。

> 所有节点操作均用**线程池并行**，6 个节点从串行 ~10s 降到 ~1–2s。

### 6.2 下发测量任务

- **时间 / 次数**：设定测量启动时间和每对邻居的 ping 次数。
- **下发定时任务**：SSH 执行 `systemd-run --on-calendar`，在指定时间启动 `/root/tcp_rtt.sh`。日志名固定为 `sync_<时间>_<hostname>.log`，并传入 `TAG=<时间>` 环境变量。
- **清理定时器**：停掉并删除所有 `sync-*` 定时器/残留。
- **获取定时任务列表**：读取各节点 `systemctl list-timers 'sync-*'`，展示任务名与下次触发时间，并把时间戳自动填入「测量时间」下拉，方便直接选择拉取。

### 6.3 结果与脚本

- **拉取结果**：根据「测量时间」拉取本次测量产物（见第七节），成功后**自动打开资源管理器**定位到结果文件夹。
  - 实现细节：从远端日志末尾的「汇总：/root/rtt_results/xxx.csv」解析出真实 CSV 路径再拉取，避免定时任务实际执行时间与下发时间存在秒级偏差时漏拉。
- **检测结果数量**：并行统计**本地结果目录**与**每个云端节点** `rtt_results` 下的 CSV 数量和最早修改时间，逐行输出到执行日志。任一超出阈值（>500 个或 >30 天）时，「执行清理」按钮变为可点。
- **执行清理**：本地 + 远端同时清理（规则见第七节「自动清理机制」）。
- **生成并分发 tcp_rtt.sh**：根据当前拓扑（优先 `active_edges`，否则 `edges`）自动生成测量脚本——每个节点测哪些邻居由拓扑的边推导。先弹窗**预览脚本**，确认后再并行分发到勾选节点。
- **部署 tcp_echo 服务**：上传 `tcp_echo.py` + systemd 服务并启动（对端需运行此回显服务，tcp_rtt 才能测量）。

### 6.4 拓扑编辑

右上角「拓扑编辑」打开全屏拓扑画布（Cytoscape.js）：

- **拖拽节点**移动位置
- **双击节点**编辑属性（名称/角色/公网IP/内网IP/公钥/密钥目录/端口/动态IP）
- **连边模式**：点按钮后依次点两个节点建立连接
- **右键**节点/边删除；**自动布局**力导向重排；**保存拓扑**写回 `config.json`
- 节点按角色着色：gateway 橙 / server 红 / relay 紫 / client 绿
- 拓扑关闭再打开会保留画布状态；配置里增删节点后会自动同步到画布

### 6.5 选路径与 WireGuard 部署

在拓扑图点「选路径」，**按顺序点击节点**组成一条路径：

- **预览配置**：用「割集」算法为路径上每个节点生成 `wg0.conf`。对每个节点，其邻居 Peer 的 `AllowedIPs` = 邻居自身 + 经该邻居可达的下游所有节点（因路径是无分支链，等价于前缀/后缀）。弹窗展示，并标注哪些中间节点需要开转发。
- **部署**：并行 SSH 执行
  1. **幂等获取私钥**（仅当 `/etc/wireguard/privatekey` 不存在才生成，绝不覆盖，避免全网断联）
  2. 上传 `wg0.conf`
  3. **精确路由**：在 conf 的 `[Interface]` 自动生成 `PostUp/PreDown`，为每个目标 IP 建 `/32` 路由绑定本接口，解决多接口同网段的路由二义性（否则会报 `Required key not available`）
  4. **暴力重启**：`ip link delete wg0 || true` 再 `wg-quick up wg0`（避免 `wg-quick down` 卡死）
  5. 中间节点自动开 `ip_forward=1` + `iptables FORWARD ACCEPT`（幂等）
- 部署成功后，把这条路径的边**覆盖**写入 `active_edges`，供 tcp_rtt 生成使用。

> 单条路径独立生成，不兼顾全网其它路径，避免 AllowedIPs 冲突。

### 6.6 数据可视化（中国地图 + 等时延圆）

「结果与脚本」面板点「**数据可视化**」打开全屏地图：

- **数据范围**：顶部下拉选择本地已拉取的批次（`Meas_*`），默认最新。
- **画什么**：
  - 图上显示**所有拓扑节点**（config 里的全部节点，无测量数据也画点）
  - 对批次里每条有数据的链路 A-B，**双方各以自己为圆心**、A 到 B 的**球面物理距离**为半径画圆（同一链路两圆同半径）
  - 节点间用虚线连接，仅表示连接关系，不模拟真实路由
  - 圆周上标注 `A-B avg=xx.xms [avg-3σ ~ avg+3σ]`（3-sigma 区间）
- **颜色**：每条链路分配一种颜色，其圆、连线、标注同色，便于区分。
- **交互**：
  - 滚轮缩放、拖拽平移，另有「放大 / 缩小 / 重置」按钮
  - 鼠标悬停圆周或标注时：该圆加粗高亮，tooltip 显示链路名、avg、3σ
- **坐标来源**：优先节点配置的 `lat/lng`，未填时用内置 6 城坐标（北京/上海/深圳/杭州/成都/青岛）；都没有的节点会跳过并在日志提示。
- **依赖**：ECharts + 中国地图 geojson（`static/vendor/` 已本地化，离线可用）。

> 说明：中国地图为墨卡托投影，球面等距圆在投影后随纬度会有轻微变形，属投影固有现象（不是计算错误）。

---

## 七、数据文件与格式

### 服务器端（`/root/`）

| 路径 | 说明 |
|---|---|
| `/root/tcp_rtt.sh` | 测量脚本（由「生成并分发」写入） |
| `/usr/local/bin/tcp_rtt.sh` | 安装副本（可直接 `tcp_rtt` 调用） |
| `/root/tcp_echo.py` | TCP 回显服务端 |
| `/etc/systemd/system/tcp-echo.service` | 回显服务 systemd 单元 |
| `/root/rtt_results/` | 测量结果目录 |

### 每次测量的产物（`/root/rtt_results/`）

| 文件 | 内容 |
|---|---|
| `sync_<时间>_<hostname>.log` | 控制台输出（统计摘要 + ASCII 直方图） |
| `<节点>_<时间>.csv` | 统计摘要（src,dst,sent,recv,loss,min,avg,max,stddev,p50,p95） |
| `<节点>_<时间>_<目标>.raw.csv` | **原始 RTT 序列**（每行一个值，单位 ms） |

### 本地拉取位置

`<results_dir>/Meas_<测量时间>/`，包含上述日志、摘要 CSV、原始 raw CSV。

### 自动清理机制

本地与远端**规则一致**：保留最新 **500 个**，超过 **30 天**的删除。

- **本地**：程序启动时（含托盘「重启服务」）扫描 `results_dir` 下的 `Meas_*` 文件夹，按修改时间从新到旧保留最新 500 个、删除超 30 天的，删除数量写入 `logs/app.log`。
- **远端**：程序启动时（后台线程，节点不可达也不阻塞启动）以及每次「下发定时任务」时，在各节点对 `/root/rtt_results/*.csv` 执行：
  ```bash
  find /root/rtt_results -maxdepth 1 -name '*.csv' -mtime +30 -delete 2>/dev/null || true
  ls -1t /root/rtt_results/*.csv 2>/dev/null | tail -n +501 | xargs -r rm -f 2>/dev/null || true
  ```
  即同样保留最新 500 个、删除超 30 天的 CSV（日志 `sync_*.log` 不删）。
  - **安全锁**：末尾统一带 `2>/dev/null || true`。当云盘只读、权限不足等情况导致删除失败时，远端清理会彻底静默并返回成功，绝不会报错或打断主流程（下发任务、服务启动）。

> 阈值（500 / 30 天）写在 `core/tasks.py` 的 `clean_local_results` / `clean_remote_results` / `_remote_clean_cmd` 的默认参数中，需要时可调整。

### tcp_rtt 测量原理

1. 建立一条持久 TCP 连接
2. 循环 count 次：发 32 字节 payload → 收回显，用 `perf_counter_ns` 计算每轮 RTT
3. 排序后聚合 min/avg/max/stddev/p50/p95
4. 统计写入摘要 CSV，原始序列写入 raw CSV，控制台输出直方图

---

## 八、项目结构

```
rtt-manager/
├── main.py               # FastAPI 入口 + 所有 API 路由
├── tray.py               # 系统托盘常驻（后台运行、重启/退出）
├── start.bat             # 双击启动
├── config.json           # 业务配置
├── python_path.txt       # Python 路径
├── requirements.txt      # 依赖
├── README.md
├── core/
│   ├── ssh.py            # ssh.exe/scp.exe 封装
│   ├── tasks.py          # 连通/NTP/下发/清理/定时器列表/拉取/部署echo/认证
│   ├── wgconf.py         # WireGuard 配置生成（割集算法）与部署
│   └── tcp_rtt.py        # tcp_rtt.sh 自动生成与分发
├── static/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── vendor/           # cytoscape.min.js / echarts.min.js / china.json（离线可用）
├── conf_snapshot/        # 手工保存的某次服务器 conf 快照
└── logs/                 # 运行日志 + 管理员密码(.admin_pwd)
```

---

## 九、注意事项

- **代理**：Clash 等代理需把节点公网 IP 加直连白名单，否则 ssh/scp 断连。
- **CRLF**：远端命令统一走 `tr -d '\r' | bash -s`，上传脚本后 `sed -i 's/\r//g'`，避免回车符问题。
- **端口**：需能直连节点 22 端口；阿里云安全组放行 UDP 51820；WireGuard 虚拟网内 TCP 9000（tcp-echo）不受安全组限制。
- **多接口节点**：同一节点若有多块 WireGuard 网卡且同网段，务必依赖 conf 中的 `PostUp` 精确路由，否则会路由二义。
- **测量时间匹配**：日志名用下发时间，CSV 用实际执行时间；拉取时以日志内记录的真实 CSV 路径为准，避免秒级偏差漏拉。
- **tcp_rtt 更新**：拓扑变化后需重新「生成并分发 tcp_rtt.sh」，旧脚本不会自动更新。
- **数据可视化坐标**：新增节点若不在内置 6 城内，需在配置页填写 `lat`/`lng`，否则地图上会被跳过。
- **地图投影**：等时延圆按球面物理距离生成，在地图（墨卡托投影）上会随纬度轻微变形，属正常现象。
- **手改中文文件**：不要用 PowerShell 的 `Get-Content | Set-Content` 改 `static/` 下的中文文件（PS 5.1 会用 GBK 误读导致乱码），请用 UTF-8 无 BOM 编辑器。


---

## 十、打包为免安装绿色版

项目可打包成**免安装绿色版**：目标机器无需安装 Python 和任何依赖，解压即用。

### 打包

双击 uild.bat（自动创建独立构建环境并调用 PyInstaller）。

- 产物：dist\rtt-manager\ 整个文件夹
- 双击其中的 
tt-manager.exe 即后台运行（系统托盘）
- 体积约 45 MB

### 目标机器要求

- Windows 10/11
- **OpenSSH Client**（多数系统自带；如无，在「设置 → 应用 → 可选功能」中启用）
- 无需安装 Python / pip

### 首次运行

在 exe 所在目录自动生成 config.json（来自内置 config.default.json 模板）与 logs/。
首次启动会弹出设置向导（密钥目录 / 结果目录 / 管理员密码）。

### 说明

- uild.bat 会从打包机的 Python 安装目录自动定位 fi.dll、fi-8.dll、libcrypto-3-x64.dll、libssl-3-x64.dll 一并打包（这些是 _ctypes 与 _ssl 的依赖，缺失会导致启动失败）。
- 打包机需能创建 venv 并联网安装依赖（首次运行 uild.bat 时）。
- 迁移打包机时，把 python_path.txt 指向该机的 python.exe 即可。
