import re
import unicodedata
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.security.filesystem_policy import RootArgs, safe_relative


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class IndexArgs(RootArgs):
    formats: Literal['pdf', 'all'] = 'all'

    @field_validator('root')
    @classmethod
    def approved_name(cls, value):
        if value not in {'desktop', 'documents', 'downloads'} and not re.fullmatch(r'(?:document|project)_[1-9]\d*', value):
            raise ValueError('Select an approved document root explicitly.')
        return value


class QueryArgs(EmptyArgs):
    query: str = Field(min_length=1, max_length=1000)

    @field_validator('query')
    @classmethod
    def safe_question(cls, value):
        if not value.strip() or any(unicodedata.category(c).startswith('C') for c in value):
            raise ValueError('Use a nonempty question without control characters.')
        return value.strip()


class RemoveArgs(EmptyArgs):
    filename: str = Field(min_length=1, max_length=400)
    _path = field_validator('filename')(safe_relative)


SCHEMAS = {'index_documents': IndexArgs, 'refresh_document_index': EmptyArgs,
           'list_indexed_documents': EmptyArgs, 'ask_documents': QueryArgs,
           'search_documents': QueryArgs, 'show_answer_sources': EmptyArgs,
           'remove_indexed_document': RemoveArgs, 'clear_document_index': EmptyArgs}
KNOWLEDGE_TOOLS = frozenset(SCHEMAS)


def validate_arguments(tool, arguments):
    return SCHEMAS[tool].model_validate(arguments).model_dump()


def knowledge_request(command):
    from app.models import ToolRequest
    value = command.strip()
    fixed = {'refresh my document index': 'refresh_document_index', 'show indexed documents': 'list_indexed_documents',
             'show sources for the last answer': 'show_answer_sources', 'clear the document index': 'clear_document_index'}
    name = fixed.get(value.lower().rstrip('.!?'))
    if name: return ToolRequest(tool_name=name)
    match = re.fullmatch(r'index (pdfs|documents)(?: in (.+))?', value, re.I)
    if match:
        return ToolRequest(tool_name='index_documents', arguments={'root': (match[2] or '').lower(), 'formats': 'pdf' if match[1].lower() == 'pdfs' else 'all'})
    for pattern, name, key in [(r'ask my documents\s*:?\s+(.+)', 'ask_documents', 'query'),
                               (r'search my documents for (.+)', 'search_documents', 'query'),
                               (r'which document discusses (.+)', 'search_documents', 'query'),
                               (r'remove (.+) from the index', 'remove_indexed_document', 'filename')]:
        match = re.fullmatch(pattern, value, re.I | re.S)
        if match: return ToolRequest(tool_name=name, arguments={key: match[1]})
    return None
