---
name: security-tester
description: Comprehensive security testing across the full stack covering OWASP Top 10, authentication, authorization, input validation, and security best practices. Use when performing security reviews, penetration testing, vulnerability assessment, or when the user mentions security, vulnerabilities, or security testing.
---

# Security Tester

## Security Testing Framework

### OWASP Top 10 (2021) Checklist

Test for these critical vulnerabilities:

1. **A01: Broken Access Control**
2. **A02: Cryptographic Failures**
3. **A03: Injection**
4. **A04: Insecure Design**
5. **A05: Security Misconfiguration**
6. **A06: Vulnerable and Outdated Components**
7. **A07: Identification and Authentication Failures**
8. **A08: Software and Data Integrity Failures**
9. **A09: Security Logging and Monitoring Failures**
10. **A10: Server-Side Request Forgery (SSRF)**

## A01: Broken Access Control

### Test Scenarios

```typescript
// Test: Horizontal privilege escalation
test('user cannot access another user data', async ({ request }) => {
  // Login as user 1
  const user1Token = await getAuthToken('user1@example.com')
  
  // Try to access user 2's data
  const response = await request.get('/api/users/2/profile', {
    headers: { 'Authorization': `Bearer ${user1Token}` }
  })
  
  // Should be forbidden
  expect(response.status()).toBe(403)
})

// Test: Vertical privilege escalation
test('regular user cannot access admin endpoints', async ({ request }) => {
  const userToken = await getAuthToken('user@example.com')
  
  const response = await request.delete('/api/users/5', {
    headers: { 'Authorization': `Bearer ${userToken}` }
  })
  
  expect(response.status()).toBe(403)
})

// Test: IDOR (Insecure Direct Object Reference)
test('cannot manipulate IDs to access unauthorized resources', async ({ request }) => {
  const token = await getAuthToken('user@example.com')
  
  // Try sequential IDs
  for (let id = 1; id <= 100; id++) {
    const response = await request.get(`/api/orders/${id}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    
    if (response.ok()) {
      const order = await response.json()
      // Verify order belongs to authenticated user
      expect(order.userId).toBe(authenticatedUserId)
    }
  }
})
```

### Backend Implementation Checklist

```javascript
// ❌ BAD: No authorization check
app.get('/api/users/:id', async (req, res) => {
  const user = await User.findById(req.params.id)
  res.json(user)
})

// ✅ GOOD: Verify ownership
app.get('/api/users/:id', authenticate, async (req, res) => {
  const user = await User.findById(req.params.id)
  
  // Check if user owns resource or is admin
  if (user.id !== req.user.id && req.user.role !== 'admin') {
    return res.status(403).json({ error: 'Forbidden' })
  }
  
  res.json(user)
})
```

## A02: Cryptographic Failures

### Test Scenarios

```typescript
// Test: Sensitive data in transit
test('API uses HTTPS in production', async ({ request }) => {
  const response = await request.get('http://api.example.com/users')
  
  // Should redirect to HTTPS or reject
  expect(response.url()).toMatch(/^https:/)
})

// Test: Password storage
test('passwords are not returned in API responses', async ({ request }) => {
  const token = await getAuthToken('user@example.com')
  const response = await request.get('/api/users/me', {
    headers: { 'Authorization': `Bearer ${token}` }
  })
  
  const user = await response.json()
  expect(user).not.toHaveProperty('password')
  expect(user).not.toHaveProperty('passwordHash')
})
```

### Implementation Checklist

```javascript
// ✅ Password hashing
const bcrypt = require('bcrypt')

async function hashPassword(password) {
  const saltRounds = 12
  return await bcrypt.hash(password, saltRounds)
}

// ✅ Secure token generation
const crypto = require('crypto')

function generateSecureToken() {
  return crypto.randomBytes(32).toString('hex')
}

// ✅ Exclude sensitive fields
const user = await User.findById(id).select('-password -passwordHash')

// ✅ Use environment variables for secrets
const JWT_SECRET = process.env.JWT_SECRET
if (!JWT_SECRET) {
  throw new Error('JWT_SECRET not set')
}
```

## A03: Injection Attacks

### SQL Injection Testing

```typescript
// Test: SQL injection in query parameters
test('SQL injection is prevented', async ({ request }) => {
  const maliciousInputs = [
    "' OR '1'='1",
    "'; DROP TABLE users; --",
    "admin'--",
    "1' UNION SELECT NULL, username, password FROM users--"
  ]
  
  for (const input of maliciousInputs) {
    const response = await request.get(`/api/search?q=${encodeURIComponent(input)}`)
    
    // Should not execute SQL
    expect(response.status()).not.toBe(500)
    const data = await response.json()
    // Should return safe results or error
    expect(data).toBeDefined()
  }
})
```

### NoSQL Injection Testing

```typescript
// Test: NoSQL injection
test('NoSQL injection is prevented', async ({ request }) => {
  const response = await request.post('/api/auth/login', {
    data: {
      email: { $gt: "" },  // MongoDB operator injection
      password: { $gt: "" }
    }
  })
  
  expect(response.status()).toBe(400)  // Should reject invalid input
})
```

### XSS (Cross-Site Scripting) Testing

```typescript
// Test: XSS in user input
test('XSS is prevented', async ({ page }) => {
  const xssPayloads = [
    '<script>alert("XSS")</script>',
    '<img src=x onerror=alert("XSS")>',
    'javascript:alert("XSS")',
    '<svg/onload=alert("XSS")>'
  ]
  
  for (const payload of xssPayloads) {
    await page.goto('/profile')
    await page.fill('[name="bio"]', payload)
    await page.click('button[type="submit"]')
    
    // Check that script doesn't execute
    await page.goto('/profile')
    const bio = await page.textContent('[data-testid="bio"]')
    
    // Should be escaped/sanitized
    expect(bio).not.toContain('<script>')
    expect(bio).not.toContain('onerror=')
  }
})
```

### Implementation: Prevent Injection

```javascript
// ✅ Use parameterized queries
const user = await db.query(
  'SELECT * FROM users WHERE email = $1',
  [email]
)

// ✅ Use ORM safely
const user = await User.findOne({ 
  where: { email: email }  // Parameterized automatically
})

// ✅ Validate and sanitize input
const validator = require('validator')

function sanitizeInput(input) {
  return validator.escape(input)
}

// ✅ Use Content Security Policy
app.use((req, res, next) => {
  res.setHeader(
    'Content-Security-Policy',
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
  )
  next()
})
```

## A07: Authentication & Session Management

### Test Scenarios

```typescript
// Test: Brute force protection
test('rate limiting prevents brute force', async ({ request }) => {
  const attempts = []
  
  for (let i = 0; i < 20; i++) {
    attempts.push(
      request.post('/api/auth/login', {
        data: { email: 'user@example.com', password: 'wrong' }
      })
    )
  }
  
  const responses = await Promise.all(attempts)
  const blocked = responses.filter(r => r.status() === 429)
  
  // Should block after multiple attempts
  expect(blocked.length).toBeGreaterThan(0)
})

// Test: Session timeout
test('session expires after inactivity', async ({ page }) => {
  await page.goto('/login')
  await login(page, 'user@example.com', 'password')
  
  // Wait for session timeout (mock time if possible)
  await page.waitForTimeout(31 * 60 * 1000)  // 31 minutes
  
  await page.goto('/dashboard')
  
  // Should redirect to login
  await expect(page).toHaveURL('/login')
})

// Test: JWT token validation
test('invalid JWT is rejected', async ({ request }) => {
  const invalidTokens = [
    'invalid.token.here',
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.signature',
    ''
  ]
  
  for (const token of invalidTokens) {
    const response = await request.get('/api/users/me', {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    
    expect(response.status()).toBe(401)
  }
})
```

### Implementation Checklist

```javascript
// ✅ Strong password requirements
function validatePassword(password) {
  const minLength = 8
  const hasUpperCase = /[A-Z]/.test(password)
  const hasLowerCase = /[a-z]/.test(password)
  const hasNumbers = /\d/.test(password)
  const hasSpecialChar = /[!@#$%^&*]/.test(password)
  
  return (
    password.length >= minLength &&
    hasUpperCase &&
    hasLowerCase &&
    hasNumbers &&
    hasSpecialChar
  )
}

// ✅ Account lockout after failed attempts
let failedAttempts = {}

async function checkLoginAttempts(email) {
  const attempts = failedAttempts[email] || 0
  
  if (attempts >= 5) {
    const lockoutTime = 15 * 60 * 1000  // 15 minutes
    throw new Error('Account temporarily locked')
  }
}

// ✅ Secure session management
const session = require('express-session')

app.use(session({
  secret: process.env.SESSION_SECRET,
  resave: false,
  saveUninitialized: false,
  cookie: {
    secure: true,        // HTTPS only
    httpOnly: true,      // No JavaScript access
    maxAge: 30 * 60 * 1000,  // 30 minutes
    sameSite: 'strict'   // CSRF protection
  }
}))
```

## A05: Security Misconfiguration

### Test Scenarios

```typescript
// Test: Debug mode disabled in production
test('debug mode is disabled', async ({ request }) => {
  const response = await request.get('/api/error-test')
  const body = await response.text()
  
  // Should not expose stack traces
  expect(body).not.toContain('at Object.')
  expect(body).not.toContain('node_modules')
})

// Test: Security headers
test('security headers are set', async ({ request }) => {
  const response = await request.get('/')
  
  expect(response.headers()['x-frame-options']).toBe('DENY')
  expect(response.headers()['x-content-type-options']).toBe('nosniff')
  expect(response.headers()['strict-transport-security']).toBeDefined()
  expect(response.headers()['content-security-policy']).toBeDefined()
})

// Test: Default credentials
test('default admin credentials are changed', async ({ request }) => {
  const defaults = [
    { email: 'admin@admin.com', password: 'admin' },
    { email: 'admin', password: 'password' },
  ]
  
  for (const creds of defaults) {
    const response = await request.post('/api/auth/login', { data: creds })
    expect(response.status()).not.toBe(200)
  }
})
```

### Implementation Checklist

```javascript
// ✅ Use helmet for security headers
const helmet = require('helmet')
app.use(helmet())

// ✅ Remove sensitive headers
app.disable('x-powered-by')

// ✅ CORS configuration
const cors = require('cors')
app.use(cors({
  origin: process.env.ALLOWED_ORIGINS.split(','),
  credentials: true
}))

// ✅ Environment-based configuration
if (process.env.NODE_ENV === 'production') {
  app.use(compression())
  app.use(morgan('combined'))
} else {
  app.use(morgan('dev'))
}
```

## CSRF Protection

```typescript
// Test: CSRF token validation
test('CSRF protection is enabled', async ({ page, request }) => {
  await page.goto('/profile')
  
  // Extract CSRF token from page
  const csrfToken = await page.getAttribute('[name="_csrf"]', 'value')
  
  // Request without token should fail
  let response = await request.post('/api/profile', {
    data: { name: 'New Name' }
  })
  expect(response.status()).toBe(403)
  
  // Request with token should succeed
  response = await request.post('/api/profile', {
    data: { name: 'New Name' },
    headers: { 'X-CSRF-Token': csrfToken }
  })
  expect(response.ok()).toBeTruthy()
})
```

## Security Testing Checklist

### Authentication & Authorization
- [ ] Password requirements enforced
- [ ] Passwords hashed with bcrypt/argon2
- [ ] Rate limiting on login attempts
- [ ] Account lockout after failed attempts
- [ ] Session timeout implemented
- [ ] JWT tokens properly validated
- [ ] Token expiration enforced
- [ ] Refresh token rotation
- [ ] Authorization checked on every endpoint
- [ ] IDOR vulnerabilities prevented

### Input Validation
- [ ] All inputs validated and sanitized
- [ ] SQL injection prevented
- [ ] NoSQL injection prevented
- [ ] XSS prevented (output encoding)
- [ ] File upload validation (type, size, content)
- [ ] Path traversal prevented
- [ ] Command injection prevented

### Data Protection
- [ ] HTTPS enforced in production
- [ ] Sensitive data encrypted at rest
- [ ] Sensitive data not logged
- [ ] Passwords never returned in responses
- [ ] PII properly protected
- [ ] Secure headers configured

### Configuration
- [ ] Debug mode disabled in production
- [ ] Error messages don't expose internals
- [ ] Default credentials changed
- [ ] Security headers present
- [ ] CORS properly configured
- [ ] Dependency versions up to date

### CSRF & Clickjacking
- [ ] CSRF tokens implemented
- [ ] SameSite cookie attribute set
- [ ] X-Frame-Options header set

## Security Testing Tools

```bash
# Dependency vulnerability scanning
npm audit
npm audit fix

# OWASP ZAP (automated security scanner)
docker run -t owasp/zap2docker-stable zap-baseline.py -t https://example.com

# SSL/TLS testing
nmap --script ssl-enum-ciphers -p 443 example.com

# Headers check
curl -I https://example.com
```

## Best Practices

1. **Defense in depth** - Multiple layers of security
2. **Principle of least privilege** - Minimal necessary permissions
3. **Fail securely** - Errors should not expose information
4. **Security by default** - Secure unless explicitly opened
5. **Never trust user input** - Always validate and sanitize
6. **Keep dependencies updated** - Patch vulnerabilities
7. **Use security headers** - Helmet.js for Express
8. **Log security events** - Failed logins, authorization failures
9. **Regular security audits** - Automated and manual testing
10. **Security training** - Keep team aware of threats

## Common Pitfalls

❌ **Don't:** Trust client-side validation only
✅ **Do:** Always validate on the server

❌ **Don't:** Store passwords in plain text or weak hashes
✅ **Do:** Use bcrypt with salt rounds ≥ 12

❌ **Don't:** Expose detailed error messages
✅ **Do:** Return generic errors to clients, log details

❌ **Don't:** Use predictable IDs or tokens
✅ **Do:** Use UUIDs or cryptographically secure random values

❌ **Don't:** Forget to test authorization edge cases
✅ **Do:** Test all permission combinations systematically
