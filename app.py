import hmac
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from openai import OpenAI
from collector import CATEGORIES, collect_posts
from engine import prepare_policy, evaluate_post
from pdf_support import PDFInputError
from reporting import collection_rows, csv_bytes, export_report

st.set_page_config(page_title='정책 비상등', page_icon='🚨', layout='wide')


def setting(name, default=''):
    try:
        return st.secrets.get(name, os.getenv(name, default))
    except FileNotFoundError:
        return os.getenv(name, default)


def clear_run():
    for name in ('policy', 'collection', 'results', 'chosen_posts'):
        st.session_state.pop(name, None)


def clear_key():
    st.session_state.api_key = ''


def show_error(exc, stage):
    messages = {'AuthenticationError': 'API 키를 확인해 주세요.',
                'RateLimitError': 'API 잔액·사용 한도·요청 제한을 확인해 주세요.',
                'APITimeoutError': 'API 응답 시간이 초과되었습니다.',
                'APIConnectionError': 'API 연결에 실패했습니다.',
                'BadRequestError': 'API 모델 및 요청 설정을 확인해 주세요.'}
    st.error(messages.get(type(exc).__name__, '작업을 완료하지 못했습니다. 아래 진단을 확인해 주세요.'))
    st.json({'단계': stage, '오류 유형': type(exc).__name__})


st.caption('POLICY WATCH / 정책문서 기반 공개 게시물 검토')
st.title('🚨 정책 비상등')
st.write('정책문서를 기준으로 기사·블로그·SNS의 주장을 대조하고, 문서와 모순되는 정보를 찾아냅니다.')

password = setting('APP_PASSWORD')
if password:
    entry = st.text_input('앱 이용 비밀번호', type='password')
    if not hmac.compare_digest(entry.encode(), password.encode()):
        st.info('비밀번호를 입력해 주세요.')
        st.stop()

with st.sidebar:
    st.subheader('API 설정')
    key = st.text_input('OpenAI API 키', type='password', key='api_key').strip()
    st.button('키 지우기', on_click=clear_key)
    st.caption('키는 현재 세션에서 사용합니다. 키의 계정에 API 사용료가 발생합니다.')
    st.subheader('수집 범위')
    categories = st.multiselect('자료 유형', CATEGORIES, default=CATEGORIES,
                                key='categories', on_change=clear_run)
    limit = st.slider('최대 수집 개수', 5, 50, 20, step=5, key='limit', on_change=clear_run)
    st.caption('유형마다 2회 검색하고 중복 URL을 정리합니다. 검색 노출과 접근 가능 여부에 따라 실제 개수는 더 적을 수 있습니다.')
    st.divider()
    st.write('🔴 정책문서가 직접 반박하는 주장 포함\n\n🟡 근거·시점·조건 확인 부족\n\n🟢 검토한 사실 주장들이 문서와 일치')
    st.caption('녹색은 게시물 전체의 무오류 인증이 아닙니다. 비상등도 작성자의 고의나 의도를 뜻하지 않습니다.')

st.subheader('1. 기준 정책문서를 넣으세요')
files = st.file_uploader('정책 공고·법령·지침·설명서 PDF', type=['pdf'], accept_multiple_files=True,
                         key='policy_files', on_change=clear_run)
st.caption('PDF 최대 5개 · 파일당 10MB · 합계 100쪽/추출 본문 15만 자. 본문을 복사할 수 없는 스캔본은 OCR 후 올려 주세요.')
left, right = st.columns([2, 1])
name = left.text_input('정책명', placeholder='예: 청년월세 지원사업', max_chars=160,
                       key='policy_name', on_change=clear_run)
date = right.date_input('정책 기준일', value=datetime.now(ZoneInfo('Asia/Seoul')).date(),
                        key='policy_date', on_change=clear_run)
st.caption('기준일은 정책의 적용 내용을 비교할 날짜입니다. 게시물 검색 시작일이 아닙니다. 발표일과 시행일이 다르면 적용하려는 기준일을 입력하세요.')
st.caption('정책 본문·정책명·기준일과 수집한 게시물 본문을 OpenAI API로 전송합니다. PDF 진본 여부는 별도로 인증하지 않습니다.')

if st.button('정책문서 확인 후 공개 자료 수집', type='primary'):
    clear_run()
    if not files or not name.strip():
        st.warning('정책 PDF와 정책명을 입력해 주세요.')
    elif not categories:
        st.warning('수집할 자료 유형을 선택해 주세요.')
    elif not key:
        st.warning('사이드바에 API 키를 입력해 주세요.')
    else:
        stage = '정책문서 확인'
        try:
            with st.status('정책문서 확인 및 자료 수집 중…', expanded=True) as status:
                message = st.empty()
                with OpenAI(api_key=key, timeout=100, max_retries=1) as client:
                    policy = prepare_policy(client, [{'name': f.name, 'data': f.getvalue()} for f in files],
                                            name, date.isoformat(), setting('OPENAI_MODEL', 'gpt-4.1'))
                    st.session_state.policy = policy
                    if policy['accepted']:
                        stage = '공개 게시물 검색 및 본문 수집'
                        st.session_state.collection = collect_posts(client, policy, limit, categories,
                            setting('OPENAI_MODEL', 'gpt-4.1'), progress=message.write)
                        st.session_state.results = {}
                        status.update(label='수집 완료 — 아래 목록에서 검토할 자료를 선택하세요.', state='complete')
                    else:
                        status.update(label='기준 정책문서를 다시 확인해 주세요.', state='error')
        except PDFInputError as exc:
            st.error(str(exc))
        except Exception as exc:
            show_error(exc, stage)

if 'policy' in st.session_state:
    policy = st.session_state.policy
    profile = policy['profile']
    with st.expander('기준 정책문서 확인 결과', expanded=not policy['accepted']):
        st.text(f"정책: {profile['policy_name']} · 발행기관: {profile['issuer']}")
        st.text(profile['summary'])
        st.caption(f"정책문서로 판단: {'예' if profile['is_policy_document'] else '아니오'} · 입력 정책명과 일치: {'예' if profile['matches_policy'] else '아니오'}")
        st.text(f"기준일 적합성: {profile['date_assessment']} · 문서 내 적용일: {', '.join(profile['effective_dates']) or '확인 불가'}")
        for warning in profile['warnings']:
            st.text('• ' + warning)
        indexed = {p['id']: p for p in policy['pages']}
        for pid in profile['supporting_passage_ids']:
            if pid in policy['catalog']:
                entry = policy['catalog'][pid]
                page = indexed[entry['source_id']]
                st.caption(f"{page['file_name']} · {page['page_number']}쪽")
                st.text(entry['quote'])
        for error in policy['extraction_failures']:
            st.warning(f"{error['file_name']} · {error['page_number']}쪽: {error['reason']}")
    if not policy['accepted']:
        st.warning('정책문서 여부·입력 정책과의 일치·기준일을 확인하지 못해 수집을 시작하지 않았습니다. 확인 결과를 보고 자료나 입력값을 수정해 주세요.')
    elif profile['date_assessment'] == '확인 불가':
        st.info('문서만으로 기준일 적용 여부를 확정하지 못했습니다. 게시물별 판정에서도 적용 시점을 별도로 검토합니다.')

if 'collection' in st.session_state:
    policy = st.session_state.policy
    collection = st.session_state.collection
    results = st.session_state.results
    posts = collection['posts']
    st.divider()
    st.subheader('2. 수집 목록을 확인하세요')
    a, b, c = st.columns(3)
    a.metric('수집한 링크', len(posts))
    b.metric('본문 확보', sum(p['status'] == '본문 확보' for p in posts))
    c.metric('웹 검색 도구 호출', collection['web_search_calls'])
    for message in collection['search_errors']:
        st.warning(message)
    st.caption('발행일은 웹페이지 메타데이터 기준입니다. 유형은 검색·도메인 분류이며 판정 단계에서 내용을 재확인합니다. 로그인·동적 SNS는 제목과 링크만 확보될 수 있습니다.')
    st.dataframe(collection_rows(collection, results), hide_index=True, use_container_width=True,
                 column_config={'링크': st.column_config.LinkColumn('원문 링크')})
    with st.expander('수집한 본문 및 접근 실패 내역'):
        for post in posts:
            st.text(f"[{post['id']}] {post['title']} — {post['status']}")
            st.link_button('원문 열기', post['url'])
            if post['reason']:
                st.caption(post['reason'])
            if post.get('text'):
                st.text(post['text'])
                if post['truncated']:
                    st.caption('앞부분 18,000자까지 표시·검토합니다.')
    if not posts:
        st.info('검색된 대상 자료가 없습니다. 정책명·문서·검색 유형을 확인해 주세요.')
    else:
        st.subheader('3. 정책문서와 대조하세요')
        eligible = [p['id'] for p in posts if p['status'] == '본문 확보']
        titles = {p['id']: p['title'] for p in posts}
        selected = st.multiselect('판정할 자료', eligible, default=eligible, key='chosen_posts',
                                  format_func=lambda item: f'[{item}] {titles[item]}')
        st.caption('자료당 1회 LLM 비교 요청을 보냅니다. 완료된 결과는 재사용하고, 오류가 난 자료는 다시 시도합니다. 한 글에서 최대 12개 핵심 사실 주장을 검토합니다.')
        if st.button('선택한 자료 일괄 판정', type='primary', disabled=not selected):
            if not key:
                st.warning('API 키를 입력해 주세요.')
            else:
                meter = st.progress(0)
                label = st.empty()
                try:
                    with OpenAI(api_key=key, timeout=100, max_retries=1) as client:
                        for index, pid in enumerate(selected, 1):
                            if pid not in results or results[pid]['status'] == '분석 오류':
                                post = next(p for p in posts if p['id'] == pid)
                                label.text(f'{index}/{len(selected)} 검토 중: {post["title"]}')
                                try:
                                    results[pid] = evaluate_post(client, post, policy, setting('OPENAI_MODEL', 'gpt-4.1'))
                                except Exception as exc:
                                    results[pid] = {'status': '분석 오류', 'alert': False, 'claims': [],
                                        'summary': f'모델 비교 실패 ({type(exc).__name__}). 다시 시도할 수 있습니다.', 'limitations': []}
                            meter.progress(index / len(selected))
                    st.session_state.results = results
                    st.rerun()
                except Exception as exc:
                    show_error(exc, '게시물 일괄 판정')
        if results:
            st.subheader('검토 결과')
            alerts = [pid for pid, result in results.items() if result['alert']]
            if alerts:
                st.error(f'🚨 비상등: {len(alerts)}개 자료에서 정책문서가 직접 반박하는 주장을 발견했습니다.')
            else:
                st.info('현재 완료된 검토에서 비상등은 없습니다. 미판정·불확실·분석 오류 자료는 별도로 확인하세요.')
            for post in sorted(posts, key=lambda p: not results.get(p['id'], {}).get('alert', False)):
                result = results.get(post['id'])
                if not result:
                    continue
                with st.expander(f"{result['status']} · [{post['id']}] {post['title']}", expanded=result['alert']):
                    st.link_button('게시물 원문', post['url'])
                    st.text(result['summary'])
                    for claim in result['claims']:
                        st.divider()
                        st.text(f"{claim['verdict']} · {claim['claim']}")
                        if claim['confidence'] is not None:
                            st.caption(f"LLM 자기평가 신뢰도: {claim['confidence']}% — 검증된 정답 확률이 아닙니다.")
                        x, y = st.columns(2)
                        with x:
                            st.caption('수집한 게시물의 실제 구절')
                            st.text(claim['article_quote'])
                        with y:
                            st.caption('기준 정책문서의 실제 구절')
                            for evidence in claim['policy_evidence']:
                                st.text(evidence['quote'])
                                st.caption(f"{evidence['file_name']} · 파일의 {evidence['page_number']}번째 페이지")
                            if not claim['policy_evidence']:
                                st.caption('직접 대응하는 정책 근거 없음')
                        st.text(claim['explanation'])
                        if claim['correction']:
                            st.success('정책문서 기준 정정: ' + claim['correction'])
                        for note in claim['validation_notes']:
                            st.caption(note)
                    for note in result['limitations']:
                        st.text('• ' + note)
    st.download_button('수집·판정 목록 CSV', csv_bytes(collection_rows(collection, results)),
                        file_name='policy-monitor-list.csv', mime='text/csv')
    st.download_button('근거 포함 보고서 JSON', json.dumps(export_report(policy, collection, results), ensure_ascii=False, indent=2),
                        file_name='policy-monitor-report.json', mime='application/json')
