def prepare_passages(pages):
    model_pages, catalog = [], {}
    for page in pages:
        body = page['text']
        passages = []
        start = 0
        while start < len(body):
            end = min(start + 450, len(body))
            if 0 < len(body) - end < 15:
                end = len(body)
            elif end < len(body):
                # 문장·단어 경계에서 자르되 원문의 문자를 수정하지 않습니다.
                boundary = max(body.rfind(mark, start + 200, end) for mark in ('. ', '? ', '! ', ' '))
                if boundary >= start + 200:
                    end = boundary + 1
            text = body[start:end]
            if len(text.strip()) >= 15:
                pid = f"{page['id']}_P{len(passages)+1}"
                passages.append({'passage_id': pid, 'text': text})
                catalog[pid] = {'source_id': page['id'], 'quote': text}
            start = end
        model_pages.append({**{k: v for k, v in page.items() if k != 'text'}, 'passages': passages})
    return model_pages, catalog

