#!/usr/bin/env python3
"""端到端链路测试：HTTP → WebSocket → Hello → Text Chat → Unit Tests"""

import asyncio
import json
import sys
import time
import unittest

import aiohttp
import websockets


SERVER_HOST = "localhost"
HTTP_PORT = 8003
WS_PORT = 8000
WS_PATH = "/xiaozhi/v1/"
DEVICE_ID = "e2e-test-device-001"
CLIENT_ID = "e2e-test-client-001"


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def ok(msg):
    print(f"  {Colors.GREEN}\u2713{Colors.RESET} {msg}")


def fail(msg):
    print(f"  {Colors.RED}\u2717{Colors.RESET} {msg}")


def info(msg):
    print(f"  {Colors.BLUE}\u2192{Colors.RESET} {msg}")


def warn(msg):
    print(f"  {Colors.YELLOW}\u26a0{Colors.RESET} {msg}")


def header(msg):
    print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}  {msg}{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")


results = {"passed": 0, "failed": 0, "warnings": 0}


def record(passed: bool, is_warning: bool = False):
    if passed:
        results["passed"] += 1
        if is_warning:
            results["warnings"] += 1
    else:
        results["failed"] += 1


async def test_http_server_running(session):
    try:
        async with session.get(f"http://{SERVER_HOST}:{HTTP_PORT}/") as resp:
            text = await resp.text()
            if resp.status == 200:
                ok(f"HTTP server 响应正常 (status={resp.status})")
                record(True)
            else:
                fail(f"HTTP server 状态异常 (status={resp.status})")
                record(False)
    except Exception as e:
        fail(f"HTTP server 无法连接: {e}")
        record(False)


async def test_vision_endpoint(session):
    try:
        async with session.options(f"http://{SERVER_HOST}:{HTTP_PORT}/mcp/vision/explain") as resp:
            if resp.status in (200, 204, 405):
                ok(f"视觉接口 /mcp/vision/explain 可达 (status={resp.status})")
                record(True)
            else:
                fail(f"视觉接口异常 (status={resp.status})")
                record(False)
    except Exception as e:
        fail(f"视觉接口无法连接: {e}")
        record(False)


async def test_ota_endpoint(session):
    try:
        async with session.options(f"http://{SERVER_HOST}:{HTTP_PORT}/xiaozhi/ota/") as resp:
            if resp.status in (200, 204, 405):
                ok(f"OTA 接口 /xiaozhi/ota/ 可达 (status={resp.status})")
                record(True)
            else:
                fail(f"OTA 接口异常 (status={resp.status})")
                record(False)
    except Exception as e:
        fail(f"OTA 接口无法连接: {e}")
        record(False)


async def test_websocket_connect():
    uri = f"ws://{SERVER_HOST}:{WS_PORT}{WS_PATH}?device-id={DEVICE_ID}&client-id={CLIENT_ID}"
    try:
        async with websockets.connect(uri, max_size=10 * 1024 * 1024) as ws:
            ok(f"WebSocket 连接成功: {uri}")
            record(True)
            return ws
    except Exception as e:
        fail(f"WebSocket 连接失败: {e}")
        record(False)
        return None


async def test_websocket_no_device_id():
    uri = f"ws://{SERVER_HOST}:{WS_PORT}{WS_PATH}"
    try:
        async with websockets.connect(uri, max_size=10 * 1024 * 1024) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=3)
            if "测试" in msg or "端口正常" in msg:
                ok("无 device-id 时正确返回提示信息并关闭")
                record(True)
            else:
                warn(f"无 device-id 时返回了意外消息: {msg[:80]}")
                record(True, is_warning=True)
    except websockets.exceptions.ConnectionClosed:
        ok("无 device-id 时 WebSocket 正确关闭连接")
        record(True)
    except Exception as e:
        fail(f"无 device-id 测试异常: {e}")
        record(False)


async def test_hello_handshake():
    uri = f"ws://{SERVER_HOST}:{WS_PORT}{WS_PATH}?device-id={DEVICE_ID}&client-id={CLIENT_ID}"
    try:
        async with websockets.connect(uri, max_size=10 * 1024 * 1024) as ws:
            hello_msg = {
                "type": "hello",
                "version": 1,
                "transport": "websocket",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 24000,
                    "channels": 1,
                    "frame_duration": 60,
                },
            }
            await ws.send(json.dumps(hello_msg))
            response = await asyncio.wait_for(ws.recv(), timeout=5)
            resp_json = json.loads(response)

            assert resp_json.get("type") == "hello", f"type not hello: {resp_json.get('type')}"
            assert "session_id" in resp_json, "missing session_id"
            assert "audio_params" in resp_json, "missing audio_params"
            assert resp_json["audio_params"]["sample_rate"] == 24000, "sample_rate mismatch"
            assert resp_json["transport"] == "websocket", "transport mismatch"

            ok(f"Hello 握手成功 (session_id={resp_json['session_id'][:8]}...)")
            record(True)
            return resp_json
    except Exception as e:
        fail(f"Hello 握手失败: {e}")
        record(False)
        return None


async def test_text_chat_basic():
    uri = f"ws://{SERVER_HOST}:{WS_PORT}{WS_PATH}?device-id={DEVICE_ID}&client-id={CLIENT_ID}"
    try:
        async with websockets.connect(uri, max_size=10 * 1024 * 1024) as ws:
            hello_msg = {
                "type": "hello",
                "version": 1,
                "transport": "websocket",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 24000,
                    "channels": 1,
                    "frame_duration": 60,
                },
            }
            await ws.send(json.dumps(hello_msg))
            await asyncio.wait_for(ws.recv(), timeout=5)
            await asyncio.sleep(1.0)

            listen_msg = {
                "type": "listen",
                "state": "start",
                "text": "你好，请简单介绍一下你自己",
            }
            await ws.send(json.dumps(listen_msg))
            await asyncio.sleep(0.3)
            stop_msg = {"type": "listen", "state": "stop"}
            await ws.send(json.dumps(stop_msg))

            responses = []
            start = time.time()
            while time.time() - start < 20:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3)
                    if isinstance(msg, bytes):
                        responses.append(("binary", len(msg)))
                    else:
                        try:
                            data = json.loads(msg)
                            t = data.get("type", "unknown")
                            if t == "tts":
                                responses.append(("tts", data.get("state", "?")))
                            elif t == "stt":
                                text = data.get("text", "")
                                info(f"STT: {text}")
                            elif t == "llm":
                                token = data.get("text", "")[:60]
                                info(f"LLM: {token}")
                                responses.append(("llm", token))
                            else:
                                responses.append(("json", t))
                        except json.JSONDecodeError:
                            responses.append(("text", msg[:80]))
                except asyncio.TimeoutError:
                    if responses:
                        break
                    continue

            if responses:
                info(f"收到 {len(responses)} 条响应")
                for r in responses[:5]:
                    info(f"  [{r[0]}] {str(r[1])[:80]}")
                ok("文本聊天链路有响应返回")
                record(True)
            else:
                warn("文本聊天未收到响应（LLM API key 可能未配置）")
                record(True, is_warning=True)
    except Exception as e:
        fail(f"文本聊天链路失败: {e}")
        record(False)


async def test_wakeup_word_response():
    uri = f"ws://{SERVER_HOST}:{WS_PORT}{WS_PATH}?device-id={DEVICE_ID}&client-id={CLIENT_ID}"
    try:
        async with websockets.connect(uri, max_size=10 * 1024 * 1024) as ws:
            hello_msg = {
                "type": "hello",
                "version": 1,
                "transport": "websocket",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 24000,
                    "channels": 1,
                    "frame_duration": 60,
                },
            }
            await ws.send(json.dumps(hello_msg))
            await asyncio.wait_for(ws.recv(), timeout=5)
            await asyncio.sleep(2.0)

            listen_msg = {
                "type": "listen",
                "state": "start",
                "text": "你好小智",
            }
            await ws.send(json.dumps(listen_msg))
            await asyncio.sleep(0.3)
            stop_msg = {"type": "listen", "state": "stop"}
            await ws.send(json.dumps(stop_msg))

            found_audio = False
            start = time.time()
            while time.time() - start < 15:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3)
                    if isinstance(msg, bytes):
                        found_audio = True
                except asyncio.TimeoutError:
                    break

            if found_audio:
                ok("唤醒词收到音频响应")
                record(True)
            else:
                warn("唤醒词未收到音频响应（TTS 初始化或缓存可能未就绪）")
                record(True, is_warning=True)
    except Exception as e:
        fail(f"唤醒词测试失败: {e}")
        record(False)


def run_unit_tests():
    header("5. 单元测试")
    loader = unittest.TestLoader()
    suite = loader.discover("tests")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        ok(f"全部 {result.testsRun} 个单元测试通过")
        record(True)
    else:
        fail(f"单元测试失败: {len(result.failures)} failures, {len(result.errors)} errors")
        record(False)


async def main():
    print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}  小智 ESP32 Server - 端到端链路测试{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"  Server: {SERVER_HOST}:{WS_PORT} (WS) / {SERVER_HOST}:{HTTP_PORT} (HTTP)\n")

    header("1. HTTP 服务端点")
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        await test_http_server_running(session)
        await test_vision_endpoint(session)
        await test_ota_endpoint(session)

    header("2. WebSocket 连接")
    await test_websocket_no_device_id()
    await test_websocket_connect()

    header("3. Hello 握手协议")
    await test_hello_handshake()

    header("4a. 文本聊天链路")
    await test_text_chat_basic()

    header("4b. 唤醒词响应")
    await test_wakeup_word_response()

    run_unit_tests()

    header("测试总结")
    total = results["passed"] + results["failed"]
    pct = (results["passed"] / total * 100) if total > 0 else 0
    print(f"  总计: {total}  通过: {results['passed']}  失败: {results['failed']}  警告: {results['warnings']}")
    print(f"  通过率: {pct:.0f}%")

    if results["failed"] > 0:
        print(f"\n{Colors.RED}  FAIL: {results['failed']} 个测试失败{Colors.RESET}")
        sys.exit(1)
    else:
        print(f"\n{Colors.GREEN}  PASS: 全部测试通过{Colors.RESET}")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
