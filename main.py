"""rtt-manager 后端入口。

串行执行各任务（定时下发本身无需并行），返回 JSON 结果。
"""
import os
from fastapi import FastAPI, Body
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from core import tasks, wgconf, tcp_rtt, mesh
from core.paths import res_dir

BASE_DIR = res_dir()
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="蜘蛛网络控制台")


@app.on_event("startup")
def _startup_clean():
    """程序启动时清理旧结果：本地保留最新 500 个/30 天内；远端后台并行清理。"""
    try:
        cfg = tasks.load_config()
        removed = tasks.clean_local_results(cfg)
        if removed:
            import logging
            logging.getLogger("uvicorn.error").info(
                "本地结果清理：删除 %d 个旧文件夹", len(removed)
            )
    except Exception:
        pass

    # 远端清理放后台线程，避免节点不可达时拖慢服务启动
    try:
        import threading
        cfg = tasks.load_config()

        def _remote_clean():
            try:
                tasks.clean_remote_results(cfg)
            except Exception:
                pass

        threading.Thread(target=_remote_clean, daemon=True).start()
    except Exception:
        pass


class ScheduleBody(BaseModel):
    start_time: str = "15:30:00"
    count: int = 1000
    nodes: Optional[List[str]] = None


class FetchBody(BaseModel):
    time_str: str = "153000"
    nodes: Optional[List[str]] = None


class SelectedBody(BaseModel):
    nodes: Optional[List[str]] = None


class WgPathBody(BaseModel):
    path: List[str]
    nodes: Optional[List[dict]] = None
    edges: Optional[List[dict]] = None


class SetupBody(BaseModel):
    key_base: str
    results_dir: str
    password: str
    nodes: Optional[List[dict]] = None


class LoginBody(BaseModel):
    password: str


@app.get("/api/auth/status")
def auth_status():
    """返回首次启动状态 + 是否已设置密码。"""
    return {
        "first": tasks.is_first_start(),
        "has_password": tasks.get_password() is not None,
    }


@app.post("/api/auth/setup")
def auth_setup(body: SetupBody):
    """首次启动：写入密钥目录、结果目录、管理员密码，标记非首次。"""
    cfg = tasks.load_config()
    cfg["key_base"] = body.key_base
    cfg["results_dir"] = body.results_dir
    if body.nodes is not None:
        cfg["nodes"] = body.nodes
    tasks.save_config(cfg)
    tasks.set_password(body.password)
    tasks.mark_started()
    return {"ok": True}


@app.post("/api/auth/login")
def auth_login(body: LoginBody):
    pwd = tasks.get_password()
    if pwd is None:
        return {"ok": False, "error": "尚未设置密码"}
    if body.password == pwd:
        return {"ok": True}
    return {"ok": False, "error": "密码错误"}


@app.get("/api/config")
def get_config():
    return tasks.load_config()


@app.put("/api/config")
def put_config(cfg: dict = Body(...)):
    tasks.save_config(cfg)
    return {"ok": True}


@app.get("/api/nodes/test")
def api_test(nodes: Optional[str] = None):
    cfg = tasks.load_config()
    selected = nodes.split(",") if nodes else None
    return {"results": tasks.test_connectivity(cfg, selected)}


@app.get("/api/nodes/ntp")
def api_ntp(nodes: Optional[str] = None):
    cfg = tasks.load_config()
    selected = nodes.split(",") if nodes else None
    return {"results": tasks.test_ntp(cfg, selected)}


@app.post("/api/tasks/schedule")
def api_schedule(body: ScheduleBody):
    cfg = tasks.load_config()
    return {"results": tasks.schedule_task(cfg, body.start_time, body.count, body.nodes)}


@app.post("/api/tasks/clean")
def api_clean(body: SelectedBody = Body(default=None)):
    cfg = tasks.load_config()
    nodes = body.nodes if body else None
    return {"results": tasks.clean_timers(cfg, nodes)}


@app.get("/api/tasks/timers")
def api_timers(nodes: Optional[str] = None):
    cfg = tasks.load_config()
    selected = nodes.split(",") if nodes else None
    return {"results": tasks.list_timers(cfg, selected)}


@app.get("/api/results/stats")
def api_results_stats(nodes: Optional[str] = None):
    cfg = tasks.load_config()
    selected = nodes.split(",") if nodes else None
    local = tasks.results_stats(cfg)
    remote = tasks.remote_results_stats(cfg, selected)
    exceeds = local["exceeds"] or any(r.get("exceeds") for r in remote)
    return {"local": local, "remote": remote, "exceeds": exceeds}


@app.get("/api/results/batches")
def api_results_batches():
    cfg = tasks.load_config()
    return {"batches": tasks.list_batches(cfg)}


@app.get("/api/results/data")
def api_results_data(batch: str):
    cfg = tasks.load_config()
    return tasks.read_batch_data(cfg, batch)


@app.post("/api/results/clean")
def api_results_clean(body: SelectedBody = Body(default=None)):
    cfg = tasks.load_config()
    nodes = body.nodes if body else None
    local_removed = tasks.clean_local_results(cfg)
    remote = tasks.clean_remote_results(cfg, nodes)
    return {"local_removed": len(local_removed), "remote": remote}


@app.post("/api/tasks/deploy_echo")
def api_deploy(body: SelectedBody = Body(default=None)):
    cfg = tasks.load_config()
    nodes = body.nodes if body else None
    return {"results": tasks.deploy_echo(cfg, nodes)}


@app.post("/api/tasks/fetch_script")
def api_fetch_script(body: SelectedBody = Body(default=None)):
    cfg = tasks.load_config()
    nodes = body.nodes if body else None
    return {"results": tasks.fetch_script(cfg, nodes)}


@app.post("/api/tasks/fetch_results")
def api_fetch_results(body: FetchBody):
    cfg = tasks.load_config()
    return {"results": tasks.fetch_results(cfg, body.time_str, body.nodes)}


@app.post("/api/wg/preview")
def api_wg_preview(body: WgPathBody):
    cfg = tasks.load_config()
    if body.nodes is not None:
        cfg["nodes"] = body.nodes
    if body.edges is not None:
        cfg["edges"] = body.edges
    ok, err = wgconf.validate_path(cfg, body.path)
    if not ok:
        return {"ok": False, "error": err}
    confs = wgconf.build_path_conf(cfg, body.path)
    return {"ok": True, "path": body.path, "confs": confs,
            "forwarders": wgconf.forwarders(body.path)}


@app.post("/api/wg/deploy")
def api_wg_deploy(body: WgPathBody):
    cfg = tasks.load_config()
    if body.nodes is not None:
        cfg["nodes"] = body.nodes
    if body.edges is not None:
        cfg["edges"] = body.edges
    ok, err = wgconf.validate_path(cfg, body.path)
    if not ok:
        return {"ok": False, "error": err, "results": []}
    return wgconf.deploy_path(cfg, body.path)


class MeshBody(BaseModel):
    nodes: Optional[List[str]] = None


@app.post("/api/mesh/deploy")
def api_mesh_deploy(body: MeshBody = Body(default=None)):
    """全互联部署：选中节点两两点对点直连，并把 active_edges 置为完全图。"""
    cfg = tasks.load_config()
    selected = body.nodes if body else None
    return mesh.deploy_mesh(cfg, selected)


@app.get("/api/mesh/preview")
def api_mesh_preview():
    """预览全互联将生成的 conf（不部署）。"""
    cfg = tasks.load_config()
    confs = mesh.build_mesh_confs(cfg)
    edges = mesh.full_mesh_edges(cfg)
    return {"ok": True, "confs": confs, "edges": edges}


class TcpRttBody(BaseModel):
    nodes: Optional[List[dict]] = None
    edges: Optional[List[dict]] = None
    selected: Optional[List[str]] = None


@app.post("/api/tcp_rtt/generate")
def api_tcp_rtt_generate(body: TcpRttBody = Body(default=None)):
    cfg = tasks.load_config()
    if body and body.nodes is not None:
        cfg["nodes"] = body.nodes
    if body and body.edges is not None:
        cfg["edges"] = body.edges
    return {"ok": True, "script": tcp_rtt.build_script(cfg)}


@app.post("/api/tcp_rtt/deploy")
def api_tcp_rtt_deploy(body: TcpRttBody = Body(default=None)):
    cfg = tasks.load_config()
    selected = body.selected if body else None
    if body and body.nodes is not None:
        cfg["nodes"] = body.nodes
    if body and body.edges is not None:
        cfg["edges"] = body.edges
    results = tcp_rtt.deploy_script(cfg, selected)
    return {"ok": True, "results": results}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
