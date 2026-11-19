// Driven by test_inventory_onboarding.py against a temporary project.
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

async function main() {
  const [url, workbook] = process.argv.slice(2);
  const browser = await chromium.launch({ executablePath: process.env.NOTEBOOK_TEST_BROWSER || undefined });
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(8000);
    const upload = page.getByLabel("Upload inventory workbook", { exact: true });
    await page.goto(url);
    await upload.waitFor();
    await page.getByRole("button", { name: "Open a demo notebook" }).click();
    await page.getByRole("heading", { name: "Demo notebook", exact: true }).waitFor();
    await page.goto(url + "#/inventory");
    await page.getByText(/Demo inventory\. Bottle locations/).waitFor();
    await page.getByRole("row").filter({ hasText: /Acetone/i }).waitFor();

    await page.goto(url + "#/start");
    await page.getByLabel("Notebook folder name").fill("My notebook");
    await page.getByRole("button", { name: "Create notebook" }).click();
    await page.getByRole("heading", { name: "My notebook", exact: true }).waitFor();
    await upload.waitFor();
    await page.goto(url + "#/inventory");
    await page.getByText("This project has no inventory yet.").waitFor();
    await upload.setInputFiles(workbook);
    await page.getByRole("combobox", { name: "Search inventory" }).fill("64-17-5");
    await page.getByRole("row").filter({ hasText: /ethanol/i }).waitFor();
    await page.goto(url + "#/");
    await page.reload();
    await page.getByRole("heading", { name: "My notebook", exact: true }).waitFor();
    assert.equal(await upload.count(), 0);
  } finally {
    await browser.close();
  }
}

main().catch(err => { console.error(err); process.exitCode = 1; });
