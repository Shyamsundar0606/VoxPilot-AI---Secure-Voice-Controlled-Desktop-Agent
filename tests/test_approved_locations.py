"""Only synthetic folders; no audio, model or user-document access."""
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from app.filesystem.roots import ApprovedRoots
from app.documents.policy import PdfArgs
from app.knowledge.policy import IndexArgs
from app.agent.executor import CommandExecutor
from app.ui.locations_panel import LocationsWorker
from app.models import Status
from tests.test_filesystem import fs
from tests.test_runtime import _window, _wait_for_worker


def reload_roots(roots):
    roots.platform.known_roots.return_value = {}
    return ApprovedRoots(roots.settings_path, roots.platform)


def test_multiple_persistence_duplicates_nested_removal(fs):
    roots = fs[0].roots
    outer = fs[1] / 'Research'; outer.mkdir()
    inner = outer / 'Reports'; inner.mkdir()
    (inner / 'source.txt').write_text('synthetic')
    first = roots.add(outer)
    assert roots.add(outer) == first
    nested = roots.add(inner)
    project = roots.add_project(outer)
    assert len({first, nested, project}) == 3
    loaded = reload_roots(roots)
    assert loaded.resolve(first, 'Reports/source.txt').is_file()
    assert loaded.resolve(nested) == inner
    PdfArgs(root=first, query='source.pdf'); IndexArgs(root=first)
    with pytest.raises(ValueError): loaded.remove(first)
    loaded.remove(first, confirmed=True)
    loaded = reload_roots(loaded)
    with pytest.raises(ValueError): loaded.resolve(first)
    assert loaded.resolve(nested) == inner
    assert (inner / 'source.txt').read_text() == 'synthetic'
    assert loaded.add(outer) != first


def test_known_removal_persists_and_legacy_migrates(fs):
    roots = fs[0].roots
    roots.platform.known_roots.return_value = {'documents': fs[1]}
    roots.settings_path.write_text(json.dumps({'project_roots': {'project_3': str(fs[2])}}))
    loaded = ApprovedRoots(roots.settings_path, roots.platform)
    assert loaded.resolve('project_3') == fs[2]
    loaded.remove('documents', confirmed=True)
    assert 'documents' not in ApprovedRoots(roots.settings_path, roots.platform).snapshot()


def test_failed_save_is_atomic(fs, monkeypatch):
    roots = fs[0].roots
    folder = fs[1] / 'Research'; folder.mkdir()
    key = roots.add(folder)
    original = roots.settings_path.read_bytes()
    monkeypatch.setattr('app.filesystem.roots.os.replace', Mock(side_effect=OSError('disk error')))
    with pytest.raises(OSError): roots.remove(key, confirmed=True)
    assert roots.resolve(key) == folder
    assert roots.settings_path.read_bytes() == original
    assert not list(roots.settings_path.parent.glob('approved-*.tmp'))


def test_missing_corrupt_and_revoked_sources(fs):
    roots = fs[0].roots
    folder = fs[1] / 'Research'; folder.mkdir()
    key = roots.add(folder); folder.rmdir()
    assert next(row for row in roots.locations() if row['id'] == key)['status'].startswith('Missing')
    with pytest.raises(ValueError, match='missing or unavailable'): roots.resolve(key)
    roots.settings_path.write_text('{broken')
    with pytest.raises(ValueError, match='settings'): reload_roots(roots).snapshot()


@pytest.mark.parametrize('relative', ['../escape', 'a/../../escape', r'C:\Windows', r'\\host\share', r'\\?\C:\data', 'NUL', 'a:stream'])
def test_new_roots_reject_escape(fs, relative):
    folder = fs[1] / 'Research'; folder.mkdir()
    roots = fs[0].roots; key = roots.add(folder)
    with pytest.raises(ValueError): roots.resolve(key, relative)


def test_symlink_escape_and_unsafe_approval(fs, monkeypatch):
    roots = fs[0].roots
    folder = fs[1] / 'Research'; folder.mkdir()
    key = roots.add(folder)
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda p: p == folder / 'escape' or original(p))
    with pytest.raises(ValueError): roots.resolve(key, 'escape', must_exist=False)
    for path in [Path.cwd(), Path.cwd().parent, Path.home(), Path(fs[1].anchor), r'\\host\share', r'\\?\C:\data', 'relative']:
        with pytest.raises(ValueError): roots.add(path)


def test_cancelled_worker_does_not_mutate(fs):
    worker = LocationsWorker(fs[0].roots, 'remove', 'documents')
    results = []; worker.finished.connect(results.append)
    worker.cancel_event.set(); worker.run()
    assert results[0].status == Status.FAILED
    assert 'documents' in fs[0].roots.snapshot()


def test_ui_add_list_open_confirm_remove_and_busy(fs, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    executor = CommandExecutor(); executor.registry.filesystem = fs[0]
    window = _window(executor=executor); panel = window.locations_panel
    folder = fs[1] / 'Research'; folder.mkdir()
    monkeypatch.setattr('app.ui.locations_panel.QFileDialog.getExistingDirectory', lambda *a: str(folder))
    panel.action('add'); _wait_for_worker(window)
    assert panel.table.topLevelItemCount() == 3
    item = next(panel.table.topLevelItem(i) for i in range(3) if panel.table.topLevelItem(i).text(2) == str(folder))
    key = item.text(0)
    assert item.text(1) == 'Research' and item.text(3) == 'Available'
    assert window.knowledge_panel.root.findData(key) >= 0
    panel.table.setCurrentItem(item)
    panel.action('open'); _wait_for_worker(window)
    fs[0].roots.platform.open_folder.assert_called_once_with(folder)
    item = next(panel.table.topLevelItem(i) for i in range(3) if panel.table.topLevelItem(i).text(0) == key)
    panel.table.setCurrentItem(item)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.No)
    panel.action('remove'); assert key in fs[0].roots.snapshot()
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    panel.action('remove'); _wait_for_worker(window)
    assert key not in fs[0].roots.snapshot() and folder.exists()
    assert window.knowledge_panel.root.findData(key) == -1
    panel.set_busy(True); assert all(not b.isEnabled() for b in panel.buttons)
    window._tts_pending = True
    panel.action('refresh'); assert window._active_thread is None
    window._tts_pending = False; window.close()
