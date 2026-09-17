"""Bounded local Ollama calls in the existing killable process boundary."""
import json
import requests
from app.agent.ollama_client import OllamaClient
from app.documents.limits import PdfLimits
from app.documents.process import run_isolated


class KnowledgeSetupError(ValueError):
    """Application-owned, path-free setup diagnostic."""


def post(session, endpoint, **kwargs):
    # One transient connection/timeout retry; the parent imposes a wall deadline.
    for attempt in range(2):
        try: return session.post(endpoint, **kwargs)
        except (requests.ConnectionError, requests.Timeout):
            if attempt: raise


def read_json(response, maximum):
    if response.status_code != 200: raise ValueError('Local model unavailable.')
    body = bytearray()
    try:
        for part in response.iter_content(4096):
            body.extend(part)
            if len(body) > maximum: raise ValueError('Local response limit exceeded.')
        return json.loads(body)
    finally:
        body[:] = b'\0' * len(body)
        body.clear()


def local_request(endpoint, model, action, payload, timeout, progress=lambda *_: None):
    """Never receives a tool schema; never follows redirects or environment proxies."""
    base = endpoint.removesuffix('/api/chat')
    try:
        with requests.Session() as session:
            session.trust_env = False
            with post(session, base + '/api/show', json={'model': model}, timeout=(3, min(timeout, 30)),
                              allow_redirects=False, stream=True) as response:
                metadata = read_json(response, 262144)
            if not isinstance(metadata, dict) or metadata.get('remote_model') or metadata.get('remote_host') or not metadata.get('model_info'):
                raise ValueError('Local model required.')
            with post(session, base + '/api/' + action, json=payload, timeout=(3, min(timeout, 30)),
                              allow_redirects=False, stream=True) as response:
                result = read_json(response, 262144 if action == 'embed' else 65536)
            return {'ok': True, 'data': result}
    except Exception:
        return {'ok': False}


class KnowledgeClient:
    def __init__(self, base_url, model, isolate=run_isolated):
        validated = OllamaClient(base_url, model)
        self.endpoint, self.model, self.isolate = validated.endpoint, validated.model, isolate

    def request(self, action, payload, cancel, timeout):
        if action not in {'embed', 'chat'}: raise ValueError('Unsupported knowledge endpoint.')
        try:
            result = self.isolate(local_request, (self.endpoint, self.model, action, payload, timeout),
                                  PdfLimits(), cancel, lambda *_: None, timeout=timeout)
            if not result['ok']:
                raise KnowledgeSetupError('Local Ollama model unavailable or response invalid. Install the configured model manually (default embeddings: ollama pull nomic-embed-text), then retry. No automatic download is performed.')
            return result['data']
        finally:
            payload.clear()
