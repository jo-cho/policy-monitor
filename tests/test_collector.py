import unittest
from unittest.mock import Mock, patch
from contextlib import contextmanager
from email.message import Message
from collector import canonical_url, candidate_sources, fetch_article, collect_posts
from network import open_public_page
from reporting import csv_bytes


class CollectorTests(unittest.TestCase):
    def test_url_dedup_and_tracking(self):
        self.assertEqual(canonical_url('https://example.com/post?id=1&utm_source=x#top'), 'https://example.com/post?id=1')
        self.assertEqual(canonical_url('https://m.blog.naver.com/a/123'), 'https://blog.naver.com/a/123')
        self.assertIsNone(canonical_url('http://127.0.0.1/path'))
        self.assertIsNone(canonical_url('file:///etc/passwd'))

    def test_nullable_metadata_and_generated_link_exclusion(self):
        response = Mock()
        response.model_dump.return_value = {'output': [{'action': {'sources': None}, 'content': None},
            {'content': [{'text': 'https://example.com/fake', 'annotations': []}]},
            {'action': {'sources': [{'url': 'https://law.go.kr/policy'}, {'url': 'https://x.com/u/status/1'}]}}]}
        result = candidate_sources(response, '기사')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['category'], 'SNS')

    def test_private_dns_destination_blocked(self):
        with patch('network.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('10.0.0.1', 443))]), patch('network.http.client.HTTPSConnection') as connection:
            with self.assertRaises(ValueError):
                with open_public_page('https://public.example.com', [], True):
                    pass
            connection.assert_not_called()

    def test_searches_all_categories_and_keeps_failed_sources(self):
        client = Mock()
        response = Mock()
        response.model_dump.return_value = {'status': 'completed', 'output': [
            {'type': 'web_search_call', 'action': {'sources': [{'url': 'https://example.com/a', 'title': '정책 글'}]}}]}
        client.responses.create.return_value = response
        policy = {'accepted': True, 'name': '지원사업', 'date': '2026-09-22', 'profile': {'aliases': []}}
        with patch('collector.fetch_article', side_effect=lambda s: {**s, 'status': '본문 미확보', 'reason': '로그인 필요', 'text': ''}):
            result = collect_posts(client, policy, limit=5)
        self.assertEqual(client.responses.create.call_count, 6)
        self.assertEqual(len(result['posts']), 1)
        self.assertEqual(result['posts'][0]['status'], '본문 미확보')
        self.assertEqual(result['web_search_calls'], 6)

    def test_profile_rejection_prevents_collection(self):
        client = Mock()
        with self.assertRaises(ValueError):
            collect_posts(client, {'accepted': False})
        client.responses.create.assert_not_called()

    def test_real_html_extractor_gets_korean_body(self):
        paragraph = '청년 지원사업의 신청 자격과 지급 금액을 안내합니다. 신청자는 소득 조건을 확인하고 신청서를 제출해야 합니다. '
        html = ('<html lang="ko"><head><title>지원사업 안내</title></head><body><article><h1>지원사업 안내</h1>' + ''.join('<p>'+paragraph+'</p>' for _ in range(5)) + '</article></body></html>').encode()
        headers = Message()
        headers['Content-Type'] = 'text/html; charset=utf-8'
        response = Mock(headers=headers)
        response.read.return_value = html
        @contextmanager
        def fake_open(*args):
            yield response, 'https://example.com/post'
        with patch('collector.open_public_page', fake_open):
            result = fetch_article({'url': 'https://example.com/post', 'title': '제목', 'id': 'A1', 'category': '기사'})
        self.assertEqual(result['status'], '본문 확보')
        self.assertIn('신청 자격', result['text'])

    def test_csv_neutralizes_formula(self):
        data = csv_bytes([{'제목': '=HYPERLINK("x")'}]).decode('utf-8-sig')
        self.assertIn("'=HYPERLINK", data)
