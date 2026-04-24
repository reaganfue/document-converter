# -*- coding: utf-8 -*-
import os, time, json
from playwright.sync_api import sync_playwright

dp = os.path.join(os.path.expanduser("~"), "Desktop", "文件轉檔")
sd = os.path.join(dp, ".execution", "screenshots")
fx = os.path.join(dp, "tests", "fixtures")
os.makedirs(sd, exist_ok=True)
R = {}
CE = []

def ss(pg, name):
    p = os.path.join(sd, name)
    pg.screenshot(path=p)
    print("  [SS]", name)

def click_fmt(pg, fmt):
    for btn in pg.locator("button").all():
        try:
            txt = (btn.text_content() or "").strip()
            if txt == fmt:
                btn.click()
                print(f"  [FMT] {fmt}")
                return True
        except: pass
    btns = [(b.text_content() or "").strip() for b in pg.locator("button").all()]
    print(f"  [FMT] {fmt} not found. Buttons: {btns}")
    return False

def cta(pg):
    for sel in ["#convert-btn",".convert-btn","button.btn-primary","button.btn-success"]:
        try:
            pg.click(sel, timeout=1500)
            print(f"  [CTA] {sel}")
            return True
        except: pass
    return False

def wait_done(pg, n=35):
    for i in range(n):
        time.sleep(1)
        s = pg.evaluate("""|() => ({
            done: document.body.innerText.includes('完成') || document.body.innerText.includes('成功'),
            dl: document.querySelector('a[download], .download-btn') !== null
        })|""".replace("|",""""))
        if s["done"] or s["dl"]: return True
    return False

def do_dl(pg):
    try:
        with pg.expect_download(timeout=8000) as dli:
            pg.locator("a[download], .download-btn").first.click()
        dl = dli.value
        dlp = dl.path()
        sz = os.path.getsize(dlp) if dlp and os.path.exists(dlp) else 0
        print(f"  [DL] {sz} bytes")
        return sz
    except Exception as e:
        print(f"  [DL] error: {e}")
        return 0

def reset(pg):
    try:
        pg.locator("button").filter(has_text="重新開始").click(timeout=2000)
        time.sleep(1)
    except:
        pg.reload(); time.sleep(2)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width":1440,"height":900},accept_downloads=True)
    pg = ctx.new_page()
    pg.on("console", lambda m: CE.append({"t":m.type,"msg":m.text}) if m.type=="error" else None)
    pg.goto("http://localhost:5000", wait_until="networkidle")
    time.sleep(2)

    # TITLE
    t = pg.title()
    R["title"] = t
    R["title_pass"] = (t == "文件轉檔工具")
    print(f"[TITLE] {repr(t)} => {R[chr(39)+chr(116)+chr(105)+chr(116)+chr(108)+chr(101)+chr(95)+chr(112)+chr(97)+chr(115)+chr(115)+chr(39)]}")

    # HERO BADGES + screenshot
    ss(pg, "e2e_p4c_01_hero_1440.png")
    bd = pg.evaluate(''' () => ({
        f: document.body.innerText.includes('永久免費'),
        o: document.body.innerText.includes('離線運行'),
        u: document.body.innerText.includes('無限制'),
        preview: document.body.innerText.substring(0,400)
    }) ''')
    R["badges"] = {"free":bd["f"],"offline":bd["o"],"unlimited":bd["u"]}
    R["badges_pass"] = bd["f"] and bd["o"] and bd["u"]
    print(f"[BADGES] free={bd[chr(39)+chr(102)+chr(39)]} offline={bd[chr(39)+chr(111)+chr(39)]} unlimited={bd[chr(39)+chr(117)+chr(39)]}")
    print("  [preview]", bd["preview"][:250])
