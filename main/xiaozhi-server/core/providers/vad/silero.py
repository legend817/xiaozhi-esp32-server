import time
import os
import uuid
import numpy as np
import onnxruntime
from config.logger import setup_logging
from core.providers.vad.base import VADProviderBase
from core.utils.vad_text import is_incomplete_asr_partial

TAG = __name__
logger = setup_logging()


class VADProvider(VADProviderBase):
    def __init__(self, config):
        logger.bind(tag=TAG).info("SileroVAD", config)

        model_path = os.path.join(
            config["model_dir"], "src", "silero_vad", "data", "silero_vad.onnx"
        )
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(
            model_path, providers=["CPUExecutionProvider"], sess_options=opts
        )

        threshold = config.get("threshold", "0.5")
        threshold_low = config.get("threshold_low", "0.2")
        min_silence_duration_ms = config.get("min_silence_duration_ms", "1000")
        incomplete_silence_duration_ms = config.get(
            "incomplete_silence_duration_ms", min_silence_duration_ms
        )

        self.vad_threshold = float(threshold) if threshold else 0.5
        self.vad_threshold_low = float(threshold_low) if threshold_low else 0.2

        self.silence_threshold_ms = (
            int(min_silence_duration_ms) if min_silence_duration_ms else 1000
        )
        self.incomplete_silence_threshold_ms = max(
            self.silence_threshold_ms,
            int(incomplete_silence_duration_ms)
            if incomplete_silence_duration_ms
            else self.silence_threshold_ms,
        )

        self.frame_window_threshold = 3

    def _init_connection_state(self, conn):
        """为连接初始化独立的 VAD 状态"""
        if not hasattr(conn, "_vad_state"):
            conn._vad_state = np.zeros((2, 1, 128), dtype=np.float32)
        if not hasattr(conn, "_vad_context"):
            conn._vad_context = np.zeros((1, 64), dtype=np.float32)

    def release_conn_resources(self, conn):
        """释放连接的 VAD 资源（连接关闭时调用）"""
        for attr in ("_vad_state", "_vad_context"):
            if hasattr(conn, attr):
                try:
                    delattr(conn, attr)
                except Exception:
                    pass

    def is_vad(self, conn, pcm_frame):
        # 手动模式：直接返回True，不进行实时VAD检测，所有音频都缓存
        if conn.client_listen_mode == "manual":
            return True

        try:
            self._init_connection_state(conn)

            # pcm_frame已经是处理后的PCM数据
            conn.client_audio_buffer.extend(pcm_frame)

            client_have_voice = False
            while len(conn.client_audio_buffer) >= 512 * 2:
                chunk = conn.client_audio_buffer[: 512 * 2]
                conn.client_audio_buffer = conn.client_audio_buffer[512 * 2 :]

                audio_int16 = np.frombuffer(chunk, dtype=np.int16)
                audio_float32 = audio_int16.astype(np.float32) / 32768.0
                audio_input = np.concatenate(
                    [conn._vad_context, audio_float32.reshape(1, -1)], axis=1
                ).astype(np.float32)

                ort_inputs = {
                    "input": audio_input,
                    "state": conn._vad_state,
                    "sr": np.array(16000, dtype=np.int64),
                }
                out, state = self.session.run(None, ort_inputs)

                conn._vad_state = state
                conn._vad_context = audio_input[:, -64:]
                speech_prob = out.item()

                # 双阈值判断
                if speech_prob >= self.vad_threshold:
                    is_voice = True
                elif speech_prob <= self.vad_threshold_low:
                    is_voice = False
                else:
                    is_voice = conn.last_is_voice

                # 声音没低于最低值则延续前一个状态，判断为有声音
                conn.last_is_voice = is_voice

                # 更新滑动窗口
                conn.client_voice_window.append(is_voice)
                client_have_voice = (
                    conn.client_voice_window.count(True) >= self.frame_window_threshold
                )

                # 如果之前有声音，但本次没有声音，且与上次有声音的时间差已经超过了静默阈值，则认为已经说完一句话
                if (
                    conn.client_have_voice
                    and not client_have_voice
                    and not conn.client_voice_stop
                ):
                    now_ms = time.time() * 1000
                    stop_duration = now_ms - conn.vad_last_voice_time
                    partial_text = str(
                        getattr(getattr(conn, "asr", None), "partial_text", "") or ""
                    )
                    partial_guard = is_incomplete_asr_partial(partial_text)
                    target_silence_ms = (
                        self.incomplete_silence_threshold_ms
                        if partial_guard
                        else self.silence_threshold_ms
                    )
                    if (
                        partial_guard
                        and stop_duration >= self.silence_threshold_ms
                        and not getattr(conn, "vad_partial_guard_active", False)
                    ):
                        conn.vad_partial_guard_active = True
                        logger.bind(tag=TAG).info(
                            "LATENCY event=vad_partial_guard trace={} active=true partial_len={} base_ms={} extended_ms={}",
                            getattr(conn, "vad_trace_id", None),
                            len(partial_text),
                            self.silence_threshold_ms,
                            self.incomplete_silence_threshold_ms,
                        )
                    if stop_duration >= target_silence_ms:
                        conn.client_voice_stop = True
                        conn.vad_voice_stop_time = now_ms
                        logger.bind(tag=TAG).info(
                            "LATENCY event=vad_voice_stop trace={} silence_ms={} target_ms={} partial_guard={} speech_ms={} buffered_frames={} buffered_bytes={}",
                            getattr(conn, "vad_trace_id", None),
                            int(stop_duration),
                            target_silence_ms,
                            partial_guard,
                            int(now_ms - conn.vad_first_voice_time) if conn.vad_first_voice_time else None,
                            len(getattr(conn, "asr_audio", []) or []),
                            sum(len(frame) for frame in (getattr(conn, "asr_audio", []) or [])),
                        )
                if client_have_voice:
                    now_ms = time.time() * 1000
                    conn.vad_partial_guard_active = False
                    if not conn.client_have_voice:
                        conn.vad_trace_id = uuid.uuid4().hex[:12]
                        conn.vad_first_voice_time = now_ms
                        logger.bind(tag=TAG).info(
                            "LATENCY event=vad_first_voice trace={} threshold={} threshold_low={}",
                            conn.vad_trace_id,
                            self.vad_threshold,
                            self.vad_threshold_low,
                        )
                    conn.client_have_voice = True
                    conn.vad_last_voice_time = now_ms

            return client_have_voice
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error processing audio packet: {e}")
