import asyncio
import re
from playwright.async_api import Playwright, async_playwright, expect


async def run(playwright: Playwright) -> None:
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context(storage_state="booking_storage.json")
    page = await context.new_page()
    await page.goto("https://booking.fudan.edu.cn/reservation/fe/site/reservationInfo?id=751")
    await page.get_by_role("button", name="确定").click()
    await page.get_by_text("后一天").click()
    await page.locator("tr:nth-child(7) > td:nth-child(7) > .cell-content > .item_content_box").click()
    await page.get_by_role("button", name="确认预约").click()
    await page.goto("https://booking.fudan.edu.cn/reservation/fe/site/reservationInfo?id=751")
    await page.get_by_role("button", name="确定").click()
    await page.get_by_text("后一天").click()
    await page.locator("tr:nth-child(7) > td:nth-child(6) > .cell-content > .item_content_box > p").click()
    await page.get_by_role("button", name="确认预约").click()
    await page.get_by_role("textbox", name="请输入专业").click()
    await page.get_by_role("textbox", name="请输入专业").click()
    await page.get_by_role("textbox", name="请输入专业").fill("081200")
    await page.get_by_role("textbox", name="请输入邮箱").click()
    await page.get_by_role("textbox", name="请输入邮箱").press("CapsLock")
    await page.get_by_role("textbox", name="请输入邮箱").fill("xxx@m.fudan.edu.cn")
    await page.get_by_role("textbox", name="请输入手机号").click()
    await page.get_by_role("textbox", name="请输入手机号").fill("138xxxxxxxx")
    await page.get_by_role("textbox", name="（需包含活动简介和参与人数）").click()
    await page.get_by_role("textbox", name="（需包含活动简介和参与人数）").press("CapsLock")
    await page.get_by_role("textbox", name="（需包含活动简介和参与人数）").press("Unidentified")
    await page.get_by_role("textbox", name="（需包含活动简介和参与人数）").fill("打台球")
    await page.get_by_role("button", name="点击上传含负责老师签字（盖章）的申请表扫描件").click()
    await page.get_by_role("button", name="点击上传含负责老师签字（盖章）的申请表扫描件").set_input_files("application.pdf")
    await page.get_by_role("button", name="立即提交").click()
    await page.get_by_role("button", name="确认").click()
    await page.get_by_role("button", name="取消预约").click()
    await page.get_by_role("button", name="确认").click()

    # ---------------------
    await context.close()
    await browser.close()


async def main() -> None:
    async with async_playwright() as playwright:
        await run(playwright)


asyncio.run(main())
