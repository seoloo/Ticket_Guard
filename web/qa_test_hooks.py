"""QA 테스트 훅 · 시험 환경 전용 · 켜는 조건은 config/settings.py · 값이 비어 있으면 꺼짐 (Issue #6)"""
import re
import secrets
from django.conf import settings

TEST_ACCOUNT_PATTERN = re.compile(r'qa-user-(\d{4})')


def is_test_account_login(username, password):
    """qa-user-0001 ~ qa-user-{QA_TEST_ACCOUNT_COUNT} · 공통 비밀번호"""
    if not settings.QA_TEST_ACCOUNT_COUNT or not settings.QA_TEST_ACCOUNT_PASSWORD:
        return False
    match = TEST_ACCOUNT_PATTERN.fullmatch(username)
    if not match or not 1 <= int(match.group(1)) <= settings.QA_TEST_ACCOUNT_COUNT:
        return False
    return secrets.compare_digest(password.encode(), settings.QA_TEST_ACCOUNT_PASSWORD.encode())
