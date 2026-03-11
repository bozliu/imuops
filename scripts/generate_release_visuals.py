#!/usr/bin/env python3
"""Generate deterministic preview assets for release notes and README cards."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from imuops.adapters import get_adapter  # noqa: E402
from imuops.audit import run_audit  # noqa: E402
from imuops.batch import batch_audit_sessions, build_batch_report  # noqa: E402
from imuops.benchmark import run_benchmark, save_benchmark  # noqa: E402
from imuops.compare import build_compare_report  # noqa: E402
from imuops.config import load_defaults  # noqa: E402
from imuops.corruption import corrupt_session, save_corrupted_session  # noqa: E402
from imuops.reporting import build_report  # noqa: E402
from imuops.replay import run_replay, save_replay  # noqa: E402
from imuops.session import load_session, save_session  # noqa: E402
from imuops.utils import dump_json  # noqa: E402

VIEWPORT = {"width": 1400, "height": 920}
SECONDARY_FRAME_DURATIONS_MS = [1800, 2100, 2400]
HERO_SCENE_DURATION_SECONDS = 2.2
HERO_TRANSITION_SECONDS = 0.35
HERO_FPS = 10
HERO_ZOOM_FRAMES = int(HERO_SCENE_DURATION_SECONDS * HERO_FPS)
HERO_OUTPUT_SIZE = "1000x657"
HERO_CAPTURE_SEQUENCE = [
    ("report_html", "report-poster"),
    ("report_html", "report-decision"),
    ("report_html", "report-trust"),
    ("report_html", "report-issues"),
    ("compare_html", "compare-poster"),
    ("compare_html", "compare-decision"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "docs" / "artifacts",
        help="Directory where poster PNGs and GIFs should be written.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=REPO_ROOT / "output" / "release_visuals_v041",
        help="Directory for generated sample sessions and HTML artifacts.",
    )
    parser.add_argument(
        "--keep-work-dir",
        action="store_true",
        help="Keep the generated session and HTML artifacts after capture.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.work_dir.exists():
        shutil.rmtree(args.work_dir)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    artifacts = build_preview_artifacts(args.work_dir)
    capture_preview_assets(artifacts, args.out_dir)

    if not args.keep_work_dir:
        shutil.rmtree(args.work_dir)


def build_preview_artifacts(work_dir: Path) -> dict[str, Path]:
    cfg = load_defaults()
    sessions_root = work_dir / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)

    clean_dir = sessions_root / "sample_tabular_session"
    corrupt_dir = sessions_root / "sample_tabular_session_packet_loss_5"
    adapter = get_adapter("tabular")
    clean_bundle = adapter.ingest(
        REPO_ROOT / "examples" / "sample_tabular_imu.csv",
        clean_dir,
        {
            "session_id": None,
            "config": cfg,
            "adapter_config": REPO_ROOT / "examples" / "sample_tabular_config.yaml",
        },
    )
    save_session(clean_bundle, clean_dir)
    clean_audit = run_audit(clean_bundle, cfg)
    dump_json(clean_dir / "issues.json", clean_audit.to_dict())
    dump_json(clean_dir / "audit_summary.json", clean_audit.summary)
    clean_replay = run_replay(clean_bundle, "pdr", cfg)
    save_replay(clean_replay, clean_dir)
    clean_benchmark = run_benchmark(clean_bundle, "pdr", cfg)
    save_benchmark(clean_benchmark, clean_dir)

    report_html = work_dir / "report.html"
    build_report(clean_bundle, clean_audit, [clean_replay], report_html)

    corrupted_bundle, corruption_summary = corrupt_session(clean_bundle, "packet_loss_5", cfg)
    save_corrupted_session(corrupted_bundle, corruption_summary, corrupt_dir)
    corrupt_session_bundle = load_session(corrupt_dir)
    corrupt_audit = run_audit(corrupt_session_bundle, cfg)
    dump_json(corrupt_dir / "issues.json", corrupt_audit.to_dict())
    dump_json(corrupt_dir / "audit_summary.json", corrupt_audit.summary)
    corrupt_replay = run_replay(corrupt_session_bundle, "pdr", cfg)
    save_replay(corrupt_replay, corrupt_dir)
    corrupt_benchmark = run_benchmark(corrupt_session_bundle, "pdr", cfg)
    save_benchmark(corrupt_benchmark, corrupt_dir)

    compare_html = work_dir / "sample_tabular_compare.html"
    compare_result = build_compare_report(
        load_session(clean_dir),
        corrupt_session_bundle,
        config=cfg,
        out_path=compare_html,
        json_path=work_dir / "sample_tabular_compare.json",
    )

    batch_dir = work_dir / "batch_artifacts"
    batch_result = batch_audit_sessions(sessions_root, batch_dir, cfg)
    batch_html = work_dir / "batch_report.html"
    build_batch_report(batch_result, batch_html)

    return {
        "report_html": report_html,
        "compare_html": compare_html,
        "batch_html": batch_html,
        "audit_summary_json": clean_dir / "audit_summary.json",
        "compare_json": compare_result.json_path,
        "batch_summary_json": batch_dir / "batch_summary.json",
    }


def capture_preview_assets(artifacts: dict[str, Path], out_dir: Path) -> None:
    scenes = {
        "audit-summary-preview": {
            "html": artifacts["report_html"],
            "poster_scene": "report-poster",
            "gif_scenes": ["report-poster", "report-decision", "report-trust"],
        },
        "report-preview": {
            "html": artifacts["report_html"],
            "poster_scene": "report-trust",
            "gif_scenes": ["report-poster", "report-trust", "report-issues"],
        },
        "compare-preview": {
            "html": artifacts["compare_html"],
            "poster_scene": "compare-poster",
            "gif_scenes": ["compare-poster", "compare-decision", "compare-trust"],
        },
        "batch-preview": {
            "html": artifacts["batch_html"],
            "poster_scene": "batch-poster",
            "gif_scenes": ["batch-poster", "batch-overview", "batch-ranking"],
        },
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for name, scene in scenes.items():
                poster_path = out_dir / f"{name}.png"
                gif_path = out_dir / f"{name}.gif"
                _capture_page_story(
                    browser=browser,
                    html_path=scene["html"],
                    poster_scene=scene["poster_scene"],
                    gif_scenes=scene["gif_scenes"],
                    poster_path=poster_path,
                    gif_path=gif_path,
                )
            _capture_workflow_hero(browser=browser, artifacts=artifacts, out_dir=out_dir)
        finally:
            browser.close()


def _capture_page_story(
    *,
    browser,
    html_path: Path,
    poster_scene: str,
    gif_scenes: list[str],
    poster_path: Path,
    gif_path: Path,
) -> None:
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
    page = context.new_page()
    page.goto(html_path.resolve().as_uri(), wait_until="load")
    page.add_style_tag(content="html { scroll-behavior: auto !important; } body { scrollbar-width: none; } ::-webkit-scrollbar { display: none; }")
    page.wait_for_timeout(1200)
    _wait_for_charts(page)

    _scroll_to_scene(page, poster_scene)
    page.screenshot(path=str(poster_path), full_page=False)

    frames: list[Image.Image] = []
    temp_dir = Path(tempfile.mkdtemp(prefix="imuops-preview-"))
    try:
        for index, scene_id in enumerate(gif_scenes):
            frame_path = temp_dir / f"{index:02d}.png"
            _scroll_to_scene(page, scene_id)
            page.screenshot(path=str(frame_path), full_page=False)
            with Image.open(frame_path) as frame:
                frames.append(frame.convert("P", palette=Image.ADAPTIVE))
        if not frames:
            raise RuntimeError(f"No frames captured for {html_path}")
        first, rest = frames[0], frames[1:]
        first.save(
            gif_path,
            save_all=True,
            append_images=rest,
            optimize=True,
            loop=0,
            duration=SECONDARY_FRAME_DURATIONS_MS[: len(frames)]
            + [SECONDARY_FRAME_DURATIONS_MS[-1]] * max(0, len(frames) - len(SECONDARY_FRAME_DURATIONS_MS)),
            disposal=2,
        )
    finally:
        for frame in frames:
            frame.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
        context.close()


def _scroll_to_scene(page, scene_id: str) -> None:
    locator = page.locator(f"#{scene_id}")
    locator.scroll_into_view_if_needed()
    page.wait_for_timeout(350)


def _wait_for_charts(page) -> None:
    try:
        page.wait_for_selector(".plotly-graph-div svg, .plotly-graph-div canvas", timeout=10_000)
    except Exception:
        page.wait_for_timeout(1200)


def _capture_workflow_hero(*, browser, artifacts: dict[str, Path], out_dir: Path) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if not ffmpeg_path or not ffprobe_path:
        raise RuntimeError("ffmpeg and ffprobe must be available to build workflow-hero.gif")

    poster_path = out_dir / "workflow-hero.png"
    gif_path = out_dir / "workflow-hero.gif"
    temp_dir = Path(tempfile.mkdtemp(prefix="imuops-workflow-hero-"))
    try:
        frame_paths = _capture_hero_frames(browser=browser, artifacts=artifacts, temp_dir=temp_dir)
        shutil.copy(frame_paths[0], poster_path)
        _build_workflow_hero_gif(
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            frame_paths=frame_paths,
            gif_path=gif_path,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _capture_hero_frames(*, browser, artifacts: dict[str, Path], temp_dir: Path) -> list[Path]:
    frame_paths: list[Path] = []
    current_key: str | None = None
    context = None
    page = None
    try:
        for index, (artifact_key, scene_id) in enumerate(HERO_CAPTURE_SEQUENCE):
            html_path = artifacts[artifact_key]
            if artifact_key != current_key:
                if context is not None:
                    context.close()
                context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
                page = context.new_page()
                page.goto(html_path.resolve().as_uri(), wait_until="load")
                page.add_style_tag(
                    content="html { scroll-behavior: auto !important; } body { scrollbar-width: none; } ::-webkit-scrollbar { display: none; }"
                )
                page.wait_for_timeout(1200)
                _wait_for_charts(page)
                current_key = artifact_key
            if page is None:
                raise RuntimeError("Browser page was not initialized for hero capture")
            frame_path = temp_dir / f"hero-{index:02d}.png"
            _scroll_to_scene(page, scene_id)
            page.screenshot(path=str(frame_path), full_page=False)
            frame_paths.append(frame_path)
    finally:
        if context is not None:
            context.close()
    return frame_paths


def _build_workflow_hero_gif(
    *,
    ffmpeg_path: str,
    ffprobe_path: str,
    frame_paths: list[Path],
    gif_path: Path,
) -> None:
    if not frame_paths:
        raise RuntimeError("No frames captured for workflow-hero.gif")

    scene_duration = f"{HERO_SCENE_DURATION_SECONDS:.2f}"
    cmd = [ffmpeg_path, "-y"]
    for frame_path in frame_paths:
        cmd.extend(["-loop", "1", "-t", scene_duration, "-i", str(frame_path)])

    filter_parts: list[str] = []
    for index in range(len(frame_paths)):
        filter_parts.append(
            f"[{index}:v]scale=1160:-1:flags=lanczos,"
            f"zoompan=z='min(zoom+0.0032,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={HERO_ZOOM_FRAMES}:s={HERO_OUTPUT_SIZE}:fps={HERO_FPS},"
            f"trim=duration={HERO_SCENE_DURATION_SECONDS:.2f},setpts=PTS-STARTPTS,"
            f"format=rgba,setsar=1[v{index}]"
        )

    current_label = "v0"
    current_duration = HERO_SCENE_DURATION_SECONDS
    for index in range(1, len(frame_paths)):
        next_label = f"x{index}"
        offset = current_duration - HERO_TRANSITION_SECONDS
        filter_parts.append(
            f"[{current_label}][v{index}]xfade=transition=fade:duration={HERO_TRANSITION_SECONDS:.2f}:offset={offset:.2f}[{next_label}]"
        )
        current_label = next_label
        current_duration = current_duration + HERO_SCENE_DURATION_SECONDS - HERO_TRANSITION_SECONDS

    filter_parts.append(f"[{current_label}]split[gif_a][gif_b]")
    filter_parts.append("[gif_a]palettegen=stats_mode=diff[palette]")
    filter_parts.append("[gif_b][palette]paletteuse=dither=sierra2_4a[final]")

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[final]",
            "-loop",
            "0",
            str(gif_path),
        ]
    )
    subprocess.run(cmd, check=True)

    duration_cmd = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(gif_path),
    ]
    result = subprocess.run(duration_cmd, check=True, capture_output=True, text=True)
    duration_seconds = float(result.stdout.strip() or "0")
    if not 10.0 <= duration_seconds <= 15.0:
        raise RuntimeError(f"workflow-hero.gif duration {duration_seconds:.2f}s is outside the expected 10-15s window")


if __name__ == "__main__":
    main()
