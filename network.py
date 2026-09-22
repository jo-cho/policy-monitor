import re
import ipaddress
import socket
import http.client
from contextlib import contextmanager
from urllib.parse import urlsplit, quote, urljoin
DOMAINS = []

def normalize_domain(value):
    value = value.strip().lower()
    if not value or any(c.isspace() for c in value) or '\\' in value:
        raise ValueError('도메인 또는 HTTP(S) 주소를 입력해 주세요.')
    parsed = urlsplit(value if '://' in value else 'https://' + value)
    host = (parsed.hostname or '').encode('idna').decode('ascii')
    if (parsed.scheme not in ('http', 'https') or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443 if parsed.scheme == 'https' else 80)
            or len(host) > 253 or '.' not in host
            or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                       for label in host.split('.'))
            or host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid'))):
        raise ValueError('공개 웹사이트의 올바른 도메인을 입력해 주세요.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise ValueError('IP 주소 대신 공개 웹사이트 도메인을 입력해 주세요.')


def allowed_url(url, domains=None, all_web=False):
    domains = DOMAINS if domains is None else domains
    try:
        if urlsplit(url).scheme not in ('http', 'https') or any(ord(c) < 32 for c in url):
            return False
        host = normalize_domain(url)
        return all_web or any(host == d or host.endswith('.' + d) for d in domains)
    except (ValueError, UnicodeError):
        return False


@contextmanager
def open_public_page(url, domains, all_web):
    # 연결할 IP를 먼저 검사하고 그 IP로 직접 연결하여 내부망 접근과 DNS 재지정을 막습니다.
    current = url
    for _ in range(6):
        if not allowed_url(current, domains, all_web):
            raise ValueError('허용되지 않은 주소')
        parsed = urlsplit(current)
        host = normalize_domain(current)
        port = 443 if parsed.scheme == 'https' else 80
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('공개 인터넷 주소가 아닙니다.')

        def connect_public(address, timeout=12, source_address=None):
            last_error = None
            for record in addresses:
                try:
                    return socket.create_connection((record[4][0], port), timeout, source_address)
                except OSError as exc:
                    last_error = exc
            raise last_error or OSError('연결 실패')

        connection_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
        connection = connection_class(host, port, timeout=12)
        connection._create_connection = connect_public
        try:
            path = quote(parsed.path or '/', safe="/%:@!$&'()*+,;=-._~")
            if parsed.query:
                path += '?' + quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
            connection.request('GET', path, headers={'User-Agent': 'PolicyEvidenceChecker/1.0', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('이동 주소 없음')
                current = urljoin(current, location)
                continue
            if response.status != 200:
                raise ValueError('본문 응답 실패')
            yield response, current
            return
        finally:
            connection.close()
    raise ValueError('리디렉션 횟수 초과')
