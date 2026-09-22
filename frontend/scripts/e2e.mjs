import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const baseUrl = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8080";
const executablePath =
  process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const outputDirectory = resolve(import.meta.dirname, "../../docs/assets");
const scenarios = [
  ["stable-k5", "Сохранить настройки"],
  ["sulfur-shock", "Рекомендуется модельное изменение"],
  ["operator-wins", "Рекомендуется модельное изменение"],
  ["missing-data", "Недостаточно данных"],
  ["cetane-blending", "Сохранить настройки"],
];

await mkdir(outputDirectory, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(error.message));

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "АВТ → гидроочистка → блендинг" }).waitFor();
  for (const [preset, expected] of scenarios) {
    await page.locator(".preset-panel select").selectOption(preset);
    const response = page.waitForResponse(
      (item) => item.url().endsWith("/api/v1/modelled-runs") && item.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Рассчитать цепочку" }).click();
    const completed = await response;
    if (!completed.ok()) throw new Error(`${preset}: API returned ${completed.status()}`);
    await page.locator(".result-hero h2").getByText(expected, { exact: true }).waitFor();
    await page.screenshot({
      path: resolve(outputDirectory, `dashboard-${preset}.png`),
      fullPage: true,
    });
    process.stdout.write(`PASS ${preset}: ${expected}\n`);
  }
  if (consoleErrors.length) {
    throw new Error(`Browser console errors:\n${consoleErrors.join("\n")}`);
  }
} finally {
  await browser.close();
}
