from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests


@dataclass(frozen=True)
class BrowserUseConfig:
    app_url: str = "http://localhost:8501"
    api_base_url: str = "http://127.0.0.1:8000"
    question: str = "Orion 支持 SSO 吗？"
    user_id: str = "employee"
    roles: str = "employee"
    top_k: int = 1
    headless: bool = True
    timeout_ms: int = 30000
    screenshot_path: Path | None = None


def run_streamlit_qa_browser_demo(
    config: BrowserUseConfig,
    *,
    playwright_factory: Callable | None = None,
    preflight_check: Callable[[BrowserUseConfig], dict[str, str] | None] | None = None,
) -> dict[str, Any]:
    """Use a real browser to operate the local Streamlit QA page.

    This is a lightweight Browser Use / Computer Use demo. It is intentionally
    scripted for a known local app instead of pretending to be a general-purpose
    autonomous desktop agent.
    """
    started = time.perf_counter()
    try:
        factory = playwright_factory or _load_sync_playwright()
    except RuntimeError as exc:
        return _error_payload(config, "playwright_not_installed", str(exc), started)

    preflight = preflight_check or _preflight
    preflight_error = preflight(config)
    if preflight_error is not None:
        return _error_payload(config, preflight_error["error_code"], preflight_error["error"], started)

    try:
        with factory() as playwright:
            browser = playwright.chromium.launch(headless=config.headless)
            page = browser.new_page()
            try:
                page.goto(config.app_url, wait_until="networkidle", timeout=config.timeout_ms)
                page.get_by_text("企业知识库问答 Agent").wait_for(timeout=config.timeout_ms)
                page.get_by_label("API Base URL").fill(config.api_base_url)
                page.get_by_label("用户 ID").fill(config.user_id)
                page.get_by_label("用户角色（逗号分隔）").fill(config.roles)
                page.get_by_label("输入问题").fill(config.question)
                _set_top_k_if_needed(page, config.top_k)
                page.get_by_role("button", name="提问").click()
                body_text = _wait_for_result_body(page, timeout_ms=config.timeout_ms)

                screenshot = None
                if config.screenshot_path is not None:
                    config.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(config.screenshot_path), full_page=True)
                    screenshot = str(config.screenshot_path)
                return {
                    "ok": True,
                    "mode": "browser_use_streamlit_qa",
                    "app_url": config.app_url,
                    "api_base_url": config.api_base_url,
                    "question": config.question,
                    "user_id": config.user_id,
                    "roles": _roles(config.roles),
                    "top_k": config.top_k,
                    "run_id": extract_run_id(body_text),
                    "answer_preview": extract_answer_preview(body_text),
                    "screenshot_path": screenshot,
                    "latency_ms": _latency(started),
                    "steps": [
                        "open_streamlit_app",
                        "fill_user_context",
                        "fill_question",
                        "submit_question",
                        "wait_for_run_id",
                        "extract_result",
                    ],
                }
            finally:
                browser.close()
    except RuntimeError as exc:
        error_code = "playwright_not_installed" if "Playwright 未安装" in str(exc) else "browser_use_failed"
        return _error_payload(config, error_code, str(exc), started)
    except Exception as exc:
        return _error_payload(config, "browser_use_failed", str(exc), started)


def extract_run_id(text: str) -> str:
    match = re.search(r"Run ID[:：]\s*(run_[a-zA-Z0-9]+)", text)
    return match.group(1) if match else ""


def extract_answer_preview(text: str, max_chars: int = 300) -> str:
    answer_marker = "回答"
    citation_marker = "引用"
    start = text.find(answer_marker)
    if start < 0:
        return text.strip()[:max_chars]
    end = text.find(citation_marker, start + len(answer_marker))
    segment = text[start + len(answer_marker) : end if end >= 0 else None]
    lines = [line.strip() for line in segment.splitlines() if line.strip()]
    return "\n".join(lines)[:max_chars]


def _load_sync_playwright() -> Callable:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright 未安装。请先运行："
            ".\\.venv\\Scripts\\python.exe -m pip install -e \".[browser]\"，"
            "然后运行：.\\.venv\\Scripts\\python.exe -m playwright install chromium"
        ) from exc
    return sync_playwright


def _set_top_k_if_needed(page, top_k: int) -> None:
    if top_k == 1:
        return
    slider = page.get_by_label("检索 Top-K")
    slider.fill(str(top_k))


def _wait_for_result_body(page, *, timeout_ms: int) -> str:
    deadline = time.perf_counter() + timeout_ms / 1000
    last_body = ""
    while time.perf_counter() < deadline:
        try:
            body_text = page.locator("body").inner_text(timeout=min(5000, timeout_ms))
        except Exception:
            page.wait_for_timeout(500)
            continue
        last_body = body_text
        if _has_result_block(body_text):
            return body_text
        page.wait_for_timeout(500)
    raise TimeoutError(
        "页面在限定时间内没有出现问答结果区。"
        f"最后看到的页面摘要：{_compact_preview(last_body)}"
    )


def _roles(roles: str) -> list[str]:
    return [role.strip() for role in roles.split(",") if role.strip()]


def _preflight(config: BrowserUseConfig) -> dict[str, str] | None:
    try:
        response = requests.get(f"{config.api_base_url.rstrip('/')}/health", timeout=5)
        response.raise_for_status()
    except Exception as exc:
        return {
            "error_code": "fastapi_unreachable",
            "error": (
                f"FastAPI 后端不可用：{config.api_base_url}/health。"
                f"请先启动后端服务。原始错误：{exc}"
            ),
        }
    try:
        response = requests.get(config.app_url, timeout=5)
        response.raise_for_status()
    except Exception as exc:
        return {
            "error_code": "streamlit_unreachable",
            "error": (
                f"Streamlit 页面不可用：{config.app_url}。"
                f"请先启动前端页面。原始错误：{exc}"
            ),
        }
    return None


def _error_payload(
    config: BrowserUseConfig,
    error_code: str,
    message: str,
    started: float,
) -> dict[str, Any]:
    return {
        "ok": False,
        "mode": "browser_use_streamlit_qa",
        "app_url": config.app_url,
        "api_base_url": config.api_base_url,
        "question": config.question,
        "user_id": config.user_id,
        "roles": _roles(config.roles),
        "top_k": config.top_k,
        "error_code": error_code,
        "error": message,
        "latency_ms": _latency(started),
        "local_checklist": [
            "确认 FastAPI 已启动：http://127.0.0.1:8000/health",
            "确认 Streamlit 已启动：http://localhost:8501",
            "确认已安装 Playwright 和 chromium 浏览器内核",
        ],
    }


def _latency(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _has_result_block(body_text: str) -> bool:
    normalized = body_text.replace("：", ":")
    return ("回答" in normalized and "Run ID" in normalized) or (
        "回答" in normalized and "Runtime" in normalized
    )


def _compact_preview(text: str, max_chars: int = 240) -> str:
    compacted = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return compacted[:max_chars]
