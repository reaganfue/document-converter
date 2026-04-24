
import os, sys, time, json
from playwright.sync_api import sync_playwright

screenshots_dir = r"C:/Users/User/Desktop/文件轉檔/.execution/screenshots"
os.makedirs(screenshots_dir, exist_ok=True)

results = {}
all_console_errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        accept_downloads=True
    )
    page = context.new_page()
    
    def on_console(msg):
        if msg.type == "error":
            all_console_errors.append({"type": msg.type, "text": msg.text})
    page.on("console", on_console)
    
    page.goto("http://localhost:5000", wait_until="networkidle")
    time.sleep(2)
    
    # 1. TITLE
    title = page.title()
    results["title"] = title
    results["title_pass"] = (title == "文件轉檔工具")
    print(f"[TITLE] {title} => {results[chr(39)+chr(116)+chr(105)+chr(116)+chr(108)+chr(101)+chr(95)+chr(112)+chr(97)+chr(115)+chr(115)+chr(39)]}")
    
    # 2. HERO BADGES
    page.screenshot(path=screenshots_dir + "/e2e_p4c_01_hero_1440.png")
    badges = page.evaluate("""() => ({
        has_free: document.body.innerText.includes("永久免費"),
        has_offline: document.body.innerText.includes("離線運行"),
        has_unlimited: document.body.innerText.includes("無限制")
    })""")
    results["hero_badges"] = badges
    results["hero_badges_pass"] = badges["has_free"] and badges["has_offline"] and badges["has_unlimited"]
    print(f"[BADGES] {badges}")

print(json.dumps(results, ensure_ascii=False, indent=2))
