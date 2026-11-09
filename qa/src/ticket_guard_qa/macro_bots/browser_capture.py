"""봇 C(브라우저 자동화) 화면 캡처 · B3 · Mock = 행동 값으로 만든 단계별 프레임 · Live = 브라우저 봇이 저장한 프레임 목록"""
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from ticket_guard_qa.domain.models import BrowserCaptureFrame, SessionBehavior

CAPTURE_STEPS: tuple[str, ...] = ("공연 상세", "대기열", "보안문자", "좌석 선택", "예매 확정")
CAPTURE_FOLDER_NAME = "captures"  # 보고서 폴더 아래 · Run별 frames.json + 이미지
CAPTURE_INDEX_FILE_NAME = "frames.json"
CAPTURE_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")
SCREEN_WIDTH = 160  # 프레임 좌표계 · B3 축소 화면
SCREEN_HEIGHT = 100
QUEUE_WAIT_MS = 12000  # 시스템 기본 대기열 대기


@dataclass(frozen=True)
class CaptureFrame:
    step: str
    elapsed_ms: float  # 오픈(T0) 기준
    click_x: int | None  # SCREEN_WIDTH × SCREEN_HEIGHT 좌표 · None = 클릭 없음
    click_y: int | None
    image_file_name: str | None = None  # Live 스크린샷 · Mock은 None


def build_mock_capture_frames(behavior: SessionBehavior, random_seed: int) -> list[CaptureFrame]:
    """같은 행동 값 · 시드 = 같은 프레임"""
    random_source = random.Random(f"capture-{random_seed}")
    elapsed_ms = float(behavior.entry_delay_after_open_ms)
    frames = []
    for step in CAPTURE_STEPS:
        frames.append(CaptureFrame(step, round(elapsed_ms, 1),
                                   random_source.randint(20, SCREEN_WIDTH - 20), random_source.randint(30, SCREEN_HEIGHT - 12)))
        step_ms = QUEUE_WAIT_MS if step == "대기열" else max(random_source.gauss(
            behavior.click_interval_mean_ms, behavior.click_interval_deviation_ms), 0.0)
        elapsed_ms += step_ms
    return frames


def save_capture_frames(report_output_dir: Path, run_id: str, frames: list[CaptureFrame]) -> Path:
    """브라우저 봇이 Run 중 호출 · 이미지는 같은 폴더"""
    capture_dir = report_output_dir / CAPTURE_FOLDER_NAME / run_id
    capture_dir.mkdir(parents=True, exist_ok=True)
    index_path = capture_dir / CAPTURE_INDEX_FILE_NAME
    index_path.write_text(json.dumps([asdict(frame) for frame in frames], ensure_ascii=False), encoding="utf-8")
    return index_path


def save_browser_capture_frames(report_output_dir: Path, run_id: str, frames: list[BrowserCaptureFrame]) -> Path:
    """Live 브라우저 세션 화면 → 이미지 파일 + frames.json · 클릭 위치는 B3 축소 화면 좌표로"""
    capture_dir = report_output_dir / CAPTURE_FOLDER_NAME / run_id
    capture_dir.mkdir(parents=True, exist_ok=True)
    saved_frames = []
    for index, frame in enumerate(frames, start=1):
        image_file_name = None
        if frame.image_png:
            image_file_name = f"frame-{index:02d}.png"
            (capture_dir / image_file_name).write_bytes(frame.image_png)
        click_x = round(frame.click_ratio_x * SCREEN_WIDTH) if frame.click_ratio_x is not None else None
        click_y = round(frame.click_ratio_y * SCREEN_HEIGHT) if frame.click_ratio_y is not None else None
        saved_frames.append(CaptureFrame(frame.step, frame.elapsed_ms, click_x, click_y, image_file_name))
    return save_capture_frames(report_output_dir, run_id, saved_frames)


def load_capture_frames(report_output_dir: Path, run_id: str) -> list[CaptureFrame]:
    index_path = report_output_dir / CAPTURE_FOLDER_NAME / run_id / CAPTURE_INDEX_FILE_NAME
    if not index_path.exists():
        return []
    return [CaptureFrame(**raw_frame) for raw_frame in json.loads(index_path.read_text(encoding="utf-8"))]
