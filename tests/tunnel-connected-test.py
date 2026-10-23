"""验证 gui.tunnel_connected()：隧道进程活着 ≠ 真的连着。

背景：cloudflared 与 Cloudflare 边缘断开后会一直重试，但**地址仍留在日志里**，
于是界面显示"隧道已运行"、点「只启动隧道」也直接返回 already running，
卡死的隧道再也救不回来（真机：dial tcp <边缘>:7844 i/o timeout 之后手机端 530）。

判定必须看日志**末尾最后一次连接状态**。本脚本直接从 gui.pyw 抽源码原文执行
（不会启动 Tk 界面）。

用法：
    python tests/tunnel-connected-test.py
"""
import ast
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "gui.pyw"
src = SRC.read_text(encoding="utf-8")
tree = ast.parse(src)

WANTED = {"_TUNNEL_OK_RE", "_TUNNEL_BAD_RE", "tunnel_connected"}
ns = {"re": re}
for node in tree.body:
    name = None
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        name = node.targets[0].id
    elif isinstance(node, ast.FunctionDef):
        name = node.name
    if name in WANTED:
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<gui>", "exec"), ns)

missing = WANTED - set(ns)
if missing:
    print("抽取失败，gui.pyw 里找不到:", sorted(missing))
    sys.exit(2)

fails = 0


def case(label, logtext, expect):
    global fails
    tmp = Path(tempfile.mkdtemp())
    if logtext is not None:
        (tmp / "tunnel.log").write_text(logtext, encoding="utf-8")
    ns["data_dir"] = lambda: tmp
    got = ns["tunnel_connected"]()
    ok = got == expect
    if not ok:
        fails += 1
    print(("PASS  " if ok else "FAIL  ") + label + f"  -> {got}  (want {expect})")
    shutil.rmtree(tmp, ignore_errors=True)


case("空日志（刚启动）", "", False)
case("只有成功", "INF Registered tunnel connection connIndex=0 protocol=http2\n", True)
case("成功后又掉线（本次真机故障）",
     "INF Registered tunnel connection connIndex=0\n"
     "ERR Connection terminated error=\"i/o timeout\"\n"
     "INF Retrying connection in up to 4s\n", False)
case("掉线后重连成功",
     "ERR Connection terminated\nINF Retrying connection in up to 4s\n"
     "INF Registered tunnel connection connIndex=0\n", True)
case("地址留在日志里但最后是错误",
     "INF https://cord-jackets-talked-ivory.trycloudflare.com\n"
     "INF Registered tunnel connection connIndex=0\n"
     "ERR Unable to establish connection with Cloudflare edge\n"
     "ERR Serve tunnel error\n", False)

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
