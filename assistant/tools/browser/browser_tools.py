"""Browser Automation Tools (Phase 9B & 9C).

Tools:
- browser.open (L1)
- browser.read (L1)
- browser.screenshot (L1)
- browser.find_links (L1)
- browser.click (L2/L3 with L0 block)
- browser.type (L2/L3 with L0 block)
"""

from __future__ import annotations

import datetime
import hashlib
import time
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field

from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.browser.manager import browser_manager
from assistant.tools.browser.safety import (
    classify_action_risk,
    wrap_untrusted_content,
)


class BrowserOpenInput(BaseModel):
    url: str = Field(description="URL to open in the isolated browser (http://, https://, or file:///)")
    wait_until: str = Field(
        default="domcontentloaded",
        description="Navigation wait condition: 'load', 'domcontentloaded', or 'networkidle'",
    )


class BrowserReadInput(BaseModel):
    selector: Optional[str] = Field(
        default=None,
        description="Optional CSS selector to read text from (defaults to entire page body)",
    )
    max_chars: int = Field(default=5000, ge=100, le=50000, description="Max characters of text to return")


class BrowserScreenshotInput(BaseModel):
    path: Optional[str] = Field(
        default=None,
        description="Optional custom file path to save screenshot PNG (defaults to data/cache/browser/)",
    )
    full_page: bool = Field(default=False, description="Whether to capture full scrollable page")


class BrowserFindLinksInput(BaseModel):
    query: Optional[str] = Field(default=None, description="Optional text filter for link labels or URLs")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum number of links to return")


class BrowserClickInput(BaseModel):
    selector: Optional[str] = Field(default=None, description="CSS selector of element to click")
    text: Optional[str] = Field(default=None, description="Visible text of element to click")
    role: Optional[str] = Field(default=None, description="ARIA role of element (e.g. 'button', 'link', 'tab')")
    confirmed: bool = Field(default=False, description="Confirmation flag for L3 operations")


class BrowserTypeInput(BaseModel):
    selector: str = Field(description="CSS selector of the input field to type into")
    text: str = Field(description="Text to type into the field")
    clear_first: bool = Field(default=True, description="Clear existing field content before typing")
    confirmed: bool = Field(default=False, description="Confirmation flag for L3 operations")


@tool(
    name="browser.open",
    risk=Risk.OBSERVE,
    description="Open a URL in the isolated Playwright browser and return page status and title.",
    input_model=BrowserOpenInput,
    timeout_s=35,
    requires_elevation=False,
)
def browser_open_tool(args: BrowserOpenInput) -> ToolResult:
    url = args.url.strip()
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("file:///")):
        return ToolResult.fail("Invalid URL protocol. Only http://, https://, and file:/// are permitted.")

    try:
        page = browser_manager.get_page()
        start_t = time.perf_counter()
        resp = page.goto(url, wait_until=args.wait_until, timeout=30000)
        load_time_ms = round((time.perf_counter() - start_t) * 1000.0, 1)

        status_code = resp.status if resp else 200
        title = page.title()
        current_url = page.url
        browser_manager.update_activity()

        data = {
            "url": current_url,
            "title": title,
            "status_code": status_code,
            "load_time_ms": load_time_ms,
            "untrusted": True,
        }

        untrusted_title = wrap_untrusted_content(title, "page_title")
        summary = (
            f"Browser Berhasil Membuka Halaman:\n"
            f"- URL: {current_url}\n"
            f"- Judul: {untrusted_title}\n"
            f"- Status HTTP: {status_code} ({load_time_ms} ms)"
        )
        return ToolResult.success(data=data, summary=summary, untrusted=True)
    except Exception as e:
        return ToolResult.fail(f"Gagal membuka URL '{url}': {e}")


@tool(
    name="browser.read",
    risk=Risk.OBSERVE,
    description="Read visible text content from the current active browser page or a specific CSS selector.",
    input_model=BrowserReadInput,
    timeout_s=15,
    requires_elevation=False,
)
def browser_read_tool(args: BrowserReadInput) -> ToolResult:
    try:
        page = browser_manager.get_page()
        browser_manager.update_activity()

        if args.selector:
            locator = page.locator(args.selector).first
            if locator.count() == 0:
                return ToolResult.fail(f"Elemen dengan selector '{args.selector}' tidak ditemukan di halaman.")
            raw_text = locator.inner_text(timeout=5000)
        else:
            # Default to reading body inner text
            raw_text = page.inner_text("body", timeout=5000)

        # Normalize whitespace
        clean_text = "\n".join(line.strip() for line in raw_text.splitlines() if line.strip())
        is_truncated = len(clean_text) > args.max_chars
        if is_truncated:
            clean_text = clean_text[:args.max_chars]

        untrusted_text = wrap_untrusted_content(clean_text, "web")

        data = {
            "url": page.url,
            "title": page.title(),
            "selector": args.selector or "body",
            "text": untrusted_text,
            "char_count": len(clean_text),
            "truncated": is_truncated,
            "untrusted": True,
        }

        summary = (
            f"Konten Halaman Browser ({data['selector']}):\n"
            f"- URL: {page.url}\n"
            f"- Panjang: {len(clean_text)} karakter{' (Dipotong)' if is_truncated else ''}\n"
            f"- Teks:\n{untrusted_text}"
        )
        return ToolResult.success(data=data, summary=summary, untrusted=True, max_summary_len=1500)
    except Exception as e:
        return ToolResult.fail(f"Gagal membaca konten browser: {e}")


@tool(
    name="browser.screenshot",
    risk=Risk.OBSERVE,
    description="Capture a screenshot of the active browser page and save to local cache with SHA-256 hash.",
    input_model=BrowserScreenshotInput,
    timeout_s=20,
    requires_elevation=False,
)
def browser_screenshot_tool(args: BrowserScreenshotInput) -> ToolResult:
    try:
        page = browser_manager.get_page()
        browser_manager.update_activity()

        if args.path:
            out_path = Path(args.path).resolve()
        else:
            cache_dir = Path("data/cache/browser").resolve()
            cache_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            out_path = cache_dir / f"screenshot_{ts}.png"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out_path), full_page=args.full_page)

        # Calculate file size and SHA-256
        data_bytes = out_path.read_bytes()
        sha256_hash = hashlib.sha256(data_bytes).hexdigest()
        size_kb = round(len(data_bytes) / 1024, 1)

        data = {
            "url": page.url,
            "title": page.title(),
            "image_path": str(out_path),
            "sha256": sha256_hash,
            "size_bytes": len(data_bytes),
            "full_page": args.full_page,
            "untrusted": True,
        }

        summary = (
            f"Tangkapan Layar Browser Berhasil Disimpan:\n"
            f"- Halaman: {page.title()} ({page.url})\n"
            f"- Lokasi File: {out_path}\n"
            f"- Ukuran: {size_kb} KB (Full page: {'Ya' if args.full_page else 'Tidak'})\n"
            f"- SHA-256: {sha256_hash[:16]}..."
        )
        return ToolResult.success(data=data, summary=summary, untrusted=True)
    except Exception as e:
        return ToolResult.fail(f"Gagal mengambil tangkapan layar browser: {e}")


@tool(
    name="browser.find_links",
    risk=Risk.OBSERVE,
    description="Find and list interactive links and buttons on the active browser page.",
    input_model=BrowserFindLinksInput,
    timeout_s=15,
    requires_elevation=False,
)
def browser_find_links_tool(args: BrowserFindLinksInput) -> ToolResult:
    try:
        page = browser_manager.get_page()
        browser_manager.update_activity()

        # Extract links and buttons via DOM evaluation
        extracted_elements = page.evaluate("""() => {
            const results = [];
            const elements = document.querySelectorAll('a[href], button, [role="button"], [role="link"], [role="tab"]');
            for (const el of elements) {
                const text = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
                const href = el.getAttribute('href') || '';
                const role = el.getAttribute('role') || el.tagName.toLowerCase();
                const id = el.id ? '#' + el.id : '';
                if (text || href) {
                    results.push({
                        tag: el.tagName.toLowerCase(),
                        role: role,
                        text: text.substring(0, 100),
                        href: href,
                        id: id
                    });
                }
            }
            return results;
        }""")

        # Filter by query if provided
        filtered = []
        q = args.query.lower() if args.query else None
        for item in extracted_elements:
            if q:
                if q not in item["text"].lower() and q not in item["href"].lower():
                    continue
            filtered.append(item)
            if len(filtered) >= args.limit:
                break

        data = {
            "url": page.url,
            "title": page.title(),
            "query": args.query,
            "total_found": len(filtered),
            "links": filtered,
            "untrusted": True,
        }

        # Build short readable summary
        lines = [f"Ditemukan {len(filtered)} tautan/tombol di '{page.title()}':"]
        for idx, item in enumerate(filtered[:10], start=1):
            target_desc = f" ({item['href']})" if item['href'] else ""
            lines.append(f"{idx}. [{item['role']}] \"{item['text']}\"{target_desc}")
        if len(filtered) > 10:
            lines.append(f"... dan {len(filtered) - 10} lainnya.")

        return ToolResult.success(
            data=data,
            summary="\n".join(lines),
            untrusted=True,
            max_summary_len=1500,
        )
    except Exception as e:
        return ToolResult.fail(f"Gagal mencari link di browser: {e}")


@tool(
    name="browser.click",
    risk=Risk.LOW_ACTION,
    description="Click a link, button, or interactive element in the active browser page with policy enforcement (L2 navigation / L3 confirm / L0 blocked).",
    input_model=BrowserClickInput,
    timeout_s=15,
    requires_elevation=False,
)
def browser_click_tool(args: BrowserClickInput) -> ToolResult:
    try:
        page = browser_manager.get_page()
        browser_manager.update_activity()

        # Locate element
        if args.selector:
            locator = page.locator(args.selector).first
        elif args.role and args.text:
            locator = page.get_by_role(args.role, name=args.text).first
        elif args.text:
            locator = page.get_by_text(args.text, exact=False).first
        else:
            return ToolResult.fail("Parameter tidak lengkap: wajib menyediakan 'selector', 'text', atau kombinasi 'role'+'text'.")

        if locator.count() == 0:
            target_str = args.selector or args.text or f"{args.role}:{args.text}"
            return ToolResult.fail(f"Elemen '{target_str}' tidak ditemukan di halaman.")

        # Live DOM inspection prior to clicking
        elem_info = locator.evaluate("""el => {
            return {
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                role: el.getAttribute('role') || el.tagName.toLowerCase(),
                name: el.getAttribute('name') || '',
                id: el.id || '',
                placeholder: el.getAttribute('placeholder') || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                autocomplete: el.getAttribute('autocomplete') || '',
                href: el.getAttribute('href') || '',
                text: (el.innerText || el.textContent || '').trim().substring(0, 100),
                isSubmit: el.type === 'submit' || (el.form && el.tagName.toLowerCase() === 'button' && (!el.type || el.type === 'submit'))
            };
        }""")

        # Classify risk dynamically
        risk_level, reason = classify_action_risk(
            action="click",
            selector=args.selector or "",
            text=args.text or elem_info["text"],
            role=elem_info["role"],
            tag=elem_info["tag"],
            input_type=elem_info["type"],
            name=elem_info["name"],
            elem_id=elem_info["id"],
            placeholder=elem_info["placeholder"],
            aria_label=elem_info["ariaLabel"],
            autocomplete=elem_info["autocomplete"],
            href=elem_info["href"],
            surrounding_text=elem_info["text"],
        )

        # L0 Check: FORBIDDEN
        if risk_level == Risk.FORBIDDEN:
            return ToolResult.fail(
                f"Pelanggaran Kebijakan Keamanan (L0 FORBIDDEN): {reason}. Aksi klik dibatalkan."
            )

        # L3 Check: Explicit confirmation needed
        if risk_level == Risk.CONFIRM and not args.confirmed:
            return ToolResult.fail(
                f"Aksi klik berisiko tinggi (L3): {reason}. Operasi membutuhkan konfirmasi pengguna. Set confirmed=True untuk menyetujui."
            )

        # Perform click
        target_repr = f"<{elem_info['tag']} id='{elem_info['id']}' text='{elem_info['text'][:30]}'>"
        locator.click(timeout=8000)

        # Allow slight delay for DOM reaction / navigation
        page.wait_for_timeout(500)
        browser_manager.update_activity()

        data = {
            "status": "clicked",
            "target": target_repr,
            "element": elem_info,
            "risk_level": risk_level.name,
            "current_url": page.url,
            "current_title": page.title(),
            "untrusted": True,
        }

        summary = (
            f"Klik Elemen Berhasil ({risk_level.name}):\n"
            f"- Target: {target_repr}\n"
            f"- Halaman Sekarang: {page.title()} ({page.url})"
        )
        return ToolResult.success(data=data, summary=summary, untrusted=True)
    except Exception as e:
        return ToolResult.fail(f"Gagal melakukan klik pada browser: {e}")


@tool(
    name="browser.type",
    risk=Risk.LOW_ACTION,
    description="Type text into an input field in the active browser page with strict security checks (passwords and credentials are L0 FORBIDDEN).",
    input_model=BrowserTypeInput,
    timeout_s=15,
    requires_elevation=False,
)
def browser_type_tool(args: BrowserTypeInput) -> ToolResult:
    try:
        page = browser_manager.get_page()
        browser_manager.update_activity()

        locator = page.locator(args.selector).first
        if locator.count() == 0:
            return ToolResult.fail(f"Input field dengan selector '{args.selector}' tidak ditemukan.")

        # Live DOM inspection prior to typing
        elem_info = locator.evaluate("""el => {
            return {
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                role: el.getAttribute('role') || el.tagName.toLowerCase(),
                name: el.getAttribute('name') || '',
                id: el.id || '',
                placeholder: el.getAttribute('placeholder') || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                autocomplete: el.getAttribute('autocomplete') || '',
                value: el.value || ''
            };
        }""")

        # Classify risk dynamically
        risk_level, reason = classify_action_risk(
            action="type",
            selector=args.selector,
            text=args.text,
            role=elem_info["role"],
            tag=elem_info["tag"],
            input_type=elem_info["type"],
            name=elem_info["name"],
            elem_id=elem_info["id"],
            placeholder=elem_info["placeholder"],
            aria_label=elem_info["ariaLabel"],
            autocomplete=elem_info["autocomplete"],
            surrounding_text=f"{elem_info['placeholder']} {elem_info['name']} {elem_info['id']}",
        )

        # L0 Check: FORBIDDEN for passwords, credentials, payment, CAPTCHA
        if risk_level == Risk.FORBIDDEN:
            return ToolResult.fail(
                f"Pelanggaran Kebijakan Keamanan (L0 FORBIDDEN): {reason}. Pengetikan kredensial/rahasia dibatalkan."
            )

        # L3 Check: Confirmation for ambiguous/high-risk input
        if risk_level == Risk.CONFIRM and not args.confirmed:
            return ToolResult.fail(
                f"Pengetikan berisiko tinggi (L3): {reason}. Membutuhkan konfirmasi pengguna. Set confirmed=True untuk menyetujui."
            )

        # Perform typing
        if args.clear_first:
            locator.fill("")

        locator.fill(args.text, timeout=8000)
        browser_manager.update_activity()

        data = {
            "status": "typed",
            "selector": args.selector,
            "chars_typed": len(args.text),
            "input_type": elem_info["type"],
            "risk_level": risk_level.name,
            "current_url": page.url,
            "untrusted": True,
        }

        summary = (
            f"Pengetikan Berhasil ({risk_level.name}):\n"
            f"- Selector: {args.selector}\n"
            f"- Karakter: {len(args.text)} karakter dimasukkan\n"
            f"- Target URL: {page.url}"
        )
        return ToolResult.success(data=data, summary=summary, untrusted=True)
    except Exception as e:
        return ToolResult.fail(f"Gagal mengetik ke input field '{args.selector}': {e}")
