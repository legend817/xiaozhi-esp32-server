import ssl
import json
import time
import asyncio
import websockets

from config.logger import setup_logging
from typing import Optional, Tuple, List, TYPE_CHECKING
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.utils import lang_tag_filter
from core.providers.asr.dto.dto import InterfaceType
from core.utils.latency import LatencyTracker

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()


class ASRProvider(ASRProviderBase):
    """FunASR runtime 2-pass streaming provider.

    This provider keeps the stable `fun_server` provider untouched. It starts a
    WebSocket session when VAD first detects speech, forwards PCM frames as they
    arrive, and uses the `2pass-offline` final result to trigger the normal
    downstream chat flow.
    """

    def __init__(self, config: dict, delete_audio_file: bool):
        super().__init__()
        self.interface_type = InterfaceType.STREAM
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 10095)
        self.api_key = config.get("api_key", "none")
        self.is_ssl = str(config.get("is_ssl", True)).lower() in (
            "true",
            "1",
            "yes",
        )
        self.output_dir = config.get("output_dir")
        self.delete_audio_file = delete_audio_file
        self.uri = (
            f"wss://{self.host}:{self.port}"
            if self.is_ssl
            else f"ws://{self.host}:{self.port}"
        )
        self.ssl_context = ssl.SSLContext() if self.is_ssl else None
        if self.ssl_context:
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

        self.mode = config.get("mode", "2pass")
        self.chunk_size = config.get("chunk_size", [5, 10, 5])
        self.chunk_interval = int(config.get("chunk_interval", 10))
        self.itn = str(config.get("itn", False)).lower() in ("true", "1", "yes")
        self.recv_timeout = float(config.get("recv_timeout", 8))

        self.asr_ws = None
        self.forward_task = None
        self.is_processing = False
        self.server_ready = False
        self._is_stopping = False
        self.text = ""
        self.partial_text = ""
        self.session_id = None
        self.started_at = None

    async def open_audio_channels(self, conn: "ConnectionHandler"):
        await super().open_audio_channels(conn)

    async def receive_audio(self, conn: "ConnectionHandler", pcm_frame, audio_have_voice):
        if conn.client_voice_stop and self.asr_ws and not self._is_stopping:
            await self._send_stop_request(conn)
            return

        if conn.client_voice_stop:
            return

        await super().receive_audio(conn, pcm_frame, audio_have_voice)

        if audio_have_voice and self.asr_ws is None and not self.is_processing:
            try:
                await self._start_session(conn)
                await self._send_cached_audio(conn)
                return
            except Exception as e:
                logger.bind(tag=TAG).error(f"FunASR 2pass启动失败: {e}", exc_info=True)
                await self._cleanup(conn)
                return

        if conn.client_voice_stop and self.asr_ws and not self._is_stopping:
            await self._send_stop_request(conn)
            return

        if self.asr_ws and self.is_processing and not self._is_stopping:
            try:
                await self.asr_ws.send(pcm_frame)
            except Exception as e:
                logger.bind(tag=TAG).warning(f"FunASR 2pass发送音频失败: {e}")
                await self._cleanup(conn)
                return

    async def _start_session(self, conn: "ConnectionHandler"):
        self.is_processing = True
        self.server_ready = False
        self._is_stopping = False
        self.text = ""
        self.partial_text = ""
        self.session_id = conn.session_id or str(int(time.time() * 1000))
        self.started_at = LatencyTracker.now()

        auth_header = {"Authorization": "Bearer; {}".format(self.api_key)}
        self.asr_ws = await websockets.connect(
            self.uri,
            additional_headers=auth_header,
            subprotocols=["binary"],
            ping_interval=None,
            ssl=self.ssl_context,
        )
        config_message = {
            "mode": self.mode,
            "chunk_size": self.chunk_size,
            "chunk_interval": self.chunk_interval,
            "wav_name": self.session_id,
            "is_speaking": True,
            "itn": self.itn,
        }
        await self.asr_ws.send(json.dumps(config_message, ensure_ascii=False))
        self.server_ready = True
        logger.bind(tag=TAG).info(
            "LATENCY event=funasr_2pass_start trace={} uri={} mode={} chunk_size={} interval={}",
            getattr(conn, "vad_trace_id", None),
            self.uri,
            self.mode,
            self.chunk_size,
            self.chunk_interval,
        )
        self.forward_task = asyncio.create_task(self._forward_results(conn))

    async def _send_cached_audio(self, conn: "ConnectionHandler"):
        if not conn.asr_audio:
            return
        for cached_pcm in conn.asr_audio:
            if self.asr_ws and self.is_processing and not self._is_stopping:
                await self.asr_ws.send(cached_pcm)

    async def _send_stop_request(self, conn: "ConnectionHandler" = None):
        if not self.asr_ws or self._is_stopping:
            return
        self._is_stopping = True
        await self.asr_ws.send(json.dumps({"is_speaking": False}, ensure_ascii=False))
        logger.bind(tag=TAG).info(
            "LATENCY event=funasr_2pass_stop_sent trace={} final_wait_started=true vad_to_stop_sent_ms={}",
            getattr(conn, "vad_trace_id", None) if conn else None,
            int(time.time() * 1000 - conn.vad_voice_stop_time)
            if conn and getattr(conn, "vad_voice_stop_time", 0.0)
            else None,
        )

    async def _forward_results(self, conn: "ConnectionHandler"):
        try:
            while not conn.stop_event.is_set() and self.asr_ws:
                try:
                    response = await asyncio.wait_for(
                        self.asr_ws.recv(), timeout=self.recv_timeout
                    )
                    result = json.loads(response)
                    text = result.get("text", "") or ""
                    mode = result.get("mode", "")
                    elapsed_ms = (
                        LatencyTracker.ms_since(self.started_at)
                        if self.started_at
                        else None
                    )

                    if text and "online" in mode:
                        self.partial_text += text
                        logger.bind(tag=TAG).info(
                            "LATENCY event=funasr_2pass_partial trace={} ms={} text_len={} mode={}",
                            getattr(conn, "vad_trace_id", None),
                            elapsed_ms,
                            len(text),
                            mode,
                        )

                    if text and self._is_final_result(result):
                        self.text = text
                        final_after_vad_stop_ms = (
                            int(time.time() * 1000 - conn.vad_voice_stop_time)
                            if getattr(conn, "vad_voice_stop_time", 0.0)
                            else None
                        )
                        logger.bind(tag=TAG).info(
                            "LATENCY event=funasr_2pass_final trace={} ms={} final_after_vad_stop_ms={} text_len={} mode={}",
                            getattr(conn, "vad_trace_id", None),
                            elapsed_ms,
                            final_after_vad_stop_ms,
                            len(text),
                            mode,
                        )
                        await self.handle_voice_stop(conn, conn.asr_audio.copy())
                        break

                except asyncio.TimeoutError:
                    if self._is_stopping:
                        logger.bind(tag=TAG).warning("FunASR 2pass等待最终结果超时")
                        break
                    continue
                except websockets.ConnectionClosed:
                    logger.bind(tag=TAG).info("FunASR 2pass连接已关闭")
                    break
                except Exception as e:
                    logger.bind(tag=TAG).error(f"FunASR 2pass处理结果失败: {e}", exc_info=True)
                    break
        finally:
            await self._cleanup(conn)
            conn.reset_audio_states()

    def _is_final_result(self, result: dict) -> bool:
        if result.get("is_final") is True:
            return True
        mode = str(result.get("mode", ""))
        return "offline" in mode

    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str, artifacts=None
    ) -> Tuple[Optional[str], Optional[str]]:
        result = self.text
        self.text = ""
        return lang_tag_filter(result), None

    def stop_ws_connection(self):
        if self.asr_ws:
            asyncio.create_task(self.asr_ws.close())
            self.asr_ws = None
        self.is_processing = False
        self._is_stopping = False

    async def _cleanup(self, conn: "ConnectionHandler" = None):
        if self.forward_task and self.forward_task is not asyncio.current_task():
            self.forward_task.cancel()
            try:
                await self.forward_task
            except asyncio.CancelledError:
                pass
        self.forward_task = None
        if self.asr_ws:
            try:
                await self.asr_ws.close()
            except Exception:
                pass
        self.asr_ws = None
        self.is_processing = False
        self.server_ready = False
        self._is_stopping = False

    async def close(self):
        await self._cleanup()
