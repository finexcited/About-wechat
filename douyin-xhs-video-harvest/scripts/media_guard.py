#!/usr/bin/env python3
"""Validate and metadata-clean vertical social videos without re-encoding."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ASPECT_TARGET = 9 / 16
ASPECT_TOLERANCE = 0.02
MIN_SHORT_SIDE = 1080
DURATION_TOLERANCE_SECONDS = 0.15

SUSPICIOUS_KEYS = {
    "creation_time",
    "creationdate",
    "encoded_date",
    "tagged_date",
    "writing_application",
    "writingapplication",
    "encoder",
    "software",
    "device",
    "devicename",
    "make",
    "model",
    "manufacturer",
    "serial_number",
    "creationdatevalue",
    "com.apple.quicktime.creationdate",
}

SUSPICIOUS_VALUE_PATTERN = re.compile(
    r"(capcut|jianying|剪映|videoleap|viva\s*video|device\s*id|serial\s*number)",
    re.IGNORECASE,
)


class MediaError(RuntimeError):
    """A user-facing media processing error."""


def command_path(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise MediaError(f"未找到 {name}，请先安装并确保它在 PATH 中")
    return path


def run_process(
    args: list[str], *, capture_stdout: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def probe(path: Path) -> dict[str, Any]:
    ffprobe = command_path("ffprobe")
    result = run_process(
        [
            ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ]
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "ffprobe 无法读取文件"
        raise MediaError(f"媒体探测失败：{detail}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(f"ffprobe 返回了无效 JSON：{exc}") from exc
    if not any(stream.get("codec_type") == "video" for stream in data.get("streams", [])):
        raise MediaError("文件中没有视频流")
    return data


def first_video_stream(data: dict[str, Any]) -> dict[str, Any]:
    videos = [
        stream
        for stream in data.get("streams", [])
        if stream.get("codec_type") == "video"
    ]
    return next(
        (
            stream
            for stream in videos
            if not stream.get("disposition", {}).get("attached_pic")
        ),
        videos[0],
    )


def rotation_degrees(stream: dict[str, Any]) -> int:
    rotate_tag = stream.get("tags", {}).get("rotate")
    if rotate_tag is not None:
        try:
            return int(float(rotate_tag)) % 360
        except ValueError:
            pass

    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            try:
                return int(float(side_data["rotation"])) % 360
            except (TypeError, ValueError):
                pass
    return 0


def display_dimensions(stream: dict[str, Any]) -> tuple[int, int, int]:
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    rotation = rotation_degrees(stream)
    if rotation in (90, 270):
        width, height = height, width
    return width, height, rotation


def metadata_inventory(data: dict[str, Any]) -> dict[str, Any]:
    tags: list[dict[str, str]] = []
    containers: list[tuple[str, dict[str, Any]]] = [
        ("format", data.get("format", {}).get("tags", {}) or {})
    ]
    for index, stream in enumerate(data.get("streams", [])):
        containers.append((f"stream:{index}", stream.get("tags", {}) or {}))

    suspicious: list[dict[str, str]] = []
    for container, entries in containers:
        for key, value in entries.items():
            key_text = str(key)
            value_text = str(value)
            tags.append(
                {"container": container, "key": key_text, "value": value_text}
            )
            key_normalized = key_text.strip().lower()
            apple_private_tag = key_normalized.startswith(
                "com.apple.quicktime."
            ) and any(
                term in key_normalized
                for term in ("creation", "make", "model", "software")
            )
            if (
                key_normalized in SUSPICIOUS_KEYS
                or apple_private_tag
                or SUSPICIOUS_VALUE_PATTERN.search(value_text)
            ):
                suspicious.append(
                    {
                        "container": container,
                        "key": key_text,
                        "value": value_text,
                    }
                )
    return {
        "clean": not suspicious,
        "tags": tags,
        "suspicious": suspicious,
    }


def decode_check(path: Path) -> tuple[bool, str | None]:
    ffmpeg = command_path("ffmpeg")
    result = run_process(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-f",
            "null",
            "-",
        ],
        capture_stdout=False,
    )
    detail = result.stderr.strip()
    return result.returncode == 0, detail or None


def stream_signature(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "index": stream.get("index"),
            "type": stream.get("codec_type"),
            "codec": stream.get("codec_name"),
            "profile": stream.get("profile"),
            "width": stream.get("width"),
            "height": stream.get("height"),
        }
        for stream in data.get("streams", [])
    ]


def duration_seconds(data: dict[str, Any]) -> float:
    raw = data.get("format", {}).get("duration")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def inspect_media(path: Path, *, require_clean: bool = False) -> dict[str, Any]:
    if not path.is_file():
        raise MediaError(f"文件不存在：{path}")

    data = probe(path)
    video = first_video_stream(data)
    width, height, rotation = display_dimensions(video)
    ratio = width / height if height else 0.0
    relative_error = (
        abs(ratio - ASPECT_TARGET) / ASPECT_TARGET if ratio else float("inf")
    )
    short_side = min(width, height) if width and height else 0
    vertical = height > width > 0
    aspect_ok = relative_error <= ASPECT_TOLERANCE
    resolution_ok = short_side >= MIN_SHORT_SIDE
    metadata = metadata_inventory(data)
    decode_ok, decode_error = decode_check(path)

    spec_ok = vertical and aspect_ok and resolution_ok and decode_ok
    qualified = spec_ok and (metadata["clean"] or not require_clean)
    return {
        "file": str(path.resolve()),
        "qualified": qualified,
        "spec_ok": spec_ok,
        "require_clean": require_clean,
        "probe_ok": True,
        "decode_ok": decode_ok,
        "decode_error": decode_error,
        "width": width,
        "height": height,
        "rotation": rotation,
        "short_side": short_side,
        "vertical": vertical,
        "aspect_ratio": round(ratio, 6),
        "aspect_error_percent": round(relative_error * 100, 3),
        "aspect_ok": aspect_ok,
        "resolution_ok": resolution_ok,
        "duration_seconds": round(duration_seconds(data), 3),
        "video_codec": video.get("codec_name"),
        "pixel_format": video.get("pix_fmt"),
        "frame_rate": video.get("avg_frame_rate"),
        "metadata": metadata,
        "streams": stream_signature(data),
    }


def clean_ffmpeg(input_path: Path, output_path: Path) -> None:
    ffmpeg = command_path("ffmpeg")
    result = run_process(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(input_path),
            "-map",
            "0",
            "-map_metadata",
            "-1",
            "-map_metadata:s:v",
            "-1",
            "-map_metadata:s:a",
            "-1",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-flags:a",
            "+bitexact",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "ffmpeg 重封装失败"
        raise MediaError(f"无损清理失败：{detail}")


def clear_residual_metadata(path: Path) -> bool:
    exiftool = shutil.which("exiftool")
    if not exiftool:
        return False
    result = run_process([exiftool, "-all=", "-overwrite_original", str(path)])
    return result.returncode == 0


def compare_streams(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if stream_signature(before) != stream_signature(after):
        problems.append("视音频流的编解码器或分辨率发生变化")

    before_duration = duration_seconds(before)
    after_duration = duration_seconds(after)
    if abs(before_duration - after_duration) > DURATION_TOLERANCE_SECONDS:
        problems.append(
            f"时长变化超过 {DURATION_TOLERANCE_SECONDS}s："
            f"{before_duration:.3f}s -> {after_duration:.3f}s"
        )
    return problems


def clean_media(
    input_path: Path, output_path: Path, *, overwrite: bool = False
) -> dict[str, Any]:
    if not input_path.is_file():
        raise MediaError(f"输入文件不存在：{input_path}")
    if input_path.resolve() == output_path.resolve():
        raise MediaError("输出路径不能与输入路径相同")
    if output_path.exists() and not overwrite:
        raise MediaError(f"输出文件已存在：{output_path}；如确需覆盖请加 --overwrite")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    before_probe = probe(input_path)
    before = inspect_media(input_path)
    if not before["spec_ok"]:
        reasons = []
        if not before["vertical"]:
            reasons.append("不是竖版")
        if not before["aspect_ok"]:
            reasons.append("宽高比不是 9:16（±2%）")
        if not before["resolution_ok"]:
            reasons.append("短边低于 1080")
        if not before["decode_ok"]:
            reasons.append("无法完整解码")
        raise MediaError("输入未通过规格初检：" + "、".join(reasons))

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}.", suffix=".mp4", dir=output_path.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)
    temp_path.unlink(missing_ok=True)

    try:
        clean_ffmpeg(input_path, temp_path)
        after_probe = probe(temp_path)
        problems = compare_streams(before_probe, after_probe)
        if problems:
            raise MediaError("；".join(problems))

        after = inspect_media(temp_path, require_clean=True)
        residual_removed = False
        if not after["metadata"]["clean"]:
            residual_removed = clear_residual_metadata(temp_path)
            if residual_removed:
                after_probe = probe(temp_path)
                residual_problems = compare_streams(before_probe, after_probe)
                if residual_problems:
                    raise MediaError("；".join(residual_problems))
                after = inspect_media(temp_path, require_clean=True)

        if not after["qualified"]:
            residual = after["metadata"]["suspicious"]
            if residual:
                summary = ", ".join(
                    f"{item['container']}:{item['key']}={item['value']}"
                    for item in residual[:8]
                )
                raise MediaError(f"清理后仍检测到可疑元数据：{summary}")
            raise MediaError("清理后的文件未通过最终验收")

        os.replace(temp_path, output_path)
        result = inspect_media(output_path, require_clean=True)
        if not result["qualified"]:
            raise MediaError("最终文件复查失败")
        result["input_metadata"] = before["metadata"]
        result["residual_removed_with_exiftool"] = residual_removed
        return result
    finally:
        temp_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验 9:16 1080p+ 视频并无损清理容器元数据"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="检查规格、解码和元数据")
    inspect_parser.add_argument("file", type=Path)
    inspect_parser.add_argument(
        "--require-clean",
        action="store_true",
        help="只有元数据无残留时才返回成功",
    )
    inspect_parser.add_argument(
        "--report", type=Path, help="同时把 JSON 结果写入指定文件"
    )

    clean_parser = subparsers.add_parser("clean", help="无损重封装并验证")
    clean_parser.add_argument("input", type=Path)
    clean_parser.add_argument("output", type=Path)
    clean_parser.add_argument(
        "--overwrite", action="store_true", help="允许覆盖已有输出文件"
    )
    clean_parser.add_argument(
        "--report", type=Path, help="把最终 JSON 报告写入指定文件"
    )
    return parser


def emit_result(result: dict[str, Any], report_path: Path | None, success: bool) -> int:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")
    return 0 if success else 2


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            result = inspect_media(args.file, require_clean=args.require_clean)
            return emit_result(result, args.report, bool(result["qualified"]))

        result = clean_media(args.input, args.output, overwrite=args.overwrite)
        return emit_result(result, args.report, bool(result["qualified"]))
    except MediaError as exc:
        error = {"error": str(exc), "command": args.command}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(error, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
