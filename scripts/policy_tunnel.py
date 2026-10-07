# -*- coding: utf-8 -*-
"""决策模型端口转发：让队友用上你的模型，同时不违反「必须本机回环」的限制。

为什么需要它
------------
`backend/policy/client.py` 强制要求模型地址是本机回环：

    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("POLICY_API_BASE_URL must be a local loopback HTTP endpoint")

所以队友**不能**直接把 `.env` 写成 `http://<你的IP>:11434`——会被直接拒绝。
`.env.example` 里也写明了正确做法：「可通过本机端口转发接入模型服务」。

本脚本实现这条路的**两端**，只用标准库，不需要管理员权限：

  队长机器（把本机 Ollama 分享出去，建议只在局域网内）:
      python scripts/policy_tunnel.py host --port 11435 --allow-lan
      python scripts/policy_tunnel.py host --port 11435 --allow 10.254.253.100 10.254.253.101

  队友机器（把本地 8001 接到队长的模型上，从而满足回环要求）:
      python scripts/policy_tunnel.py borrow --remote 10.254.253.222:11435
      python scripts/policy_tunnel.py borrow --remote [2409:890f:4e08:38c1::1]:11435

  队友随后**不用改 `.env`**，保持 `.env.example` 的默认值
  （POLICY_API_BASE_URL=http://127.0.0.1:8001）照常启动后端即可。

局域网 / 跨网段
---------------
`host` 默认**双栈监听**：同一个端口既收局域网的 IPv4，也收走 IPv6 的跨网段连接。
所以队友不在同一个网段时，只要两边都有 IPv6，直接把上面横幅里那条 IPv6 命令发给他即可，
不需要端口映射、也不需要装组网工具（IPv6 一般不做 NAT，地址本身就是可达的）。

IPv6 地址必须写成 `[地址]:端口`——地址内部的冒号会和端口分隔符冲突。

前提
----
- 队长的机器必须**保持开机**、本脚本保持运行；
- 两台机器网络可达（同一局域网，或两边都有 IPv6，或有公网隧道）；
- 跨网段走 IPv6 时，队长机器的防火墙要放行该端口的入站；
- 这不是"把模型下载下来了"，而是**借用**：断线即失效。

安全提示
--------
Ollama 本身没有鉴权，默认放开意味着同网段谁都能用你的模型。
如果环境嘈杂，加 `--allow <队友IP...>` 限定来源。
"""

import argparse
import json
import socket
import socketserver
import sys
import threading

BUFFER = 65536
DISCOVER_PORT = 11436
DISCOVER_PROBE = b"MMA-POLICY-DISCOVER/1"
DISCOVER_REPLY = b"MMA-POLICY-HERE/1 "


def split_host_port(spec: str) -> tuple[str, int]:
    """拆开 HOST:PORT，兼容 IPv6 的 ``[2409:...]:11435`` 写法。

    直接用 ``rpartition(":")`` 会被 IPv6 地址内部的冒号截断（拿到的"端口"其实是
    地址的最后一段），所以带方括号的形式必须单独处理。
    """
    text = spec.strip()
    if text.startswith("["):
        host, sep, rest = text[1:].partition("]")
        port_text = rest.lstrip(":")
        if not sep or not port_text:
            raise ValueError(f"IPv6 需要写成 [地址]:端口：{spec}")
        return host, int(port_text)
    host, _, port_text = text.rpartition(":")
    if not host or not port_text:
        raise ValueError(f"需要写成 HOST:PORT：{spec}")
    return host, int(port_text)


def format_host_port(host: str, port: int) -> str:
    """IPv6 补上方括号，好直接传给 --team / --remote。"""
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def peer_ip(client_address) -> str:  # noqa: ANN001
    """双栈监听下 IPv4 客户端会被看成 ``::ffff:1.2.3.4``，这里还原成 IPv4。"""
    ip = client_address[0] if client_address else ""
    return ip[7:] if ip.startswith("::ffff:") else ip


def start_discovery(port: int, relay_port: int) -> socket.socket | None:
    """UDP 应答器：队友的 start_dev.py 广播探测时，把转发端口告诉他。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as exc:
        print(f"[tunnel] 发现服务未能启动（{exc}），队友需手动传 --team", flush=True)
        return None

    def loop() -> None:
        while True:
            try:
                data, addr = sock.recvfrom(1024)
            except OSError:
                return
            if data.startswith(DISCOVER_PROBE):
                payload = json.dumps({
                    "port": relay_port,
                    "host": socket.gethostname(),
                    "addresses": lan_addresses(),
                }).encode()
                try:
                    sock.sendto(DISCOVER_REPLY + payload, addr)
                    print(f"[tunnel] 已回应自动发现：{addr[0]}", flush=True)
                except OSError:
                    pass

    threading.Thread(target=loop, daemon=True).start()
    return sock


def discover(timeout: float = 1.5, port: int = DISCOVER_PORT) -> str | None:
    """在局域网里广播，找有没有人在分享模型。返回能连通的 HOST:PORT。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    candidates: list[str] = []
    try:
        sock.sendto(DISCOVER_PROBE, ("255.255.255.255", port))
        while True:
            try:
                data, addr = sock.recvfrom(2048)
            except (socket.timeout, OSError):
                break
            if not data.startswith(DISCOVER_REPLY):
                continue
            try:
                info = json.loads(data[len(DISCOVER_REPLY):].decode("utf-8"))
            except ValueError:
                continue
            relay_port = info.get("port")
            if not relay_port:
                continue
            # 多网卡机器（比如还装了 WSL/VMware）可能报错地址，所以逐个试
            for ip in info.get("addresses") or []:
                candidates.append(format_host_port(str(ip), int(relay_port)))
            candidates.append(format_host_port(peer_ip(addr), int(relay_port)))
    finally:
        sock.close()

    for spec in candidates:
        try:
            host, port_number = split_host_port(spec)
        except ValueError:
            continue
        try:
            with socket.create_connection((host, port_number), timeout=1.5):
                return spec
        except (OSError, ValueError):
            continue
    return None


def pipe(src: socket.socket, dst: socket.socket) -> None:
    """单向搬运，直到任一端关闭。"""
    try:
        while True:
            chunk = src.recv(BUFFER)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class Relay(socketserver.BaseRequestHandler):
    target: tuple[str, int] = ("127.0.0.1", 11434)

    def handle(self) -> None:
        try:
            upstream = socket.create_connection(self.target, timeout=15)
        except OSError as exc:
            print(f"[tunnel] 连不上目标 {self.target[0]}:{self.target[1]} — {exc}", flush=True)
            return
        print(f"[tunnel] {peer_ip(self.client_address)} → {self.target[0]}:{self.target[1]}", flush=True)
        with upstream:
            worker = threading.Thread(target=pipe, args=(self.request, upstream), daemon=True)
            worker.start()
            pipe(upstream, self.request)
            worker.join(timeout=5)


class RelayServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def verify_request(self, request, client_address):  # noqa: ANN001
        allowed = getattr(self, "allowed", None)
        if allowed is not None and peer_ip(client_address) not in allowed:
            print(f"[tunnel] 拒绝未授权来源 {peer_ip(client_address)}", flush=True)
            return False
        return True


class DualStackRelayServer(RelayServer):
    """同时监听 IPv4 和 IPv6。

    Windows 上 ``IPV6_V6ONLY`` 默认是 1，只绑 ``::`` 会收不到 IPv4 连接，
    必须显式关掉；这样同一个端口既能接局域网的 IPv4 队友，也能接跨网段走
    IPv6 直连的队友。
    """

    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except OSError:
            pass
        super().server_bind()


def lan_addresses() -> list[str]:
    """本机可以提供给队友的地址：局域网 IPv4 在前，全局 IPv6 在后。

    带上 IPv6 是为了跨网段的队友——他的机器如果也有 IPv6，就能直接连过来，
    不必依赖同一局域网或第三方组网工具。
    """
    v4: list[str] = []
    v6: list[str] = []
    for family, bucket in ((socket.AF_INET, v4), (socket.AF_INET6, v6)):
        try:
            infos = socket.getaddrinfo(socket.gethostname(), None, family)
        except OSError:
            continue
        for info in infos:
            ip = info[4][0]
            if family == socket.AF_INET6:
                ip = ip.split("%", 1)[0]  # 去掉 fe80::1%12 这种 zone id
                if ip.startswith(("fe80", "::1")):
                    continue
            elif ip.startswith("127."):
                continue
            if ip not in bucket:
                bucket.append(ip)
    return v4 + v6


def run_host(args: argparse.Namespace) -> None:
    handler = type("HostHandler", (Relay,), {"target": ("127.0.0.1", args.to_port)})
    bind_note = "IPv4 / IPv6 双栈"
    try:
        server = DualStackRelayServer(("::", args.port), handler)
    except OSError as exc:
        # 机器禁用了 IPv6 时退回纯 IPv4，局域网共享照旧可用。
        print(f"[tunnel] IPv6 监听不可用（{exc}），退回 IPv4", flush=True)
        server = RelayServer(("0.0.0.0", args.port), handler)
        bind_note = "仅 IPv4"
    # 默认放开（不限制来源）；给了 --allow 就只允许这些 IP。
    server.allowed = set(args.allow) if args.allow else None

    scope = "、".join(args.allow) if args.allow else "不限制来源"
    print("\n" + "=" * 68)
    print("  决策模型已共享（队长端）")
    print(f"  本机模型   127.0.0.1:{args.to_port}  →  对外监听 :{args.port}（{bind_note}）")
    print(f"  允许来源   {scope}")
    if not args.no_discovery:
        print("  同一局域网：队友**什么都不用填**，直接运行：")
        print("      python scripts/start_dev.py")
        print("  （会自动在局域网里找到你；跨网段时用下面的地址：）")
    for ip in lan_addresses():
        tag = "IPv6（跨网段可用）" if ":" in ip else "局域网 IPv4"
        print(f"      python scripts/start_dev.py --team {format_host_port(ip, args.port)}   # {tag}")
    print("  ⚠️  你的机器要保持开机，本窗口不能关；关闭即断开。")
    print("=" * 68 + "\n", flush=True)

    if not args.no_discovery:
        start_discovery(args.discover_port, args.port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[tunnel] 已停止", flush=True)
    finally:
        server.server_close()


def run_borrow(args: argparse.Namespace) -> None:
    try:
        host, port = split_host_port(args.remote)
    except ValueError:
        sys.exit("--remote 需要写成 HOST:PORT；IPv6 要加方括号，"
                 "例如 10.254.253.222:11435 或 [2409:890f:4e08:38c1::1]:11435")

    try:
        probe = socket.create_connection((host, port), timeout=8)
        probe.close()
        reachable = "可达"
    except OSError as exc:
        reachable = f"当前不可达（{exc}）—— 仍会启动，等队长那边起来后自动可用"

    handler = type("BorrowHandler", (Relay,), {"target": (host, port)})
    server = RelayServer(("127.0.0.1", args.local), handler)

    if not args.quiet:
        print("\n" + "=" * 68)
        print("  决策模型转发已启动（borrow）")
        print(f"  本地 127.0.0.1:{args.local}  →  目标 {format_host_port(host, port)}   [{reachable}]")
        print(f"  .env 保持默认即可：POLICY_API_BASE_URL=http://127.0.0.1:{args.local}")
        print("  然后照常启动后端：uvicorn backend.main:app --reload")
        print("  ⚠️  目标服务不可用（或队长关机）时，请求会失败。")
        print("=" * 68 + "\n", flush=True)
    elif reachable != "可达":
        print(f"[tunnel] 目标 {format_host_port(host, port)} {reachable}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[tunnel] 已停止", flush=True)
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="决策模型端口转发（host / borrow）")
    sub = parser.add_subparsers(dest="role", required=True)

    host = sub.add_parser("host", help="队长端：把本机模型分享给队友")
    host.add_argument("--port", type=int, default=11435, help="对外监听端口，默认 11435")
    host.add_argument("--to-port", type=int, default=11434, help="本机模型端口，默认 11434（Ollama）")
    host.add_argument("--allow", nargs="+", default=[], metavar="IP",
                      help="可选：只允许这些队友 IP（默认不限制）")
    host.add_argument("--discover-port", type=int, default=DISCOVER_PORT,
                      help=f"自动发现的 UDP 端口，默认 {DISCOVER_PORT}")
    host.add_argument("--no-discovery", action="store_true",
                      help="关闭局域网自动发现，让队友手动传 --team")
    host.set_defaults(func=run_host)

    borrow = sub.add_parser("borrow", help="队友端：把本地回环接到队长的模型")
    borrow.add_argument("--remote", required=True, metavar="HOST:PORT", help="队长的地址")
    borrow.add_argument("--local", type=int, default=8001,
                        help="本地监听端口，默认 8001（与 .env.example 一致）")
    borrow.add_argument("--quiet", action="store_true", help="不打印横幅（供脚本调用）")
    borrow.set_defaults(func=run_borrow)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
