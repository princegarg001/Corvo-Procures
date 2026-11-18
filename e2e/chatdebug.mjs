import { chromium } from "@playwright/test";
const BASE = process.env.BASE_URL || "https://corvo-procure.onrender.com";
const b = await chromium.launch();
for (const user of [null, "Asha", "Rahul", "Meera"]) {
  const ctx = await b.newContext({ viewport: { width: 1400, height: 800 } });
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push("PAGEERROR " + e.message.slice(0, 200)));
  page.on("console", (m) => m.type() === "error" && errs.push("console " + m.text().slice(0, 200)));
  page.on("response", (r) => r.status() >= 400 && errs.push(`HTTP ${r.status()} ${r.url()}`));
  await page.goto(BASE + "/");
  if (user) await page.evaluate((u) => localStorage.setItem("corvo.user", u), user);
  await page.goto(BASE + "/chat", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  const rootLen = await page.evaluate(() => document.getElementById("root").innerHTML.length);
  console.log(`user=${user ?? "(fresh)"} rootHtml=${rootLen} errors=${JSON.stringify(errs)}`);
  await ctx.close();
}
await b.close();
