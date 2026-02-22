from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import typer

from birdstamp.config import load_config, write_default_config
from birdstamp.constants import DEFAULT_SHOW_FIELDS, VALID_FRAME_STYLES, VALID_MODES
from birdstamp.decoders.image_decoder import decode_image
from birdstamp.discover import discover_inputs
from birdstamp.gui.editor_core import CENTER_MODE_BIRD, CENTER_MODE_FOCUS, apply_editor_crop
from birdstamp.meta.exiftool import extract_many
from birdstamp.meta.normalize import normalize_metadata
from birdstamp.meta.pillow_fallback import extract_pillow_metadata
from birdstamp.models import RenderOptions
from birdstamp.naming import build_output_name
from birdstamp.render.banner import render_banner
from birdstamp.render.image_modes import apply_output_mode
from birdstamp.template_loader import list_builtin_templates, load_template

app = typer.Typer(add_completion=False, no_args_is_help=True, help="BirdStamp / 鸟印 photo banner CLI.")
LOGGER = logging.getLogger("birdstamp")


@dataclass(slots=True)
class ProcessResult:
    source: Path
    status: str
    output: Path | None = None
    elapsed: float = 0.0
    error: str | None = None


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _parse_multi_values(values: list[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for item in str(value).split(","):
            token = item.strip().lower()
            if token:
                items.append(token)
    return items


def _resolve_output_format(output_format: str) -> tuple[str, str]:
    fmt = output_format.lower()
    if fmt in {"jpeg", "jpg"}:
        return "jpg", "JPEG"
    if fmt == "png":
        return "png", "PNG"
    raise ValueError("output format must be jpeg/jpg or png")


def _save_image(image, path: Path, pil_format: str, quality: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if pil_format == "JPEG":
        image.save(path, format="JPEG", quality=max(1, min(100, quality)), optimize=True, progressive=True)
    else:
        image.save(path, format="PNG", optimize=True)


@app.command()
def render(
    input_path: Path = typer.Argument(..., exists=True, resolve_path=True),
    out: Path | None = typer.Option(None, "--out", help="Output directory."),
    recursive: bool = typer.Option(False, "--recursive", help="Recursively scan input directories."),
    ext: list[str] = typer.Option([], "--ext", help="Extension filter, repeat or use comma-separated."),
    template: str | None = typer.Option(None, "--template", help="Template name or template file path."),
    theme: str | None = typer.Option(None, "--theme", help="Theme override: light|gray|dark"),
    banner_height: int | None = typer.Option(None, "--banner-height", min=80),
    font: Path | None = typer.Option(None, "--font", exists=True, file_okay=True, dir_okay=False),
    lang: str | None = typer.Option(None, "--lang", help="Language tag for labels (zh/en)."),
    show: list[str] = typer.Option([], "--show", help="Display fields, repeat or use comma-separated."),
    bird: str | None = typer.Option(None, "--bird", help="Force bird name for whole batch."),
    bird_from: str | None = typer.Option(None, "--bird-from", help="Bird source order, e.g. arg,meta,filename"),
    bird_regex: str | None = typer.Option(None, "--bird-regex", help="Regex used for filename bird extraction."),
    time_format: str | None = typer.Option(None, "--time-format", help="Datetime output format."),
    mode: str | None = typer.Option(None, "--mode", help="Output mode: keep|fit|square|vertical"),
    center: str | None = typer.Option(
        None,
        "--center",
        help="Crop center for square/vertical: image|focus|bird (focus=EXIF focus, bird=detect bird).",
    ),
    frame_style: str | None = typer.Option(None, "--frame-style", help="For square/vertical: crop|pad"),
    max_long_edge: int | None = typer.Option(None, "--max-long-edge", min=0),
    jobs: int | None = typer.Option(None, "--jobs", min=1, help="Parallel workers."),
    name_template: str | None = typer.Option(None, "--name", help='Output name template, e.g. "{date}_{camera}_{stem}.{ext}"'),
    output_format: str | None = typer.Option(None, "--format", help="Output format: jpeg|png"),
    quality: int | None = typer.Option(None, "--quality", min=1, max=100),
    use_exiftool: str | None = typer.Option(None, "--use-exiftool", help="auto|on|off"),
    decoder: str | None = typer.Option(None, "--decoder", help="auto|rawpy|darktable"),
    skip_existing: bool | None = typer.Option(None, "--skip-existing/--no-skip-existing"),
    show_eq_focal: bool | None = typer.Option(None, "--show-eq-focal/--no-show-eq-focal"),
    log_level: str = typer.Option("info", "--log-level"),
) -> None:
    cfg = load_config()
    _setup_logging(log_level)

    template_name = template or str(cfg.get("template", "default"))
    theme_name = theme or cfg.get("theme")
    banner_height_value = int(banner_height if banner_height is not None else cfg.get("banner_height", 220))
    lang_value = lang or str(cfg.get("lang", "zh"))

    show_values = _parse_multi_values(show)
    if not show_values:
        show_values = [str(v).lower() for v in cfg.get("show", DEFAULT_SHOW_FIELDS)]
    show_fields = set(show_values) or set(DEFAULT_SHOW_FIELDS)

    bird_priority_raw = bird_from or ",".join(cfg.get("bird_from", ["arg", "meta", "filename"]))
    bird_priority = _parse_multi_values([bird_priority_raw]) or ["arg", "meta", "filename"]
    bird_regex_value = bird_regex or str(cfg.get("bird_regex", r"(?P<bird>[^_]+)_"))
    time_format_value = time_format or str(cfg.get("time_format", "%Y-%m-%d %H:%M"))

    mode_value = (mode or str(cfg.get("mode", "keep"))).lower()
    if mode_value not in VALID_MODES:
        raise typer.BadParameter(f"mode must be one of: {', '.join(sorted(VALID_MODES))}")

    frame_style_value = (frame_style or str(cfg.get("frame_style", "crop"))).lower()
    if frame_style_value not in VALID_FRAME_STYLES:
        raise typer.BadParameter(f"frame-style must be one of: {', '.join(sorted(VALID_FRAME_STYLES))}")

    center_value = (center or str(cfg.get("center", "image"))).lower()
    if center_value not in ("image", "focus", "bird"):
        raise typer.BadParameter("center must be one of: image, focus, bird")

    max_long_edge_value = int(max_long_edge if max_long_edge is not None else cfg.get("max_long_edge", 2048))
    jobs_value = int(jobs if jobs is not None else cfg.get("jobs", 1))
    jobs_value = max(1, jobs_value)
    name_template_value = name_template or str(cfg.get("name_template", "{stem}__banner.{ext}"))
    output_format_value = output_format or str(cfg.get("output_format", "jpeg"))
    output_extension, pil_format = _resolve_output_format(output_format_value)
    quality_value = int(quality if quality is not None else cfg.get("quality", 92))
    use_exiftool_value = (use_exiftool or str(cfg.get("use_exiftool", "auto"))).lower()
    decoder_value = (decoder or str(cfg.get("decoder", "auto"))).lower()
    skip_existing_value = bool(cfg.get("skip_existing", True)) if skip_existing is None else skip_existing
    show_eq_focal_value = bool(cfg.get("show_eq_focal", True)) if show_eq_focal is None else show_eq_focal
    input_extensions = _parse_multi_values(ext)

    files = discover_inputs(input_path, recursive=recursive, extensions=input_extensions or None)
    if not files:
        typer.echo("No supported image files found.")
        raise typer.Exit(0)

    out_dir = out
    if out_dir is None:
        out_dir = (input_path / "output") if input_path.is_dir() else (input_path.parent / "output")
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        template_spec = load_template(template_name, theme=theme_name, banner_height=banner_height_value)
    except Exception as exc:
        typer.secho(f"Template error: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(1)

    render_options = RenderOptions(
        show_fields=show_fields,
        lang=lang_value,
        font_path=font,
        show_eq_focal=show_eq_focal_value,
        fallback_text="N/A",
    )

    resolved_files = [p.resolve(strict=False) for p in files]
    try:
        raw_meta_map = extract_many(resolved_files, mode=use_exiftool_value)
    except Exception as exc:
        typer.secho(f"Metadata extraction setup failed: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(1)

    def process_one(source: Path) -> ProcessResult:
        started = time.perf_counter()
        try:
            resolved = source.resolve(strict=False)
            raw_meta = raw_meta_map.get(resolved)
            if not raw_meta:
                raw_meta = extract_pillow_metadata(source)
            metadata = normalize_metadata(
                source,
                raw_meta,
                bird_arg=bird,
                bird_priority=bird_priority,
                bird_regex=bird_regex_value,
                time_format=time_format_value,
            )
            output_name = build_output_name(name_template_value, source, metadata, extension=output_extension)
            output_file = out_dir / output_name
            if skip_existing_value and output_file.exists():
                return ProcessResult(source=source, status="skipped", output=output_file, elapsed=time.perf_counter() - started)

            image = decode_image(source, decoder=decoder_value)
            fill_color = template_spec.colors.get("background", "#FFFFFF")
            if mode_value in ("square", "vertical") and center_value in (CENTER_MODE_FOCUS, CENTER_MODE_BIRD):
                ratio = 1.0 if mode_value == "square" else (9.0 / 16.0)
                image = apply_editor_crop(
                    image,
                    source_path=source,
                    raw_metadata=raw_meta,
                    ratio=ratio,
                    center_mode=center_value,
                    crop_padding_px=0,
                    max_long_edge=max_long_edge_value,
                    fill_color=fill_color,
                    use_bird_auto=(center_value == CENTER_MODE_BIRD),
                )
            else:
                image = apply_output_mode(
                    image,
                    mode=mode_value,
                    max_long_edge=max_long_edge_value,
                    frame_style=frame_style_value,
                    fill_color=fill_color,
                )
            rendered = render_banner(image, metadata, template_spec, render_options)
            _save_image(rendered, output_file, pil_format=pil_format, quality=quality_value)
            return ProcessResult(source=source, status="ok", output=output_file, elapsed=time.perf_counter() - started)
        except Exception as exc:
            return ProcessResult(
                source=source,
                status="failed",
                error=str(exc),
                elapsed=time.perf_counter() - started,
            )

    LOGGER.info("Starting render for %d files, jobs=%d", len(files), jobs_value)

    results: list[ProcessResult] = []
    if jobs_value == 1:
        for file in files:
            result = process_one(file)
            results.append(result)
            if result.status == "ok":
                LOGGER.info("OK %s -> %s (%.2fs)", result.source.name, result.output.name if result.output else "-", result.elapsed)
            elif result.status == "skipped":
                LOGGER.info("SKIP %s (output exists)", result.source.name)
            else:
                LOGGER.error("FAIL %s (%s)", result.source.name, result.error)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs_value) as executor:
            future_map = {executor.submit(process_one, file): file for file in files}
            for future in concurrent.futures.as_completed(future_map):
                result = future.result()
                results.append(result)
                if result.status == "ok":
                    LOGGER.info("OK %s -> %s (%.2fs)", result.source.name, result.output.name if result.output else "-", result.elapsed)
                elif result.status == "skipped":
                    LOGGER.info("SKIP %s (output exists)", result.source.name)
                else:
                    LOGGER.error("FAIL %s (%s)", result.source.name, result.error)

    ok_count = sum(1 for r in results if r.status == "ok")
    skip_count = sum(1 for r in results if r.status == "skipped")
    fail_results = [r for r in results if r.status == "failed"]
    typer.echo(f"Done. success={ok_count} skipped={skip_count} failed={len(fail_results)}")
    if fail_results:
        typer.echo("Failures:")
        for item in fail_results:
            typer.echo(f"- {item.source}: {item.error}")


@app.command("inspect")
def inspect_file(
    file: Path = typer.Argument(..., exists=True, resolve_path=True, dir_okay=False),
    use_exiftool: str = typer.Option("auto", "--use-exiftool", help="auto|on|off"),
    bird: str | None = typer.Option(None, "--bird"),
    bird_from: str = typer.Option("arg,meta,filename", "--bird-from"),
    bird_regex: str = typer.Option(r"(?P<bird>[^_]+)_", "--bird-regex"),
    time_format: str = typer.Option("%Y-%m-%d %H:%M", "--time-format"),
    raw: bool = typer.Option(False, "--raw", help="Include raw metadata payload."),
) -> None:
    resolved = file.resolve(strict=False)
    try:
        raw_map = extract_many([resolved], mode=use_exiftool.lower())
    except Exception as exc:
        typer.secho(f"Metadata extraction failed: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(1)
    raw_metadata = raw_map.get(resolved) or extract_pillow_metadata(file)
    metadata = normalize_metadata(
        file,
        raw_metadata,
        bird_arg=bird,
        bird_priority=_parse_multi_values([bird_from]) or ["arg", "meta", "filename"],
        bird_regex=bird_regex,
        time_format=time_format,
    )
    payload = metadata.to_dict()
    if raw:
        payload["raw_metadata"] = raw_metadata
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command()
def templates() -> None:
    for name in list_builtin_templates():
        typer.echo(name)


@app.command("init-config")
def init_config(
    force: bool = typer.Option(False, "--force", help="Overwrite existing config file."),
) -> None:
    path = write_default_config(force=force)
    typer.echo(f"Config initialized: {path}")


@app.command()
def gui(
    file: Path | None = typer.Option(
        None,
        "--file",
        exists=True,
        resolve_path=True,
        dir_okay=False,
        help="Open this image file on startup.",
    ),
) -> None:
    try:
        from birdstamp.gui import launch_gui
    except Exception as exc:
        typer.secho(f"GUI is unavailable: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(1)

    try:
        launch_gui(startup_file=file)
    except Exception as exc:
        typer.secho(f"GUI failed to start: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
