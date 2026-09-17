import json
from threading import Event
from unittest.mock import Mock, patch
import pytest
from app.knowledge.embedding import Embedder
from app.knowledge.limits import KnowledgeLimits
from app.knowledge.transport import KnowledgeClient, local_request, post
import requests


def response(value, status=200):
    item = Mock(status_code=status)
    item.__enter__ = Mock(return_value=item); item.__exit__ = Mock(return_value=False)
    item.iter_content.return_value = [json.dumps(value).encode()]
    return item


@pytest.mark.parametrize('url', ['https://localhost:11434', 'http://example.com', 'http://127.0.0.1.evil', 'http://localhost@evil',
                                  'http://localhost/path', 'http://localhost?url=evil', 'http://0.0.0.0', 'http://192.168.1.1'])
def test_remote_endpoints_rejected(url):
    with pytest.raises(ValueError): KnowledgeClient(url, 'nomic-embed-text')


@pytest.mark.parametrize('model', ['remote/cloud', 'model-cloud', '', 'a' * 101])
def test_cloud_model_names_rejected(model):
    with pytest.raises(ValueError): KnowledgeClient('http://localhost:11434', model)


def test_loopback_requests_ignore_proxies_and_redirects():
    session = Mock(); session.__enter__ = Mock(return_value=session); session.__exit__ = Mock(return_value=False)
    session.post.side_effect = [response({'model_info': {'architecture': 'bert'}}), response({'embeddings': [[1, 2]]})]
    with patch('app.knowledge.transport.requests.Session', return_value=session):
        result = local_request('http://127.0.0.1:11434/api/chat', 'nomic-embed-text', 'embed', {'input': 'data'}, 10)
    assert result['ok'] and session.trust_env is False
    assert session.post.call_count == 2
    for call in session.post.call_args_list:
        assert call.kwargs['allow_redirects'] is False and call.kwargs['stream'] is True
        assert call.kwargs['timeout'] == (3, 10)


@pytest.mark.parametrize('metadata,status', [({'model_info': {}, 'remote_host': 'evil'}, 200),
    ({'model_info': {'x': 1}, 'remote_model': 'cloud'}, 200), ({'model_info': {'x': 1}}, 302), ({}, 404)])
def test_model_metadata_must_be_local_before_text_sent(metadata, status):
    session = Mock(); session.__enter__ = Mock(return_value=session); session.__exit__ = Mock(return_value=False)
    session.post.return_value = response(metadata, status)
    with patch('app.knowledge.transport.requests.Session', return_value=session):
        assert not local_request('http://127.0.0.1/api/chat', 'model', 'embed', {'input': 'private'}, 10)['ok']
    assert session.post.call_count == 1
    assert session.post.call_args.kwargs['json'] == {'model': 'model'}


def test_oversized_metadata_never_sends_text():
    session = Mock(); session.__enter__ = Mock(return_value=session); session.__exit__ = Mock(return_value=False)
    session.post.return_value = response({'model_info': 'x' * 262144})
    with patch('app.knowledge.transport.requests.Session', return_value=session):
        assert not local_request('http://127.0.0.1/api/chat', 'model', 'embed', {'input': 'private'}, 10)['ok']
    assert session.post.call_count == 1


def test_embedding_payload_bounded_no_automatic_pull():
    client = Mock(model='nomic-embed-text')
    client.request.return_value = {'embeddings': [[3, 4]]}
    embedder = Embedder(client, KnowledgeLimits())
    assert len(embedder.embed('bounded text', Event(), 10)) == 2
    action, payload, *_ = client.request.call_args.args
    assert action == 'embed' and payload['truncate'] is False
    assert payload['input'] == 'search_document: bounded text'
    with pytest.raises(ValueError): embedder.embed('a' * 1801, Event(), 10)


def test_model_missing_clears_request_payload():
    client = KnowledgeClient('http://localhost', 'nomic-embed-text', isolate=Mock(return_value={'ok': False}))
    payload = {'input': 'private'}
    with pytest.raises(ValueError, match='manually'): client.request('embed', payload, Event(), 1)
    assert payload == {}


def test_connection_retries_are_bounded():
    session = Mock()
    session.post.side_effect = requests.ConnectionError('unavailable')
    with pytest.raises(requests.ConnectionError): post(session, 'http://127.0.0.1/api/show')
    assert session.post.call_count == 2


@pytest.mark.parametrize('bad', [[], [1, 2], [[1], [2]], [[float('nan')]], [[float('inf')]], [[0]], [['bad']]])
def test_embedding_response_validation(bad):
    embedder = Embedder(Mock(model='local', request=Mock(return_value={'embeddings': bad})), KnowledgeLimits())
    with pytest.raises(ValueError): embedder.embed('text', Event(), 10)
