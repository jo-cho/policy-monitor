import csv
import io


def collection_rows(collection, results):
    rows = []
    for post in collection['posts']:
        result = results.get(post['id'])
        rows.append({'ID': post['id'], '유형': result.get('category', post['category']) if result else post['category'],
                     '제목': post['title'], '발행일': post['published_at'], '본문 상태': post['status'],
                     '판정': result['status'] if result else '미판정',
                     '비상등': '🔴' if result and result['alert'] else '', '링크': post['url']})
    return rows


def csv_bytes(rows):
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        # 스프레드시트에서 외부 문자열이 수식으로 실행되지 않도록 처리합니다.
        writer.writerows({k: "'" + str(v) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v
                          for k, v in row.items()} for row in rows)
    return output.getvalue().encode('utf-8-sig')


def export_report(policy, collection, results):
    return {'policy_name': policy['name'], 'reference_date': policy['date'],
            'policy_profile': policy['profile'], 'policy_documents': policy['documents'],
            'policy_extraction_failures': policy['extraction_failures'],
            'search_errors': collection['search_errors'], 'web_search_calls': collection['web_search_calls'],
            'collected_at': collection['collected_at'],
            'posts': [{k: v for k, v in p.items() if k != 'text'} for p in collection['posts']],
            'results': results,
            'notice': '업로드 정책문서와의 대조 결과이며 게시물 전체·작성자의 의도에 대한 판정이 아닙니다.'}
