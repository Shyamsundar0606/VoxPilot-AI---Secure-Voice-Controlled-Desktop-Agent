"""Native decoder protocol is tested with injected Vosk, not a model download."""
import json
import sys
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.voice.vosk_decoder import VoskDecoder, WakeDecoderError, _vosk_process


@pytest.mark.parametrize('final,text', [(False, 'hello'), (True, 'hello'), (True, 'hello google'), (True, '[unk]'), (True, '')])
def test_constrained_grammar_final_results_only_model_loaded_once(monkeypatch, final, text):
    recognizer = Mock(AcceptWaveform=Mock(return_value=final), Result=Mock(return_value=json.dumps({'text': text})),
                      PartialResult=Mock(return_value='{"partial":"hello"}'))
    vosk = SimpleNamespace(Model=Mock(), KaldiRecognizer=Mock(return_value=recognizer), SetLogLevel=Mock())
    monkeypatch.setitem(sys.modules, 'vosk', vosk)
    pcm = bytearray(b'\x01\x02' * 800)
    connection = Mock()
    connection.recv.side_effect = [('start', 'hello'), ('frame', pcm), ('reset', None), ('start', 'hello'), EOFError()]
    _vosk_process(connection, 'local-test-model')
    vosk.Model.assert_called_once_with(model_path='local-test-model')
    assert vosk.KaldiRecognizer.call_count == 2
    for call in vosk.KaldiRecognizer.call_args_list:
        assert call.args[1] == 16000 and json.loads(call.args[2]) == ['hello', '[unk]']
    assert connection.send.call_args_list[2].args == ((True, text if final else ''),)
    recognizer.PartialResult.assert_not_called(); recognizer.FinalResult.assert_not_called()
    assert not any(pcm)
    connection.close.assert_called_once()


def test_missing_model_never_starts_a_process(tmp_path):
    context = Mock()
    decoder = VoskDecoder(tmp_path / 'missing', context_factory=context)
    with pytest.raises(WakeDecoderError, match='VOSK_MODEL_PATH') as error: decoder.start('hello', Event())
    assert error.value.code == 'missing_model'
    context.assert_not_called()


def fake_transport(tmp_path):
    context, connection, child = Mock(), Mock(), Mock()
    context.Pipe.return_value = (connection, child)
    context.Process.return_value.pid = 123
    context.Process.return_value.is_alive.return_value = True
    connection.poll.return_value = True
    connection.recv.return_value = (True, None)
    decoder = VoskDecoder(tmp_path, context_factory=lambda _: context)
    return decoder, context, connection


def test_decoder_process_reused_across_sessions(tmp_path):
    decoder, context, connection = fake_transport(tmp_path)
    decoder.start('hello', Event()); decoder.reset(); decoder.start('hello', Event())
    context.Process.assert_called_once()
    assert [c.args[0][0] for c in connection.send.call_args_list] == ['start', 'reset', 'start']
    decoder.shutdown(); decoder.shutdown()
    context.Process.return_value.terminate.assert_called_once()
    context.Process.return_value.join.assert_called_once()


def test_cancel_during_native_load_terminates_process(tmp_path):
    decoder, context, connection = fake_transport(tmp_path)
    cancel = Event()
    connection.poll.side_effect = lambda _: cancel.set() or False
    with pytest.raises(WakeDecoderError, match='cancelled'): decoder.start('hello', cancel)
    context.Process.return_value.terminate.assert_called_once()
    assert decoder.process is None


def test_native_timeout_terminates_process(tmp_path, monkeypatch):
    import app.voice.vosk_decoder as module
    decoder, context, connection = fake_transport(tmp_path)
    clock = iter([0, 31])
    monkeypatch.setattr(module, 'monotonic', lambda: next(clock))
    with pytest.raises(WakeDecoderError, match='timed out'): decoder.start('hello', Event())
    context.Process.return_value.terminate.assert_called_once()


def test_missing_vosk_package_returns_setup_error(monkeypatch):
    monkeypatch.setitem(sys.modules, 'vosk', None)
    connection = Mock()
    _vosk_process(connection, 'local-test-model')
    connection.send.assert_called_once_with((False, 'vosk_unavailable'))


def test_invalid_model_error_has_no_internal_path(monkeypatch):
    vosk = SimpleNamespace(Model=Mock(side_effect=ValueError('PRIVATE_PATH')), KaldiRecognizer=Mock(), SetLogLevel=Mock())
    monkeypatch.setitem(sys.modules, 'vosk', vosk)
    connection = Mock()
    _vosk_process(connection, 'local-test-model')
    connection.send.assert_called_once_with((False, 'invalid_model'))


def fake_native_process(connection, path):
    connection.send((True, None))
    try:
        while True:
            operation, payload = connection.recv()
            connection.send((True, 'hello' if operation == 'frame' else None))
    except EOFError: pass
    finally: connection.close()


def test_real_persistent_process_lifecycle(tmp_path):
    from multiprocessing import get_context
    class Context:
        def __init__(self): self.context = get_context('spawn')
        def Pipe(self): return self.context.Pipe()
        def Process(self, **kwargs):
            kwargs['target'] = fake_native_process
            return self.context.Process(**kwargs)
    decoder = VoskDecoder(tmp_path, context_factory=lambda _: Context())
    try:
        decoder.start('hello', Event())
        pid = decoder.process.pid
        assert decoder.feed(bytearray(1600), Event()) == 'hello'
        decoder.reset(); decoder.start('hello', Event())
        assert decoder.process.pid == pid
    finally: decoder.shutdown()
    assert decoder.process is None and decoder.connection is None


def test_cancel_during_native_frame_terminates_and_can_reload(tmp_path):
    decoder, context, connection = fake_transport(tmp_path)
    decoder.start('hello', Event())
    cancel = Event()
    connection.poll.side_effect = lambda _: cancel.set() or False
    with pytest.raises(WakeDecoderError, match='cancelled'): decoder.feed(bytearray(1600), cancel)
    assert decoder.process is None
    connection.poll.side_effect = None
    decoder.start('hello', Event())
    assert context.Process.call_count == 2
    decoder.shutdown()
