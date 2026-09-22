import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
from engine import Claim, Comparison, PolicyProfile, prepare_policy, finalize_comparison, evaluate_post, comparison_schema
from passages import prepare_passages


def scenario():
    pages = [{'id': 'D1P1', 'text': '이 지원사업의 지급액은 신청자 1인당 10만원이며 2026년 1월 1일부터 시행한다.',
              'file_name': 'policy.pdf', 'page_number': 1}]
    model_pages, catalog = prepare_passages(pages)
    policy = {'accepted': True, 'name': '지원사업', 'date': '2026-09-22', 'pages': pages,
              'catalog': catalog, 'model_pages': model_pages, 'extraction_failures': [],
              'profile': {'aliases': [], 'date_assessment': '부합'}, 'documents': []}
    post = {'id': 'A1', 'url': 'https://example.com/post', 'title': '지원사업 소개', 'category': '블로그',
            'status': '본문 확보', 'text': '이 지원사업의 지급액은 모든 신청자에게 100만원이다. 지금 바로 신청하세요.',
            'published_at': '2026-09-10', 'truncated': False, 'reason': ''}
    _, article_catalog = prepare_passages([{'id': post['id'], 'text': post['text']}])
    claim = dict(claim='지원금은 100만원이다.', article_passage_id='A1_P1', policy_passage_ids=['D1P1_P1'],
                 verdict='거짓', confidence=93, asserted_as_fact=True, scope_verified=True,
                 direct_contradiction=True, explanation='정책은 10만원으로 정한다.', correction='지급액은 10만원이다.')
    return policy, post, article_catalog, claim


class ComparisonTests(unittest.TestCase):
    def run_case(self, **changes):
        policy, post, catalog, claim = scenario()
        claim.update(changes)
        raw = Comparison(relevant=True, domestic_context=True, category='블로그', explanation='검토 완료',
                         claims=[Claim(**claim)], limitations=[])
        return finalize_comparison(raw, post, policy, catalog)

    def test_direct_contradiction_triggers_alert_with_exact_quotes(self):
        result = self.run_case()
        self.assertTrue(result['alert'])
        self.assertIn('100만원', result['claims'][0]['article_quote'])
        self.assertIn('10만원', result['claims'][0]['policy_evidence'][0]['quote'])
        self.assertEqual(result['claims'][0]['policy_evidence'][0]['page_number'], 1)

    def test_no_policy_evidence_never_red(self):
        result = self.run_case(policy_passage_ids=[])
        self.assertFalse(result['alert'])
        self.assertEqual(result['claims'][0]['verdict'], '불확실')
        self.assertIsNone(result['claims'][0]['confidence'])

    def test_old_policy_or_unverified_scope_never_red(self):
        self.assertFalse(self.run_case(scope_verified=False)['alert'])

    def test_quoted_debunked_claim_is_not_authors_falsehood(self):
        result = self.run_case(asserted_as_fact=False)
        self.assertFalse(result['alert'])
        self.assertEqual(result['status'], '판정 대상 없음')

    def test_no_direct_contradiction_never_red(self):
        self.assertFalse(self.run_case(direct_contradiction=False)['alert'])

    def test_bad_ids_fail_closed(self):
        for changes in [{'article_passage_id': 'A99_P1'}, {'policy_passage_ids': ['D99P1_P1']}]:
            result = self.run_case(**changes)
            self.assertFalse(result['alert'])
            self.assertEqual(result['claims'][0]['verdict'], '불확실')

    def test_true_and_uncertain_states(self):
        self.assertEqual(self.run_case(verdict='참', direct_contradiction=False)['status'], '🟢 검토한 주장 일치')
        self.assertEqual(self.run_case(verdict='불확실', policy_passage_ids=[])['status'], '🟡 불확실')

    def test_off_topic_not_scored(self):
        policy, post, catalog, claim = scenario()
        raw = Comparison(relevant=False, domestic_context=True, category='블로그', explanation='다른 정책',
                         claims=[Claim(**claim)], limitations=[])
        self.assertEqual(finalize_comparison(raw, post, policy, catalog)['status'], '대상 제외')

    def test_unavailable_body_never_calls_judge(self):
        policy, post, _, _ = scenario()
        post.update(status='본문 미확보', text='')
        client = Mock()
        result = evaluate_post(client, post, policy)
        self.assertFalse(result['alert'])
        client.responses.parse.assert_not_called()

    def test_dynamic_schema_restricts_article_and_policy_ids(self):
        policy, _, article, claim = scenario()
        schema = comparison_schema(article, policy['catalog'])
        data = dict(relevant=True, domestic_context=True, category='블로그', explanation='', claims=[claim], limitations=[])
        schema(**data)
        data['claims'][0]['article_passage_id'] = 'D1P1_P1'
        with self.assertRaises(ValueError):
            schema(**data)

    def test_judge_has_no_search_tool_and_uses_reference_document(self):
        policy, post, catalog, claim = scenario()
        client = Mock()
        client.responses.parse.return_value.model_dump.return_value = {'status': 'completed'}
        client.responses.parse.return_value.output_parsed = Comparison(relevant=True, domestic_context=True,
            category='블로그', explanation='대조 완료', claims=[Claim(**claim)], limitations=[])
        result = evaluate_post(client, post, policy)
        self.assertTrue(result['alert'])
        self.assertNotIn('tools', client.responses.parse.call_args.kwargs)
        client.responses.create.assert_not_called()

    def test_non_policy_document_is_rejected(self):
        policy, _, _, _ = scenario()
        client = Mock()
        client.responses.parse.return_value.model_dump.return_value = {'status': 'completed'}
        client.responses.parse.return_value.output_parsed = PolicyProfile(is_policy_document=False,
            matches_policy=True, policy_name='지원사업', issuer='블로그', aliases=[], summary='단순 의견문',
            effective_dates=[], date_assessment='확인 불가', supporting_passage_ids=['D1P1_P1'], warnings=[])
        with patch('engine.extract_pdfs', return_value=(policy['pages'], [], 1)):
            result = prepare_policy(client, [{'name': 'opinion.pdf', 'data': b''}], '지원사업', '2026-09-22')
        self.assertFalse(result['accepted'])
