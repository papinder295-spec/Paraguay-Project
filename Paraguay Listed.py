"""
BCP Paraguay - Emisores > Estados Contables
1. Company select karta hai
2. "Estados Contables" tab kholta hai
3. Sabhi year/month document links padhta hai
4. Sabse latest year + usme sabse latest month ka document download karta hai
5. Use ek ZIP file mein save karta hai

Usage:
    python emisor_estados_zip.py "AUTOMAQ S.A.E.C.A."
"""

import re
import sys
import unicodedata
import zipfile
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

URL = "https://www.bcp.gov.py/emisores"

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def norm(text: str) -> str:
    """Accent aur case hata kar compare karne ke liye."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return text.lower().strip()


def select_company(page: Page, company: str) -> None:
    """Dropdown kholkar company ka naam type karke select karta hai."""
    trigger = page.get_by_text("Seleccione una emisora").first
    if trigger.count() == 0:
        trigger = page.locator("[role='combobox'], input[placeholder*='emisora' i]").first
    trigger.click()
    page.keyboard.type(company, delay=60)
    page.wait_for_timeout(800)

    option = page.get_by_role("option", name=company, exact=True).first
    if option.count() == 0:
        option = page.get_by_text(company, exact=True).first
    option.click(timeout=10000)
    page.wait_for_timeout(1500)


def open_estados_contables(page: Page) -> None:
    page.get_by_text("Estados Contables", exact=True).first.click(timeout=15000)
    page.wait_for_selector("a[href*='/documents/d/']", timeout=20000)
    page.wait_for_timeout(1000)


def collect_docs(page: Page) -> list[dict]:
    """Sabhi document links nikaalta hai, year/month ke saath."""
    raw = page.eval_on_selector_all(
        "a[href*='/documents/d/']",
        "els => els.map(e => ({text: (e.innerText || '').trim(), href: e.href}))",
    )

    docs, seen = [], set()
    for item in raw:
        url = item["href"]
        if url in seen:
            continue

        # Month: pehle text se, nahi mila to href se
        text_n = norm(item["text"])
        month = next((m for name, m in MONTHS.items() if name in text_n), None)
        if month is None:
            href_n = norm(url)
            month = next((m for name, m in MONTHS.items() if name[:3] in href_n), None)
        if month is None:
            continue

        # Year: pehle href se (asiadic2023), nahi to text se
        year_m = re.search(r"(19|20)\d{2}", url) or re.search(r"(19|20)\d{2}", item["text"])
        if not year_m:
            continue

        seen.add(url)
        docs.append({
            "year": int(year_m.group(0)),
            "month": month,
            "text": item["text"],
            "url": url,
        })

    return sorted(docs, key=lambda d: (d["year"], d["month"]))


def download_bytes(page: Page, url: str) -> tuple[bytes, str]:
    """Document download karta hai aur (bytes, extension) return karta hai."""
    resp = page.request.get(url)
    if not resp.ok:
        raise RuntimeError(f"Download fail ({resp.status}): {url}")

    ctype = resp.headers.get("content-type", "").lower()
    if "pdf" in ctype:
        ext = ".pdf"
    elif "sheet" in ctype or "excel" in ctype:
        ext = ".xlsx"
    else:
        ext = ".bin"
    return resp.body(), ext


def main(company: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        page = browser.new_page(locale="es-PY", viewport={"width": 1366, "height": 900})

        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)

        print(f"Company select ho rahi hai: {company}")
        select_company(page, company)

        print("Estados Contables khul raha hai...")
        open_estados_contables(page)

        docs = collect_docs(page)
        if not docs:
            page.screenshot(path="estados_debug.png", full_page=True)
            print("Koi document link nahi mila. estados_debug.png dekhein.")
            browser.close()
            return

        print("\nSaare documents:")
        for d in docs:
            print(f"  {d['year']} | {d['text']:<12} | {d['url']}")

        # Latest year, phir us year ka latest month
        latest_year = max(d["year"] for d in docs)
        latest_month = max(d["month"] for d in docs if d["year"] == latest_year)
        targets = [d for d in docs if d["year"] == latest_year and d["month"] == latest_month]

        label = targets[0]["text"]
        print(f"\nLatest: {latest_year} {label}")

        safe = re.sub(r"[^A-Za-z0-9]+", "_", company).strip("_")
        zip_name = f"{safe}_{latest_year}_{latest_month:02d}.zip"

        with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, d in enumerate(targets, 1):
                body, ext = download_bytes(page, d["url"])
                inner = f"{safe}_{latest_year}_{latest_month:02d}" + (f"_{i}" if len(targets) > 1 else "") + ext
                zf.writestr(inner, body)
                print(f"  Added to zip: {inner}")

        print(f"\nZIP saved: {Path(zip_name).resolve()}")
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python emisor_estados_zip.py "AUTOMAQ S.A.E.C.A."')
        sys.exit(1)
    main(" ".join(sys.argv[1:]))