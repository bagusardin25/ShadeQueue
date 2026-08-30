import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const out = join(root, '..', '.ui-ux-evidence')
mkdirSync(out, { recursive: true })
const origin = process.env.ORIGIN ?? 'http://127.0.0.1:4173'

const browser = await chromium.launch({ headless: true })

async function capture(name, viewport, interact) {
  const context = await browser.newContext({ viewport })
  const page = await context.newPage()
  await page.goto(`${origin}/scenarios/phoenix-central-fixture`, { waitUntil: 'networkidle', timeout: 60_000 })
  await page.waitForSelector('#map-stop-details', { timeout: 20_000 })
  await page.locator('#corridor-map').scrollIntoViewIfNeeded()
  await page.waitForTimeout(800)
  if (interact) await interact(page)
  await page.screenshot({ path: join(out, name), fullPage: false })
  const details = await page.locator('#map-stop-details').innerText()
  console.log(name, details.replaceAll('\n', ' | '))
  await context.close()
}

await capture('map-details-desktop.png', { width: 1440, height: 900 })
await capture('map-details-desktop-pin.png', { width: 1440, height: 900 }, async (page) => {
  const buttons = page.locator('#stops-table button')
  const count = await buttons.count()
  if (count > 2) await buttons.nth(2).click()
  await page.waitForTimeout(1200)
})
await capture('map-details-mobile.png', { width: 390, height: 844 })

await browser.close()
console.log('done')
