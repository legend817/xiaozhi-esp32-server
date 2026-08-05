import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import config.logger


class _FakeLogger:
    def bind(self, **_):
        return self

    def debug(self, *_, **__):
        pass

    def info(self, *_, **__):
        pass

    def warning(self, *_, **__):
        pass

    def error(self, *_, **__):
        pass


config.logger.setup_logging = lambda *_args, **_kwargs: _FakeLogger()

from core.providers.tts.dto.dto import SentenceType
from core.providers.tts import triton_cosyvoice


class _FakeInferInput:
    def __init__(self, name, shape, datatype):
        self.name = name
        self.shape = shape
        self.datatype = datatype
        self.data = None

    def set_data_from_numpy(self, data):
        self.data = data


class _FakeOutput:
    def __init__(self, name):
        self.name = name


class _FakeEncoder:
    def __init__(self):
        self.calls = []

    def encode_pcm_to_opus_stream(self, pcm, is_end, callback):
        self.calls.append((pcm, is_end))
        if pcm:
            callback(b"opus-frame")


class _FakeResult:
    def __init__(self, waveform, final=False):
        self.waveform = waveform
        self.response = SimpleNamespace(
            parameters={
                "triton_final_response": SimpleNamespace(bool_param=final)
            }
        )

    def as_numpy(self, name):
        return self.waveform if name == "waveform" else None

    def get_response(self):
        return self.response


class TritonCosyVoiceTests(unittest.TestCase):
    def setUp(self):
        fake_grpc = SimpleNamespace(
            InferInput=_FakeInferInput,
            InferRequestedOutput=_FakeOutput,
            InferenceServerClient=object,
        )
        self.grpc_patch = patch.object(triton_cosyvoice, "grpcclient", fake_grpc)
        self.grpc_patch.start()
        self.provider = triton_cosyvoice.TTSProvider(
            {"server": "localhost:8001", "model_name": "cosyvoice2"}, True
        )
        self.provider.conn = SimpleNamespace(
            sentence_id="sentence-1",
            sample_rate=24000,
            client_abort=False,
            stop_event=threading.Event(),
        )
        self.provider.current_sentence_id = "sentence-1"
        self.provider.opus_encoder = _FakeEncoder()

    def tearDown(self):
        self.grpc_patch.stop()

    def test_cached_voice_request_only_sends_target_text(self):
        inputs = self.provider._build_inputs("你好")
        self.assertEqual(["target_text"], [item.name for item in inputs])
        self.assertEqual("你好", inputs[0].data[0][0])

    def test_audio_chunk_is_forwarded_before_final_response(self):
        state = triton_cosyvoice._RequestState("sentence-1", "你好")
        self.provider._active_request = state

        self.provider._stream_callback(
            _FakeResult(np.array([[0.25, -0.25]], dtype=np.float32)), None
        )

        first = self.provider.tts_audio_queue.get_nowait()
        audio = self.provider.tts_audio_queue.get_nowait()
        self.assertEqual(SentenceType.FIRST, first[0])
        self.assertEqual("你好", first[2])
        self.assertEqual(SentenceType.MIDDLE, audio[0])
        self.assertEqual(b"opus-frame", audio[1])
        self.assertFalse(state.done.is_set())

        self.provider._stream_callback(
            _FakeResult(np.array([], dtype=np.float32), final=True), None
        )
        self.assertTrue(state.done.is_set())
        self.assertTrue(self.provider.opus_encoder.calls[-1][1])

    def test_float_waveform_is_clipped_to_pcm16(self):
        pcm = self.provider._waveform_to_pcm(
            np.array([-2.0, 0.0, 2.0], dtype=np.float32)
        )
        samples = np.frombuffer(pcm, dtype="<i2")
        np.testing.assert_array_equal(samples, [-32767, 0, 32767])


if __name__ == "__main__":
    unittest.main()
