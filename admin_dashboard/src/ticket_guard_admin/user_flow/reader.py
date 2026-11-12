"""
[홍석환] 검증 후 공개된 사용자 흐름 지표 조회
기존 MongoDB 설정으로 공개 뷰만 읽고 동일 버전의 최신값·시계열을 반환한다.
"""
from pymongo import MongoClient
from pymongo.errors import ConfigurationError, InvalidURI, OperationFailure, PyMongoError

from .contracts import FlowError, invalid, scope_key, validate

READ_TIMEOUT_MS = 3000


class PublishedFlowReader:
    def __init__(self, uri):
        self.uri = uri

    def read(self, scope='all'):
        scope = scope_key(scope)
        if not self.uri:
            raise FlowError('connection_config', 'DB 조회 실패 · 기존 관리자 MongoDB 연결 설정을 확인해 주세요.')
        try:
            with MongoClient(self.uri, serverSelectionTimeoutMS=READ_TIMEOUT_MS,
                             connectTimeoutMS=READ_TIMEOUT_MS, socketTimeoutMS=READ_TIMEOUT_MS,
                             tz_aware=True, appname='ticketguard-admin-published-reader') as client:
                database = client.get_default_database()
                for _ in range(3):
                    current = database.flow_read_current.find_one({'_id': scope}, max_time_ms=READ_TIMEOUT_MS)
                    if current is None:
                        code = 'no_publication' if scope == 'all' else 'scope_not_found'
                        message = ('공개 결과 없음 · 연결 대상 DB의 공개 뷰와 Spark의 검증 공개 여부를 확인해 주세요.'
                                   if scope == 'all' else '조회 범위 없음 · 해당 조합의 공개 지표가 없습니다.')
                        raise FlowError(code, message)
                    series = database.flow_read_series.find_one({'_id': scope}, max_time_ms=READ_TIMEOUT_MS)
                    if not isinstance(current, dict) or (series is not None and not isinstance(series, dict)):
                        invalid()
                    versions = []
                    if series is not None:
                        for wrapper, key in ((current, '_id'), (series, 'version')):
                            if not isinstance(wrapper.get('version'), str) or not isinstance(wrapper.get('result'), dict) or not isinstance(wrapper['result'].get(key), str):
                                invalid()
                            versions.extend((wrapper['version'], wrapper['result'][key]))
                    if series is not None and len(set(versions)) == 1:
                        metrics, history = validate(current, series, scope)
                        choices = []
                        for item in database.flow_read_current.find({}, {'_id': 1}).limit(101).max_time_ms(READ_TIMEOUT_MS):
                            key = item.get('_id')
                            if not isinstance(key, str):
                                invalid()
                            try:
                                normalized = scope_key(key)
                            except FlowError:
                                invalid()
                            if normalized != key:
                                invalid()
                            choices.append(key)
                        return {'metrics': metrics, 'history': history, 'version': current['version'],
                                'published_at': current['result']['publishedAt'], 'scopes': sorted(set(choices) | {scope}),
                                'database': database.name}
                raise FlowError('version_mismatch', '공개 버전 불일치 · 최신 지표와 시계열을 같은 버전으로 읽지 못했습니다. 새로고침해 주세요.')
        except FlowError:
            raise
        except OperationFailure as exc:
            if exc.code == 13:
                raise FlowError('permission_denied', '읽기 권한 부족 · 기존 관리자 계정의 공개 뷰 조회 권한을 확인해 주세요.') from None
            if exc.code == 18:
                raise FlowError('authentication_failed', 'DB 인증 실패 · 기존 관리자 계정과 인증 DB 설정을 확인해 주세요.') from None
            raise FlowError('query_failed', 'DB 조회 실패 · 공개 뷰의 배포 상태와 조회 가능 여부를 확인해 주세요.') from None
        except (ConfigurationError, InvalidURI, ValueError):
            raise FlowError('connection_config', 'DB 조회 실패 · 기존 관리자 연결 주소와 대상 DB 설정을 확인해 주세요.') from None
        except PyMongoError:
            raise FlowError('connection_failed', 'DB 연결 실패 · MongoDB 실행 상태와 기존 네트워크 연결을 확인해 주세요.') from None
