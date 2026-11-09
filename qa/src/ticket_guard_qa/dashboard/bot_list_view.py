"""B1 화면 데이터 · ① 수법 분류별 탐지 현황 타일 · ② 검색 · 필터 · 분류별 봇 목록 · 선택 봇 상세 · 봇 수가 늘어도 같은 구조"""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

from ticket_guard_qa.macro_bots.behavior_description import BehaviorLine, describe_behavior
from ticket_guard_qa.macro_bots.bot_catalog import BOT_CATEGORIES, BROWSER_TRAFFIC, BotCategory, BotTypeInfo
from ticket_guard_qa.macro_bots.bot_profiles import BotProfile
from ticket_guard_qa.scoring.detection_breakdown import ActorDetectionRow

FILTER_NAMES = ("category", "status", "verdict", "channel", "q")
VERDICT_FILTERS = {"fail": "FAIL", "pass": "PASS", "none": "결과 없음"}
CHANNEL_FILTERS = {"http": "HTTP", "browser": "브라우저"}
STATUS_FILTERS = {"active": "사용 중", "review": "검증 중", "draft": "작성 중", "locked": "평가 전용"}


@dataclass(frozen=True)
class BotListItem:
    profile: BotProfile
    detection_row: ActorDetectionRow | None  # None = 판정 정확도 시험 결과 없음

    @property
    def info(self) -> BotTypeInfo:
        return self.profile.type_info

    @property
    def behavior_lines(self) -> list[BehaviorLine]:
        return describe_behavior(self.profile.behavior)

    @property
    def has_result(self) -> bool:
        return bool(self.detection_row and self.detection_row.session_count)

    @property
    def verdict_key(self) -> str:
        """fail · pass · none · 목표 없는 결과는 none"""
        if not self.has_result or self.detection_row.is_meeting_target is None:
            return "none"
        return "pass" if self.detection_row.is_meeting_target else "fail"

    @property
    def channel_key(self) -> str:
        return "browser" if self.info.traffic_channel == BROWSER_TRAFFIC else "http"

    def matches_search(self, query: str) -> bool:
        text = " ".join([self.info.display_name, self.info.purpose, self.info.category.title, *self.info.detection_signals])
        return query.lower() in text.lower()


@dataclass(frozen=True)
class CategoryTile:
    category: BotCategory
    items: list[BotListItem]

    @property
    def is_baseline(self) -> bool:
        return self.category.category_id == "baseline"

    @property
    def measured_items(self) -> list[BotListItem]:
        return [item for item in self.items if item.has_result]

    @property
    def rate_percent(self) -> float | None:
        """분류 합산 · 봇 판정 세션 수 / 전체 세션 수 · 기준 트래픽은 곧 오탐률"""
        rows = [item.detection_row for item in self.measured_items]
        session_count = sum(row.session_count for row in rows)
        return sum(row.detected_count for row in rows) / session_count * 100 if session_count else None

    @property
    def fail_count(self) -> int:
        return sum(1 for item in self.items if item.verdict_key == "fail")

    @property
    def unmeasured_count(self) -> int:
        return len(self.items) - len(self.measured_items)


@dataclass(frozen=True)
class CategoryGroup:
    category: BotCategory
    items: list[BotListItem]


@dataclass(frozen=True)
class FilterOption:
    value: str
    title: str
    count: int
    url: str
    is_selected: bool


@dataclass(frozen=True)
class BotListView:
    tiles: list[CategoryTile]
    groups: list[CategoryGroup]
    selected: BotListItem | None
    filters: dict[str, str]
    status_options: list[FilterOption]
    verdict_options: list[FilterOption]
    channel_options: list[FilterOption]
    total_count: int
    shown_count: int
    build_url: Callable[..., str]


def make_url_builder(filters: Mapping[str, str]) -> Callable[..., str]:
    """현재 필터 유지 + 바꿀 값만 · 빈 값 = 필터 해제"""
    def build_url(**changes: str) -> str:
        merged = {**filters, **changes}
        query = {name: value for name, value in merged.items() if value}
        return f"/bots?{urlencode(query)}" if query else "/bots"
    return build_url


def read_filters(query_params: Mapping[str, str]) -> dict[str, str]:
    return {name: str(query_params.get(name, "")).strip() for name in FILTER_NAMES}


def is_shown(item: BotListItem, filters: dict[str, str], skip: str = "") -> bool:
    checks = {
        "category": lambda value: item.info.category_id == value,
        "status": lambda value: item.info.status_key == value,
        "verdict": lambda value: item.verdict_key == value,
        "channel": lambda value: item.channel_key == value,
        "q": item.matches_search,
    }
    return all(check(filters[name]) for name, check in checks.items() if filters[name] and name != skip)


def build_options(items: list[BotListItem], filters: dict[str, str], name: str, titles: dict[str, str],
                  read_key: Callable[[BotListItem], str], build_url: Callable[..., str]) -> list[FilterOption]:
    """선택지마다 다른 필터 적용 후 개수 · 0개도 표시 · 같은 칸 다시 누르면 해제"""
    candidates = [item for item in items if is_shown(item, filters, skip=name)]
    options = []
    for value, title in titles.items():
        is_selected = filters[name] == value
        options.append(FilterOption(value, title, sum(1 for item in candidates if read_key(item) == value),
                                    build_url(**{name: "" if is_selected else value, "bot": ""}), is_selected))
    return options


def build_bot_list_view(items: list[BotListItem], query_params: Mapping[str, str]) -> BotListView:
    filters = read_filters(query_params)
    build_url = make_url_builder(filters)
    tiles = [CategoryTile(category, [item for item in items if item.info.category_id == category.category_id])
             for category in BOT_CATEGORIES]
    shown_items = [item for item in items if is_shown(item, filters)]
    groups = [CategoryGroup(tile.category, [item for item in shown_items if item.info.category_id == tile.category.category_id])
              for tile in tiles]
    selected_slug = str(query_params.get("bot", ""))
    selected = next((item for item in shown_items if item.info.slug == selected_slug), shown_items[0] if shown_items else None)
    return BotListView(
        tiles=[tile for tile in tiles if tile.items],
        groups=[group for group in groups if group.items],
        selected=selected,
        filters=filters,
        status_options=build_options(items, filters, "status", STATUS_FILTERS, lambda item: item.info.status_key, build_url),
        verdict_options=build_options(items, filters, "verdict", VERDICT_FILTERS, lambda item: item.verdict_key, build_url),
        channel_options=build_options(items, filters, "channel", CHANNEL_FILTERS, lambda item: item.channel_key, build_url),
        total_count=len(items),
        shown_count=len(shown_items),
        build_url=build_url,
    )
