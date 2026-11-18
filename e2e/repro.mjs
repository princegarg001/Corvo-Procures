import { chromium } from "@playwright/test";
const BASE = process.env.BASE_URL;
const b = await chromium.launch();
const page = await b.newPage();
const errs = [];
page.on("pageerror", (e) => errs.push(e.message.slice(0, 120)));
// simulate an extension/polyfill whose scrollIntoView returns a value instead of undefined
await page.addInitScript(() => { Element.prototype.scrollIntoView = function () { return { done: true }; }; });
await page.goto(BASE + "/"); await page.evaluate(() => localStorage.setItem("corvo.user", "Rahul"));
await page.goto(BASE + "/chat", { waitUntil: "networkidle" }); await page.waitForTimeout(1500);
const crashed = await page.getByText("This page hit an error").count();
const ok = await page.getByText("Raise a purchase request").count();
console.log(JSON.stringify({ crashed: crashed > 0, chatVisible: ok > 0, errs }));
await b.close();
