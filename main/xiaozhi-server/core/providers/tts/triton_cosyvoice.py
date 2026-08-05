import asyncio
import audioop
import os
import queue
import threading
import time
import traceback
import uuid
import wave

import numpy as np

from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import ContentType, InterfaceType, SentenceType
from core.utils import opus_encoder_utils, textUtils
from core.utils.tts import MarkdownCleaner

try:
    import tritonclient.grpc as grpcclient
except ImportError:  # 由 __init__ 给出可操作的错误信息，便于现有 EdgeTTS 降级生效
    grpcclient = None


TAG = __name__
logger = setup_logging()


class _RequestState:
    def __init__(self, sentence_id, display_text):
        self.sentence_id = sentence_id
        self.display_text = display_text
        self.done = threading.Event()
        self.error = None
        self.first_audio_received = False
        self.started_at = time.monotonic()
        self.resample_state = None


class TTSProvider(TTSProviderBase):
    """CosyVoice2 Triton decoupled gRPC 流式 TTS Provider。"""

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        if grpcclient is None:
            raise RuntimeError(
                "缺少 Triton gRPC 客户端，请安装 tritonclient[grpc]"
            )

        self.interface_type = InterfaceType.SINGLE_STREAM
        self.server = config.get("server", "localhost:8001")
        self.model_name = config.get("model_name", "cosyvoice2")
        self.model_version = str(config.get("model_version", ""))
        self.output_name = config.get("output_name", "waveform")
        self.reference_audio = config.get("ref_audio") or config.get(
            "reference_audio", ""
        )
        self.reference_text = config.get("ref_text") or config.get(
            "reference_text", ""
        )
        self.voice = config.get("private_voice") or config.get(
            "voice", os.path.basename(self.reference_audio) or "triton_cosyvoice"
        )
        self.output_sample_rate = int(config.get("sample_rate", 24000))
        self.request_timeout = float(config.get("request_timeout", self.tts_timeout))
        self.ssl = str(config.get("ssl", False)).lower() in ("true", "1", "yes")

        self._reference_waveform = None
        self._reference_waveform_len = None
        if self.reference_audio:
            (
                self._reference_waveform,
                self._reference_waveform_len,
            ) = self._load_reference_wav(self.reference_audio)

        self._client = None
        self._client_owner_thread = None
        self._active_request = None
        self._request_lock = threading.Lock()

    @staticmethod
    def _load_reference_wav(audio_path):
        path = os.path.abspath(os.path.expanduser(audio_path))
        if not os.path.isfile(path):
            raise ValueError(f"Triton CosyVoice2 参考音频不存在: {path}")

        with wave.open(path, "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            raw = wav_file.readframes(wav_file.getnframes())

        if sample_width != 2:
            raise ValueError("reference_audio 必须是 16-bit PCM WAV")
        if sample_rate != 16000:
            raise ValueError("reference_audio 必须是 16 kHz WAV")
        if channels not in (1, 2):
            raise ValueError("reference_audio 只支持单声道或双声道 WAV")

        pcm = np.frombuffer(raw, dtype="<i2")
        if channels == 2:
            pcm = pcm.reshape(-1, 2).astype(np.int32).mean(axis=1)
        waveform = (pcm.astype(np.float32) / 32768.0).reshape(1, -1)
        lengths = np.array([[waveform.shape[1]]], dtype=np.int32)
        return waveform, lengths

    def _ensure_client(self):
        current_thread = threading.get_ident()
        if self._client is not None:
            if self._client_owner_thread != current_thread:
                raise RuntimeError("Triton stream 只能由创建它的 TTS 工作线程访问")
            return

        self._client = grpcclient.InferenceServerClient(
            url=self.server, verbose=False, ssl=self.ssl
        )
        self._client.start_stream(callback=self._stream_callback)
        self._client_owner_thread = current_thread
        logger.bind(tag=TAG).info(
            f"Triton CosyVoice2 gRPC stream 已连接: {self.server}/{self.model_name}"
        )

    def _shutdown_client(self, cancel_requests=False):
        client = self._client
        if client is None:
            return
        try:
            client.stop_stream(cancel_requests=cancel_requests)
        except Exception as e:
            logger.bind(tag=TAG).warning(f"关闭 Triton stream 失败: {e}")
        try:
            client.close()
        except Exception as e:
            logger.bind(tag=TAG).warning(f"关闭 Triton client 失败: {e}")
        finally:
            self._client = None
            self._client_owner_thread = None

    def _build_inputs(self, target_text):
        inputs = []
        if self._reference_waveform is not None:
            reference_wav = grpcclient.InferInput(
                "reference_wav", self._reference_waveform.shape, "FP32"
            )
            reference_wav.set_data_from_numpy(self._reference_waveform)
            inputs.append(reference_wav)

            reference_wav_len = grpcclient.InferInput(
                "reference_wav_len", self._reference_waveform_len.shape, "INT32"
            )
            reference_wav_len.set_data_from_numpy(self._reference_waveform_len)
            inputs.append(reference_wav_len)

            reference_text = grpcclient.InferInput(
                "reference_text", [1, 1], "BYTES"
            )
            reference_text.set_data_from_numpy(
                np.array([[self.reference_text]], dtype=object)
            )
            inputs.append(reference_text)

        target = grpcclient.InferInput("target_text", [1, 1], "BYTES")
        target.set_data_from_numpy(np.array([[target_text]], dtype=object))
        inputs.append(target)
        return inputs

    @staticmethod
    def _is_final_response(result):
        response = result.get_response()
        parameters = getattr(response, "parameters", {})
        final_parameter = parameters.get("triton_final_response")
        return bool(getattr(final_parameter, "bool_param", False))

    @staticmethod
    def _waveform_to_pcm(waveform):
        samples = np.asarray(waveform).reshape(-1)
        if samples.size == 0:
            return b""
        if np.issubdtype(samples.dtype, np.floating):
            samples = np.clip(samples, -1.0, 1.0)
            samples = (samples * 32767.0).astype("<i2")
        else:
            samples = np.clip(samples, -32768, 32767).astype("<i2")
        return samples.tobytes()

    def _stream_callback(self, result, error):
        with self._request_lock:
            state = self._active_request
        if state is None:
            return

        if error is not None:
            state.error = error
            state.done.set()
            return

        try:
            waveform = result.as_numpy(self.output_name)
            if (
                waveform is not None
                and waveform.size
                and state.sentence_id == self.conn.sentence_id
                and not self.conn.client_abort
            ):
                if not state.first_audio_received:
                    state.first_audio_received = True
                    self.tts_audio_queue.put(
                        (
                            SentenceType.FIRST,
                            [],
                            state.display_text,
                            state.sentence_id,
                        )
                    )
                    logger.bind(tag=TAG).info(
                        "LATENCY event=triton_cosyvoice_first_audio request_ms={}",
                        int((time.monotonic() - state.started_at) * 1000),
                    )

                pcm = self._waveform_to_pcm(waveform)
                if self.output_sample_rate != self.conn.sample_rate:
                    pcm, state.resample_state = audioop.ratecv(
                        pcm,
                        2,
                        1,
                        self.output_sample_rate,
                        self.conn.sample_rate,
                        state.resample_state,
                    )
                if pcm:
                    self.opus_encoder.encode_pcm_to_opus_stream(
                        pcm, False, callback=self.handle_opus
                    )

            if self._is_final_response(result):
                self.opus_encoder.encode_pcm_to_opus_stream(
                    b"", True, callback=self.handle_opus
                )
                state.done.set()
        except Exception as e:
            state.error = e
            state.done.set()

    def _synthesize_request(self, target_text, display_text):
        self._ensure_client()
        request_id = uuid.uuid4().hex
        state = _RequestState(self.current_sentence_id, display_text)
        with self._request_lock:
            self._active_request = state

        try:
            outputs = [grpcclient.InferRequestedOutput(self.output_name)]
            self._client.async_stream_infer(
                model_name=self.model_name,
                inputs=self._build_inputs(target_text),
                model_version=self.model_version,
                request_id=request_id,
                outputs=outputs,
                enable_empty_final_response=True,
            )

            deadline = time.monotonic() + self.request_timeout
            while not state.done.wait(timeout=0.1):
                if self.conn.client_abort or self.conn.stop_event.is_set():
                    raise asyncio.CancelledError("TTS 请求已打断")
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"等待 Triton CosyVoice2 响应超时({self.request_timeout}s)"
                    )
            if state.error is not None:
                raise RuntimeError(f"Triton CosyVoice2 推理失败: {state.error}")
        except BaseException:
            self._shutdown_client(cancel_requests=True)
            raise
        finally:
            with self._request_lock:
                if self._active_request is state:
                    self._active_request = None

    def _prepare_target_text(self, text):
        target_text = MarkdownCleaner.clean_markdown(text)
        if self._correct_words_pattern:
            target_text = self._correct_words_pattern.sub(
                lambda match: self.correct_words[match.group(0)], target_text
            )
        return target_text

    def _synthesize_segment(self, text):
        original_text = text
        target_text = self._prepare_target_text(text)
        if target_text:
            self._record_tts_segment_latency(target_text)
            self._synthesize_request(target_text, original_text)

    def to_tts(self, text):
        """为唤醒词缓存等非实时调用生成 Opus 帧，不复用实时播放 stream。"""
        target_text = self._prepare_target_text(text)
        if not target_text:
            return []

        sample_rate = getattr(self.conn, "sample_rate", self.output_sample_rate)
        encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=sample_rate, channels=1, frame_size_ms=60
        )
        audio_frames = []
        done = threading.Event()
        callback_error = []
        resample_state = None

        def callback(result, error):
            nonlocal resample_state
            if error is not None:
                callback_error.append(error)
                done.set()
                return
            try:
                waveform = result.as_numpy(self.output_name)
                if waveform is not None and waveform.size:
                    pcm = self._waveform_to_pcm(waveform)
                    if self.output_sample_rate != sample_rate:
                        pcm, resample_state = audioop.ratecv(
                            pcm,
                            2,
                            1,
                            self.output_sample_rate,
                            sample_rate,
                            resample_state,
                        )
                    encoder.encode_pcm_to_opus_stream(
                        pcm, False, callback=audio_frames.append
                    )
                if self._is_final_response(result):
                    encoder.encode_pcm_to_opus_stream(
                        b"", True, callback=audio_frames.append
                    )
                    done.set()
            except Exception as e:
                callback_error.append(e)
                done.set()

        client = grpcclient.InferenceServerClient(
            url=self.server, verbose=False, ssl=self.ssl
        )
        try:
            client.start_stream(callback=callback)
            client.async_stream_infer(
                model_name=self.model_name,
                inputs=self._build_inputs(target_text),
                model_version=self.model_version,
                request_id=uuid.uuid4().hex,
                outputs=[grpcclient.InferRequestedOutput(self.output_name)],
                enable_empty_final_response=True,
            )
            if not done.wait(self.request_timeout):
                raise TimeoutError(
                    f"等待 Triton CosyVoice2 响应超时({self.request_timeout}s)"
                )
            if callback_error:
                raise RuntimeError(f"Triton CosyVoice2 推理失败: {callback_error[0]}")
            return audio_frames
        except Exception as e:
            logger.bind(tag=TAG).error(f"生成 Triton CosyVoice2 缓存音频失败: {e}")
            return []
        finally:
            try:
                client.stop_stream(cancel_requests=not done.is_set())
            except Exception:
                pass
            client.close()
            encoder.close()

    def tts_text_priority_thread(self):
        """消费 LLM 增量文本；每个可播报片段对应一个 decoupled 请求。"""
        try:
            while not self.conn.stop_event.is_set():
                try:
                    message = self.tts_text_queue.get(timeout=1)
                    if self.conn.client_abort:
                        self._shutdown_client(cancel_requests=True)
                        continue
                    if message.sentence_id != self.conn.sentence_id:
                        continue

                    if message.sentence_type == SentenceType.FIRST:
                        self.current_sentence_id = message.sentence_id
                        self.tts_stop_request = False
                        self.processed_chars = 0
                        self.tts_text_buff = []
                        self.is_first_sentence = True
                        self.tts_audio_first_sentence = True
                        self.before_stop_play_files.clear()
                        if hasattr(self, "opus_encoder"):
                            self.opus_encoder.reset_state()
                    elif message.content_type == ContentType.TEXT:
                        self.tts_text_buff.append(message.content_detail)
                        segment_text = self._get_segment_text()
                        if segment_text:
                            self._synthesize_segment(segment_text)
                    elif message.content_type == ContentType.FILE:
                        self._process_remaining_text()
                        if message.content_file and os.path.exists(message.content_file):
                            self._process_audio_file_stream(
                                message.content_file,
                                callback=lambda data: self.handle_audio_file(
                                    data, message.content_detail
                                ),
                            )

                    if message.sentence_type == SentenceType.LAST:
                        self._process_remaining_text()
                        self._process_before_stop_play_files()
                except queue.Empty:
                    continue
                except asyncio.CancelledError:
                    logger.bind(tag=TAG).info("Triton CosyVoice2 请求已取消")
                except Exception as e:
                    logger.bind(tag=TAG).error(
                        f"处理 Triton CosyVoice2 TTS 失败: {e}, 堆栈: {traceback.format_exc()}"
                    )
                    self._process_before_stop_play_files()
        finally:
            self._shutdown_client(cancel_requests=True)

    def _process_remaining_text(self):
        full_text = "".join(self.tts_text_buff)
        remaining_text = full_text[self.processed_chars :]
        if not remaining_text:
            return False
        segment_text = textUtils.get_string_no_punctuation_or_emoji(remaining_text)
        self.processed_chars = len(full_text)
        if not segment_text:
            return False
        self._synthesize_segment(segment_text)
        return True

    async def text_to_speak(self, text, _):
        """兼容 Provider 接口；正常对话由专属 TTS 工作线程调用同步实现。"""
        await asyncio.to_thread(self._synthesize_segment, text)

    async def close(self):
        # Triton 文档要求 stream API 不跨线程；实际关闭由 TTS 工作线程 finally 完成。
        await super().close()
