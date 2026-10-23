"""验证 GUI._access_url() 的优先级：公网隧道 > Tailscale 固定地址 > 局域网。

为什么是"隧道优先"：手机端要求**不装 App、不开 VPN**，浏览器和壳 APK 都要能直接用，
所以二维码/手机地址要指向公网隧道；只有当隧道没起时才退到 Tailscale（需手机装 Tailscale）。

用法：
    python tests/access-url-test.py
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tree = ast.parse((ROOT / "gui.pyw").read_text(encoding="utf-8"))

ns = {"re": re, "PORT": 8787}
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "_access_url":
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<gui>", "exec"), ns)
        break
if "_access_url" not in ns:
    print("抽取失败：gui.pyw 里找不到 _access_url")
    sys.exit(2)

fails = 0


class Fake:
    def __init__(self, tunnel=None):
        self.pin = "00000000"
        self.tunnel_url = tunnel


def case(label, lan, ts, tunnel, want):
    global fails
    ns["lan_ips"] = lambda: list(lan)
    ns["session_tailscale_ips"] = lambda: list(ts)
    got = ns["_access_url"](Fake(tunnel))
    ok = got == want
    if not ok:
        fails += 1
    print(("PASS  " if ok else "FAIL  ") + label + f"  -> {got}  (want {want})")


case("有隧道就优先用隧道（手机零安装，即使 Tailscale 也在）",
     ["100.90.36.34", "100.78.170.60"], ["100.90.36.34"],
     "https://aaa.trycloudflare.com",
     "https://aaa.trycloudflare.com?pin=00000000")
case("没隧道但有 Tailscale -> 用 Tailscale 固定地址",
     ["100.90.36.34", "100.78.170.60"], ["100.90.36.34"],
     None,
     "http://100.90.36.34:8787?pin=00000000")
case("都没有 -> 用局域网",
     ["192.168.0.67"], [], None,
     "http://192.168.0.67:8787?pin=00000000")
case("Tailscale 网卡在但地址不在 lan_ips 里 -> 不该用它",
     ["192.168.0.67"], ["100.90.36.34"], None,
     "http://192.168.0.67:8787?pin=00000000")
case("什么都没有 -> None", [], [], None, None)

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
