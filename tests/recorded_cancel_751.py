import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(storage_state="booking_storage.json")
    page = context.new_page()
    page.goto("https://booking.fudan.edu.cn/reservation/fe/site/myReservation")
    page.get_by_role("button", name="取消预约").click()
    page.get_by_role("button", name="确认").click()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
