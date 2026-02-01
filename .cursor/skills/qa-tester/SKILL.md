---
name: qa-tester
description: QA testing with Playwright for E2E testing, test automation, test strategy, and quality assurance best practices. Use when writing tests, creating test plans, automating UI tests, or when the user mentions testing, QA, Playwright, or quality assurance.
---

# QA Tester

## Test Strategy

### Testing Pyramid

```
        /\        E2E Tests (Few)
       /  \       - Critical user journeys
      /    \      - Happy paths + key edge cases
     /------\     
    /        \    Integration Tests (Some)
   /          \   - API contracts
  /            \  - Database operations
 /--------------\ 
/                \ Unit Tests (Many)
                   - Business logic
                   - Utilities
                   - Pure functions
```

**Prioritize:**
1. **Unit tests** - Fast, isolated, many
2. **Integration tests** - API/DB interactions
3. **E2E tests** - Critical user flows only

## Playwright E2E Testing

### Project Setup

```typescript
// playwright.config.ts
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html'],
    ['json', { outputFile: 'test-results/results.json' }],
    ['junit', { outputFile: 'test-results/junit.xml' }]
  ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
  },
})
```

### Page Object Model (POM)

Encapsulate page interactions for maintainability:

```typescript
// pages/LoginPage.ts
import { Page, Locator } from '@playwright/test'

export class LoginPage {
  readonly page: Page
  readonly emailInput: Locator
  readonly passwordInput: Locator
  readonly loginButton: Locator
  readonly errorMessage: Locator

  constructor(page: Page) {
    this.page = page
    this.emailInput = page.getByLabel('Email')
    this.passwordInput = page.getByLabel('Password')
    this.loginButton = page.getByRole('button', { name: 'Log in' })
    this.errorMessage = page.getByTestId('error-message')
  }

  async goto() {
    await this.page.goto('/login')
  }

  async login(email: string, password: string) {
    await this.emailInput.fill(email)
    await this.passwordInput.fill(password)
    await this.loginButton.click()
  }

  async expectError(message: string) {
    await expect(this.errorMessage).toContainText(message)
  }
}

// pages/DashboardPage.ts
export class DashboardPage {
  readonly page: Page
  readonly welcomeMessage: Locator
  readonly logoutButton: Locator

  constructor(page: Page) {
    this.page = page
    this.welcomeMessage = page.getByTestId('welcome-message')
    this.logoutButton = page.getByRole('button', { name: 'Log out' })
  }

  async expectLoggedIn(userName: string) {
    await expect(this.welcomeMessage).toContainText(`Welcome, ${userName}`)
  }

  async logout() {
    await this.logoutButton.click()
  }
}
```

### Test Structure

```typescript
// tests/auth.spec.ts
import { test, expect } from '@playwright/test'
import { LoginPage } from '../pages/LoginPage'
import { DashboardPage } from '../pages/DashboardPage'

test.describe('Authentication', () => {
  let loginPage: LoginPage
  let dashboardPage: DashboardPage

  test.beforeEach(async ({ page }) => {
    loginPage = new LoginPage(page)
    dashboardPage = new DashboardPage(page)
    await loginPage.goto()
  })

  test('successful login with valid credentials', async ({ page }) => {
    await loginPage.login('user@example.com', 'password123')
    
    // Verify redirect to dashboard
    await expect(page).toHaveURL('/dashboard')
    await dashboardPage.expectLoggedIn('John Doe')
  })

  test('failed login with invalid credentials', async () => {
    await loginPage.login('invalid@example.com', 'wrongpassword')
    
    // Should stay on login page
    await expect(loginPage.page).toHaveURL('/login')
    await loginPage.expectError('Invalid credentials')
  })

  test('validation errors for empty fields', async () => {
    await loginPage.loginButton.click()
    
    // Check for validation messages
    await expect(loginPage.emailInput).toHaveAttribute('aria-invalid', 'true')
    await expect(loginPage.passwordInput).toHaveAttribute('aria-invalid', 'true')
  })
})
```

### Fixtures for Test Data

```typescript
// fixtures/auth.fixture.ts
import { test as base } from '@playwright/test'
import { LoginPage } from '../pages/LoginPage'

type AuthFixtures = {
  loginPage: LoginPage
  authenticatedPage: Page
}

export const test = base.extend<AuthFixtures>({
  loginPage: async ({ page }, use) => {
    const loginPage = new LoginPage(page)
    await loginPage.goto()
    await use(loginPage)
  },
  
  authenticatedPage: async ({ page }, use) => {
    // Login before each test
    const loginPage = new LoginPage(page)
    await loginPage.goto()
    await loginPage.login('user@example.com', 'password123')
    await page.waitForURL('/dashboard')
    await use(page)
  },
})

// Usage
import { test } from './fixtures/auth.fixture'

test('user can update profile', async ({ authenticatedPage }) => {
  // Test starts already authenticated
  await authenticatedPage.goto('/profile')
  // ... test profile update
})
```

### API Testing with Playwright

```typescript
// tests/api/users.spec.ts
import { test, expect } from '@playwright/test'

test.describe('User API', () => {
  let authToken: string

  test.beforeAll(async ({ request }) => {
    // Get auth token
    const response = await request.post('/api/auth/login', {
      data: {
        email: 'admin@example.com',
        password: 'admin123'
      }
    })
    const data = await response.json()
    authToken = data.token
  })

  test('GET /api/users returns user list', async ({ request }) => {
    const response = await request.get('/api/users', {
      headers: {
        'Authorization': `Bearer ${authToken}`
      }
    })
    
    expect(response.ok()).toBeTruthy()
    const users = await response.json()
    expect(Array.isArray(users)).toBeTruthy()
    expect(users.length).toBeGreaterThan(0)
  })

  test('POST /api/users creates new user', async ({ request }) => {
    const newUser = {
      name: 'Test User',
      email: `test-${Date.now()}@example.com`,
      password: 'password123'
    }
    
    const response = await request.post('/api/users', {
      headers: {
        'Authorization': `Bearer ${authToken}`
      },
      data: newUser
    })
    
    expect(response.status()).toBe(201)
    const user = await response.json()
    expect(user.email).toBe(newUser.email)
    expect(user).not.toHaveProperty('password')
  })

  test('GET /api/users/:id returns 404 for nonexistent user', async ({ request }) => {
    const response = await request.get('/api/users/99999', {
      headers: {
        'Authorization': `Bearer ${authToken}`
      }
    })
    
    expect(response.status()).toBe(404)
  })
})
```

### Visual Regression Testing

```typescript
// tests/visual/homepage.spec.ts
import { test, expect } from '@playwright/test'

test.describe('Visual Regression', () => {
  test('homepage looks correct', async ({ page }) => {
    await page.goto('/')
    
    // Wait for page to be fully loaded
    await page.waitForLoadState('networkidle')
    
    // Take screenshot and compare
    await expect(page).toHaveScreenshot('homepage.png', {
      fullPage: true,
      maxDiffPixels: 100
    })
  })

  test('mobile homepage looks correct', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    
    await expect(page).toHaveScreenshot('homepage-mobile.png')
  })

  test('component in different states', async ({ page }) => {
    await page.goto('/components/button')
    
    const button = page.getByRole('button', { name: 'Submit' })
    
    // Default state
    await expect(button).toHaveScreenshot('button-default.png')
    
    // Hover state
    await button.hover()
    await expect(button).toHaveScreenshot('button-hover.png')
    
    // Disabled state
    await page.evaluate(() => {
      document.querySelector('button')?.setAttribute('disabled', 'true')
    })
    await expect(button).toHaveScreenshot('button-disabled.png')
  })
})
```

### Accessibility Testing

```typescript
// tests/a11y/homepage.spec.ts
import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test.describe('Accessibility', () => {
  test('homepage has no accessibility violations', async ({ page }) => {
    await page.goto('/')
    
    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    
    expect(accessibilityScanResults.violations).toEqual([])
  })

  test('form has proper labels and ARIA attributes', async ({ page }) => {
    await page.goto('/contact')
    
    // Check for labels
    const nameInput = page.getByLabel('Name')
    await expect(nameInput).toBeVisible()
    
    const emailInput = page.getByLabel('Email')
    await expect(emailInput).toHaveAttribute('type', 'email')
    await expect(emailInput).toHaveAttribute('required')
    
    // Check ARIA attributes
    const submitButton = page.getByRole('button', { name: 'Submit' })
    await expect(submitButton).toHaveAttribute('type', 'submit')
  })
})
```

## Test Data Management

```typescript
// fixtures/testData.ts
export const testUsers = {
  admin: {
    email: 'admin@example.com',
    password: 'admin123',
    role: 'admin'
  },
  regularUser: {
    email: 'user@example.com',
    password: 'user123',
    role: 'user'
  }
}

export function generateUniqueEmail() {
  return `test-${Date.now()}-${Math.random().toString(36).substr(2, 9)}@example.com`
}

// tests/helpers/database.ts
export async function seedTestData(db: any) {
  await db.user.createMany({
    data: [
      { name: 'Admin User', email: testUsers.admin.email },
      { name: 'Regular User', email: testUsers.regularUser.email }
    ]
  })
}

export async function cleanupTestData(db: any) {
  await db.user.deleteMany({
    where: { email: { contains: 'test-' } }
  })
}
```

## Test Execution Strategy

### Run Tests Efficiently

```bash
# Run all tests
npx playwright test

# Run specific file
npx playwright test tests/auth.spec.ts

# Run tests in headed mode (see browser)
npx playwright test --headed

# Run in debug mode
npx playwright test --debug

# Run specific test by name
npx playwright test -g "successful login"

# Run tests in specific browser
npx playwright test --project=chromium

# Run in parallel (default is auto)
npx playwright test --workers=4

# Update snapshots
npx playwright test --update-snapshots
```

## Test Reporting

```typescript
// Custom reporter
class CustomReporter {
  onTestEnd(test, result) {
    if (result.status === 'failed') {
      console.log(`❌ ${test.title} - ${result.error.message}`)
    } else {
      console.log(`✅ ${test.title}`)
    }
  }
}

export default CustomReporter
```

## Best Practices

1. **Use test IDs** - Add `data-testid` for reliable selectors
2. **Keep tests independent** - Each test should work in isolation
3. **Use Page Object Model** - Encapsulate page logic
4. **Wait for conditions** - Use auto-waiting, avoid fixed waits
5. **Test user flows, not implementation** - Test what users do
6. **Parallelize tests** - Run tests concurrently for speed
7. **Use fixtures** - Share setup code efficiently
8. **Clean up test data** - Don't leave orphaned data
9. **Use meaningful assertions** - Clear error messages
10. **Test edge cases** - Empty states, errors, boundaries

## Common Pitfalls

❌ **Don't:** Use `waitForTimeout()` - use `waitForSelector()` instead
✅ **Do:** Let Playwright auto-wait for elements

❌ **Don't:** Test implementation details
✅ **Do:** Test user-facing behavior

❌ **Don't:** Have dependent tests (test2 needs test1)
✅ **Do:** Make each test independent with proper setup

❌ **Don't:** Use brittle selectors (CSS classes, XPath)
✅ **Do:** Use semantic selectors (role, label, test IDs)

❌ **Don't:** Skip test cleanup
✅ **Do:** Clean up test data after tests

## Test Coverage Goals

- **Critical paths**: 100% (login, checkout, payment)
- **Core features**: 80-90%
- **Edge cases**: Cover known issues
- **Happy path + error scenarios**: Both required
