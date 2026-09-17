def render_sources(chunks, documents):
    result = []
    for chunk in chunks:
        item = documents[chunk['document_id']]
        page = f" — page {chunk['page']}" if chunk['page'] is not None else ''
        result.append({'chunk_id': chunk['id'], 'document_id': item['id'],
                       'label': f"{item['root']}/{item['relative']}{page}",
                       'excerpt': chunk['text'][:700]})
    return result
