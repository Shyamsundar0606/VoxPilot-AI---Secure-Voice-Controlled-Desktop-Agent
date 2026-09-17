from contextlib import closing
from dataclasses import replace
from multiprocessing import active_children
from pathlib import Path
import sqlite3
from threading import Event, Timer
from time import sleep, monotonic
from unittest.mock import Mock, patch
import pytest
from app.documents.process import run_isolated, DocumentError
from app.documents.limits import PdfLimits
from app.knowledge.discovery import discover, fingerprint
from app.knowledge.extraction import extract_source
from app.knowledge.limits import KnowledgeLimits
from app.knowledge.storage import IndexStore
from app.models import Status
from tests.test_filesystem import fs
from tests.test_documents import write_pdf
from tests.test_knowledge import knowledge, index, documents, req


def blocked_stage(progress): sleep(20)


@pytest.mark.parametrize('mode', ['cancel', 'timeout'])
def test_real_isolated_stage_terminates(mode):
    before = {child.pid for child in active_children()}
    cancel = Event(); timer = Timer(.2, cancel.set)
    if mode == 'cancel': timer.start()
    started = monotonic()
    try:
        with pytest.raises(DocumentError):
            run_isolated(blocked_stage, (), PdfLimits(), cancel, lambda *_: None, timeout=.2 if mode == 'timeout' else 10)
    finally:
        if mode == 'cancel': timer.join()
    assert monotonic() - started < 5
    assert {child.pid for child in active_children()} == before


def test_real_isolated_discovery_hash_and_pdf_page_extraction(knowledge):
    service, docs, *_ = knowledge
    write_pdf(docs / 'report.pdf', ('Synthetic first page about governance and controls.', 'Synthetic second page about resilience and risk.'))
    args = service.roots.configuration()
    items = run_isolated(discover, (args, 'documents', 'all', service.limits), PdfLimits(), Event(), lambda *_: None)
    digest = run_isolated(fingerprint, (args, items[0], service.limits), PdfLimits(), Event(), lambda *_: None)
    result = run_isolated(extract_source, (args, items[0], PdfLimits(), service.limits), PdfLimits(), Event(), lambda *_: None)
    assert len(digest) == 64 and result['page_count'] == 2
    assert [number for number, _ in result['pages']] == [1, 2]


@pytest.mark.parametrize('link_method', ['is_symlink', 'is_junction'])
def test_link_and_junction_policy_excludes_sources(knowledge, link_method):
    service, docs, *_ = knowledge
    source = docs / 'report.txt'; source.write_text('Synthetic evidence.')
    original = getattr(Path, link_method)
    with patch.object(Path, link_method, lambda path: path == source or original(path)):
        assert discover(service.roots.configuration(), 'documents', 'all', service.limits) == []


@pytest.mark.parametrize('limit', ['max_entries', 'max_depth', 'max_documents'])
def test_discovery_limits_abort_instead_of_pruning_index(knowledge, limit):
    service, docs, *_ = knowledge
    (docs / 'a.txt').write_text('Evidence'); (docs / 'b.txt').write_text('Evidence')
    if limit == 'max_depth':
        nested = docs / 'one' / 'two'; nested.mkdir(parents=True); (nested / 'c.txt').write_text('Evidence')
    limits = replace(service.limits, **{limit: 1})
    with pytest.raises(ValueError): discover(service.roots.configuration(), 'documents', 'all', limits)


@pytest.mark.parametrize('limit', ['max_documents', 'max_total_chunks', 'max_index_bytes'])
def test_storage_limits_rollback(knowledge, limit):
    service, docs, *_ = knowledge
    (docs / 'a.txt').write_text('Evidence')
    assert index(service).status == Status.COMPLETED
    before = documents(service)
    (docs / 'b.txt').write_text('Additional evidence')
    service.store.limits = replace(service.limits, **{limit: 1 if limit != 'max_index_bytes' else 100})
    assert index(service).status == Status.FAILED
    service.store.limits = service.limits
    assert documents(service) == before


def test_empty_schema_initialization_and_foreign_schema_refusal(knowledge):
    service, docs, *_ = knowledge
    with service.store.connect() as db: assert db.execute('PRAGMA user_version').fetchone()[0] == 1
    foreign = docs.parent / 'foreign.sqlite3'
    with closing(sqlite3.connect(foreign)) as db:
        db.execute('CREATE TABLE unrelated(value TEXT)'); db.commit()
    with pytest.raises(ValueError, match='Unversioned'):
        with IndexStore(foreign, service.limits).connect(): pass
    with closing(sqlite3.connect(foreign)) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [('unrelated',)]


def test_malformed_database_fails_safely(knowledge):
    service, *_ = knowledge
    service.store.path.write_bytes(b'not a sqlite database')
    assert service.execute(req('list_indexed_documents')).status == Status.FAILED


def test_replaced_file_with_same_text_not_returned_until_refresh(knowledge):
    service, docs, *_ = knowledge
    source = docs / 'a.txt'; source.write_text('Synthetic evidence'); index(service)
    replacement = docs / 'replacement.txt'; replacement.write_text('Synthetic evidence')
    replacement.replace(source)
    result = service.execute(req('search_documents', query='Evidence'))
    assert result.knowledge_data['sources'] == []
    assert index(service).status == Status.COMPLETED
    assert service.execute(req('search_documents', query='Evidence')).knowledge_data['sources']


def test_embedding_dimension_change_rolls_back(knowledge):
    import numpy as np
    service, docs, embedder, _ = knowledge
    (docs / 'a.txt').write_text('Evidence'); index(service)
    before = documents(service)
    (docs / 'b.txt').write_text('Other evidence')
    embedder.embed.side_effect = lambda *a, **k: np.array([1., 0.], dtype='<f4')
    assert index(service).status == Status.FAILED and documents(service) == before


def test_cancellation_after_last_embedding_before_commit_rolls_back(knowledge):
    service, docs, *_ = knowledge
    (docs / 'a.txt').write_text('Evidence'); index(service)
    before = documents(service)
    (docs / 'a.txt').write_text('Changed evidence')
    cancel = Event()
    original = service.store.put
    def put(*args): original(*args); cancel.set()
    service.store.put = put
    assert service.execute(req('index_documents', root='documents'), cancel).status == Status.CANCELLED
    assert documents(service) == before


def test_revoked_root_refresh_removes_stale_chunks(knowledge):
    service, docs, *_ = knowledge
    (docs / 'a.txt').write_text('Evidence'); index(service)
    service.roots._roots.pop('documents')
    assert service.execute(req('refresh_document_index')).status == Status.COMPLETED
    assert documents(service) == []


def test_index_refuses_storage_inside_source(knowledge):
    service, docs, *_ = knowledge
    service.store.path = docs / 'index.sqlite3'
    assert service.execute(req('list_indexed_documents')).status == Status.FAILED
    assert not service.store.path.exists()


def test_source_change_during_generation_rejects_answer(knowledge):
    service, docs, _, client = knowledge
    source = docs / 'a.txt'; source.write_text('Evidence'); index(service)
    answer = client.request.side_effect
    def changed(*args):
        result = answer(*args); source.write_text('Changed evidence'); return result
    client.request.side_effect = changed
    result = service.execute(req('ask_documents', query='Evidence'))
    assert result.status == Status.FAILED and result.knowledge_data is None


def test_query_timeout_does_not_fall_back_to_answer(knowledge):
    service, docs, _, client = knowledge
    (docs / 'a.txt').write_text('Evidence'); index(service)
    ticks = iter([0, 0, 121])
    service.clock = lambda: next(ticks, 121)
    assert service.execute(req('ask_documents', query='Evidence')).status == Status.FAILED
    client.request.assert_not_called()
