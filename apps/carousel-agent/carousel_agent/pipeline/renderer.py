"""Renderer — calls gpt-image-2 and writes PNG slides to disk.

Plain Python (no LLM agent). The approval gate is implemented in manager.py
via a 2-phase split: render_first_slide is called in phase A; render_remaining
is called in phase B (post-approval).

Retry policy: 3 retries with 2/4/8s exponential backoff; honor Retry-After on
429s.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

from openai import APIError, OpenAI, RateLimitError
from openai import BadRequestError as _BadRequestError

from carousel_agent.config import Config
from carousel_agent.logging_setup import get_logger
from carousel_agent.pipeline.schemas import SlideVisual, VisualSpec

log = get_logger(__name__)


class ImageRenderError(RuntimeError):
    """Raised when image generation fails after all retries."""


class ContentPolicyBlocked(RuntimeError):
    """Raised when gpt-image-2 returns a content-policy block."""


def _client() -> OpenAI:
    return OpenAI()


def _size_for_api(size: str) -> str:
    """gpt-image-2 may not accept arbitrary dimensions. Map to supported sizes.

    1080x1350 (Instagram 4:5) maps to '1024x1536' which is the SDK's portrait token.
    """
    mapping = {
        "1080x1350": "1024x1536",
        "1024x1024": "1024x1024",
    }
    return mapping.get(size, "1024x1536")


def _retry_render(
    client: OpenAI,
    *,
    model: str,
    prompt: str,
    api_size: str,
    retries: int,
) -> bytes:
    delay = 2.0
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            log.info("image API attempt %d (model=%s)", attempt + 1, model)
            resp = client.images.generate(
                model=model,
                prompt=prompt,
                size=api_size,
                n=1,
            )
            if not resp.data or not resp.data[0]:
                raise ImageRenderError("empty data in image response")
            item = resp.data[0]
            b64 = getattr(item, "b64_json", None)
            if b64:
                return base64.b64decode(b64)
            url = getattr(item, "url", None)
            if url:
                # Download the URL bytes
                import httpx

                with httpx.Client(timeout=60) as http:
                    r = http.get(url)
                    r.raise_for_status()
                    return r.content
            raise ImageRenderError("response had no b64_json or url")
        except _BadRequestError as e:
            msg = str(e).lower()
            if "policy" in msg or "safety" in msg:
                raise ContentPolicyBlocked(str(e)) from e
            last_err = e
            log.warning("image API bad-request: %s", e)
        except RateLimitError as e:
            last_err = e
            retry_after = 5.0
            try:
                ra = e.response.headers.get("Retry-After") if e.response is not None else None
                if ra:
                    retry_after = float(ra)
            except Exception:  # noqa: BLE001
                pass
            log.warning("image API rate-limited; sleeping %.1fs", retry_after)
            time.sleep(retry_after)
            # Don't count rate-limit waits against retries.
            continue
        except APIError as e:
            last_err = e
            log.warning("image API error (attempt %d): %s", attempt + 1, e)
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("image API unexpected error (attempt %d): %s", attempt + 1, e)
        if attempt < retries:
            time.sleep(delay)
            delay *= 2
    raise ImageRenderError(f"failed after {retries + 1} attempts: {last_err}")


def render_slide(
    slide: SlideVisual,
    spec: VisualSpec,
    out_dir: Path,
    cfg: Config,
    *,
    use_fallback: bool = False,
) -> Path:
    """Render one slide to disk. Returns the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / f"slide-{slide.index:02d}.png"

    # Compose final prompt: image_prompt + text-overlay instructions baked in.
    overlays_desc = "\n".join(
        f"  - render text \"{o.text}\" at {o.position} ({o.style})" for o in slide.text_overlays
    )
    full_prompt = (
        f"{slide.image_prompt}\n\n"
        f"REQUIRED TEXT OVERLAYS (render these as visible text in the image):\n{overlays_desc}"
    )

    model = cfg.rendering.fallback_model if use_fallback else cfg.rendering.image_model
    api_size = _size_for_api(spec.size)
    client = _client()
    try:
        png_bytes = _retry_render(
            client,
            model=model,
            prompt=full_prompt,
            api_size=api_size,
            retries=cfg.rendering.retries,
        )
    except ImageRenderError:
        if not use_fallback and cfg.rendering.fallback_model != cfg.rendering.image_model:
            log.warning("primary model failed; retrying with fallback %s", cfg.rendering.fallback_model)
            return render_slide(slide, spec, out_dir, cfg, use_fallback=True)
        raise

    fname.write_bytes(png_bytes)
    log.info("rendered slide %d -> %s (%d bytes)", slide.index, fname, len(png_bytes))
    return fname


def render_first_slide(spec: VisualSpec, out_dir: Path, cfg: Config) -> Path:
    if not spec.slides:
        raise ImageRenderError("visual spec has no slides")
    return render_slide(spec.slides[0], spec, out_dir, cfg)


def render_remaining_slides(spec: VisualSpec, out_dir: Path, cfg: Config) -> list[Path]:
    if len(spec.slides) <= 1:
        return []
    return [render_slide(s, spec, out_dir, cfg) for s in spec.slides[1:]]
