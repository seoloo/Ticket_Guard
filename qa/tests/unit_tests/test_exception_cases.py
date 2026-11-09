"""예외 코드 사례 · E01 ~ E22 · T1 · T2 전부 · 각 Suite의 related_codes가 사례 파일에 있음"""
from ticket_guard_qa.settings import QA_ROOT_DIR
from ticket_guard_qa.test_suites.exception_cases import find_covering_suites, load_exception_cases
from ticket_guard_qa.test_suites.suite_registry import list_suites

CASE_DATA_DIR = QA_ROOT_DIR / "case_data"
EXPECTED_CODES = [f"E{number:02d}" for number in range(1, 23)] + ["T1", "T2"]


def test_every_exception_code_has_one_case_in_order():
    assert [case.related_code for case in load_exception_cases(CASE_DATA_DIR)] == EXPECTED_CODES


def test_suite_related_codes_point_to_known_cases():
    known_codes = set(EXPECTED_CODES)
    for suite in list_suites():
        assert set(suite.related_codes) <= known_codes, suite.suite_name


def test_load_suite_covers_queue_policies():
    covering_names = {suite.suite_name for suite in find_covering_suites("T1", list_suites())}
    assert covering_names == {"load_capacity"}


def test_every_suite_has_plain_guide():
    for suite in list_suites():
        guide = suite.guide
        assert guide.purpose and guide.method and guide.pass_condition, suite.suite_name
        for text in (guide.purpose, guide.method, guide.pass_condition):
            assert not text.endswith(("요", "다", ".")), (suite.suite_name, text)  # 명사형 종결
