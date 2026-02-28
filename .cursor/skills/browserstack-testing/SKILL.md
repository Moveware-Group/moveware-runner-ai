---
name: browserstack-testing
description: BrowserStack cross-browser and device testing for responsive design validation, accessibility scanning, and multi-platform QA. Use when testing responsiveness, cross-browser compatibility, or when BrowserStack is mentioned.
---

# BrowserStack Testing

## Overview

BrowserStack provides access to 3,500+ real devices and browsers for testing web and mobile applications. This skill covers cross-browser testing, responsive design validation, and accessibility scanning via the BrowserStack MCP server.

## MCP Server (Cursor IDE)

The BrowserStack MCP server is configured at `.cursor/mcp.json` and runs locally via npx. It requires `BROWSERSTACK_USERNAME` and `BROWSERSTACK_ACCESS_KEY` environment variables.

**Available MCP tools (20+):**
- Run Selenium/Playwright/Cypress tests across browsers
- Run Appium/XCUITest/Espresso tests on real devices
- Scan for accessibility (WCAG) violations
- Generate test cases from PRD documents
- Launch live browser/device testing sessions
- View test results and screenshots

## Responsive Design Testing

### Viewport Configuration

Test across standard breakpoints used in modern web design:

| Breakpoint | Width | Devices |
|-----------|-------|---------|
| Mobile S | 320px | iPhone SE |
| Mobile M | 375px | iPhone 12/13/14 |
| Mobile L | 425px | iPhone Plus models |
| Tablet | 768px | iPad Mini, iPad |
| Laptop | 1024px | iPad Pro, small laptops |
| Desktop | 1440px | Standard desktops |
| 4K | 2560px | Large monitors |

### Playwright + BrowserStack

```typescript
// browserstack.config.ts
import { defineConfig } from "@playwright/test"

const bsCapabilities = {
  "browser": "chrome",
  "browser_version": "latest",
  "os": "Windows",
  "os_version": "11",
  "browserstack.username": process.env.BROWSERSTACK_USERNAME,
  "browserstack.accessKey": process.env.BROWSERSTACK_ACCESS_KEY,
  "build": `responsive-test-${Date.now()}`,
  "name": "Responsive Design Validation",
}

export default defineConfig({
  use: {
    connectOptions: {
      wsEndpoint: `wss://cdp.browserstack.com/playwright?caps=${encodeURIComponent(JSON.stringify(bsCapabilities))}`,
    },
  },
})
```

### Responsive Test Pattern

```typescript
import { test, expect } from "@playwright/test"

const viewports = [
  { name: "mobile", width: 375, height: 812 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1440, height: 900 },
]

for (const vp of viewports) {
  test(`layout is correct at ${vp.name} (${vp.width}x${vp.height})`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height })
    await page.goto("/")
    await page.waitForLoadState("networkidle")

    // Navigation collapses to hamburger on mobile
    if (vp.width < 768) {
      await expect(page.getByTestId("mobile-menu-toggle")).toBeVisible()
      await expect(page.getByTestId("desktop-nav")).toBeHidden()
    } else {
      await expect(page.getByTestId("desktop-nav")).toBeVisible()
    }

    // No horizontal overflow
    const body = page.locator("body")
    const scrollWidth = await body.evaluate((el) => el.scrollWidth)
    const clientWidth = await body.evaluate((el) => el.clientWidth)
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth)

    await expect(page).toHaveScreenshot(`homepage-${vp.name}.png`, {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    })
  })
}
```

## Accessibility Scanning

### Using BrowserStack Accessibility

```typescript
test("page meets WCAG 2.1 AA standards", async ({ page }) => {
  await page.goto("/")

  // BrowserStack's accessibility scanner via MCP
  // In Cursor, use the MCP tool: browserstack_accessibility_scan
  // Programmatically via @axe-core:
  const AxeBuilder = require("@axe-core/playwright").default
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze()

  expect(results.violations).toEqual([])
})
```

## Cross-Browser Test Matrix

Target the browsers that matter for your audience:

```typescript
const browsers = [
  { os: "Windows", os_version: "11", browser: "chrome", browser_version: "latest" },
  { os: "Windows", os_version: "11", browser: "firefox", browser_version: "latest" },
  { os: "Windows", os_version: "11", browser: "edge", browser_version: "latest" },
  { os: "OS X", os_version: "Sonoma", browser: "safari", browser_version: "latest" },
  { os: "OS X", os_version: "Sonoma", browser: "chrome", browser_version: "latest" },
]

const mobileDevices = [
  { device: "iPhone 15", os_version: "17", browser: "safari" },
  { device: "Samsung Galaxy S24", os_version: "14.0", browser: "chrome" },
  { device: "Google Pixel 8", os_version: "14.0", browser: "chrome" },
  { device: "iPad Pro 12.9 2022", os_version: "16", browser: "safari" },
]
```

## CI/CD Integration

```yaml
# .github/workflows/browserstack.yml
name: BrowserStack Tests
on:
  pull_request:
    branches: [main]

jobs:
  responsive-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: npm ci
      - run: npx playwright install
      - run: npx playwright test --config=browserstack.config.ts
        env:
          BROWSERSTACK_USERNAME: ${{ secrets.BROWSERSTACK_USERNAME }}
          BROWSERSTACK_ACCESS_KEY: ${{ secrets.BROWSERSTACK_ACCESS_KEY }}
```

## Best Practices

1. **Test real devices** - Emulators miss rendering quirks; use BrowserStack's real device cloud
2. **Prioritize by analytics** - Focus testing on your actual user browser/device distribution
3. **Visual regression** - Screenshot comparisons catch layout shifts across browsers
4. **Test touch interactions** - Swipe, pinch, long-press behave differently on real devices
5. **Network throttling** - Test on 3G/4G to catch performance issues on slow connections
6. **Parallelize** - Run cross-browser tests in parallel to keep CI fast
