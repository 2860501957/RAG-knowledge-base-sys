from pathlib import Path

from backend.services.browser_use import (
    BrowserUseConfig,
    extract_answer_preview,
    extract_run_id,
    run_streamlit_qa_browser_demo,
)


class FakeLocator:
    def __init__(self, page, selector: str):
        self.page = page
        self.selector = selector

    def wait_for(self, timeout: int):
        self.page.actions.append(("wait_for", self.selector, timeout))

    def fill(self, value: str):
        self.page.actions.append(("fill", self.selector, value))

    def click(self):
        self.page.actions.append(("click", self.selector))

    def inner_text(self, timeout: int):
        self.page.actions.append(("inner_text", self.selector, timeout))
        return (
            "企业知识库问答 Agent\n"
            "回答\n"
            "结论：支持 SSO。\n"
            "引用\n"
            "Run ID：run_browser123\n"
        )


class FakePage:
    def __init__(self):
        self.actions = []

    def goto(self, url: str, wait_until: str, timeout: int):
        self.actions.append(("goto", url, wait_until, timeout))

    def get_by_text(self, text: str):
        return FakeLocator(self, f"text={text}")

    def get_by_label(self, label: str):
        return FakeLocator(self, f"label={label}")

    def get_by_role(self, role: str, name: str):
        return FakeLocator(self, f"role={role}:{name}")

    def locator(self, selector: str):
        return FakeLocator(self, selector)

    def screenshot(self, path: str, full_page: bool):
        self.actions.append(("screenshot", path, full_page))
        Path(path).write_text("fake screenshot", encoding="utf-8")


class FakeBrowser:
    def __init__(self):
        self.page = FakePage()
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self):
        self.browser = FakeBrowser()

    def launch(self, headless: bool):
        self.headless = headless
        return self.browser


class FakePlaywright:
    def __init__(self):
        self.chromium = FakeChromium()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_browser_use_demo_drives_streamlit_page(tmp_path: Path) -> None:
    fake = FakePlaywright()

    payload = run_streamlit_qa_browser_demo(
        BrowserUseConfig(
            app_url="http://localhost:8501",
            question="Orion 支持 SSO 吗？",
            user_id="alice",
            roles="employee",
            screenshot_path=tmp_path / "browser.png",
        ),
        playwright_factory=lambda: fake,
        preflight_check=lambda config: None,
    )

    assert payload["ok"] is True
    assert payload["run_id"] == "run_browser123"
    assert payload["answer_preview"] == "结论：支持 SSO。"
    assert payload["screenshot_path"] == str(tmp_path / "browser.png")
    assert fake.chromium.browser.closed is True
    assert ("fill", "label=用户 ID", "alice") in fake.chromium.browser.page.actions
    assert ("click", "role=button:提问") in fake.chromium.browser.page.actions


def test_browser_use_extractors() -> None:
    text = "回答\n结论：支持。\n引用\nRun ID: run_abc123"

    assert extract_run_id(text) == "run_abc123"
    assert extract_answer_preview(text) == "结论：支持。"


def test_browser_use_demo_reports_missing_playwright() -> None:
    def missing_factory():
        raise RuntimeError("Playwright 未安装")

    payload = run_streamlit_qa_browser_demo(
        BrowserUseConfig(),
        playwright_factory=missing_factory,
        preflight_check=lambda config: None,
    )

    assert payload["ok"] is False
    assert payload["error_code"] == "playwright_not_installed"


def test_browser_use_demo_reports_fastapi_preflight_failure() -> None:
    payload = run_streamlit_qa_browser_demo(
        BrowserUseConfig(),
        playwright_factory=lambda: FakePlaywright(),
        preflight_check=lambda config: {
            "error_code": "fastapi_unreachable",
            "error": "FastAPI 后端不可用",
        },
    )

    assert payload["ok"] is False
    assert payload["error_code"] == "fastapi_unreachable"
