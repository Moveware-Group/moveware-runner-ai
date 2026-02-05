# Scope Control System

## Overview

The AI Runner now has strict scope controls to prevent "feature creep" - where the AI adds extra functionality that wasn't requested.

## The Problem

**Issue Observed:** AI generated an unauthorized `app/performance/page.tsx` dashboard page that was never mentioned in the Jira ticket. This caused:
- Build failures (TypeScript errors in code that shouldn't exist)
- Wasted development time debugging unwanted features
- Scope creep and unexpected functionality
- Code review overhead for features that weren't requested

## The Solution

### System Prompt Rules

Added explicit scope control rules to the system prompt:

```
🚨 CRITICAL SCOPE RULES - MUST FOLLOW:
- ONLY implement what is EXPLICITLY stated in the task requirements
- Do NOT add features, pages, or components that are not mentioned
- Do NOT add 'nice to have' functionality or try to be 'helpful' by adding extras
- Do NOT create dashboard pages, admin panels, or analytics unless specifically requested
- If you think something is missing: ASK via questions array, DON'T implement
- Every file you create MUST be directly mentioned or implied by the task
- When in doubt, implement LESS rather than MORE
```

### Task-Specific Reminder

Before implementation, Claude receives an additional reminder:

```
REMINDER - SCOPE CHECK:
Before implementing, verify that EVERY file you create is explicitly 
mentioned in the requirements. If you're creating a file that isn't 
directly requested, STOP and ask a question instead.
```

## How It Works

### 1. Pre-Implementation Check

Claude is instructed to mentally verify each file against the requirements:

```
Requirements: "Add user authentication"
Files to create:
  ✅ lib/auth.ts - Mentioned in requirements
  ✅ middleware.ts - Implied by authentication requirement
  ❌ app/dashboard/page.tsx - NOT mentioned, would need to ask first
```

### 2. Questions Over Assumptions

If Claude thinks something is needed but it's not in the requirements:

**❌ Old behavior:**
```json
{
  "files": [
    {"path": "app/login/page.tsx", ...},
    {"path": "app/dashboard/page.tsx", ...}  // Added without being asked!
  ]
}
```

**✅ New behavior:**
```json
{
  "questions": [
    "Should I also create a dashboard page for authenticated users?"
  ]
}
```

### 3. Conservative Implementation

When requirements are ambiguous, implement the minimum:

**Requirement:** "Add hero section to homepage"

**❌ Over-implementation:**
- Hero section
- About section
- Features section  
- Testimonials section
- Newsletter signup

**✅ Correct implementation:**
- Hero section only

If more sections are needed, they'll be in separate tickets.

## Common Scenarios

### Scenario 1: Database Setup

**Requirement:** "Add database connection"

**Allowed:**
- `lib/db.ts` - Database connection code
- `lib/prisma.ts` - Prisma client (if using Prisma)
- `.env.example` update - Add DATABASE_URL placeholder

**Not Allowed (unless explicitly requested):**
- Seed scripts
- Admin panels
- Database migration scripts
- Backup utilities
- Query performance monitoring

### Scenario 2: UI Component

**Requirement:** "Create a button component"

**Allowed:**
- `components/Button.tsx` - The button component
- `components/Button.test.tsx` - Tests (if project has testing setup)

**Not Allowed:**
- `components/IconButton.tsx` - Variant not requested
- `components/ButtonGroup.tsx` - Related component not requested
- `app/components-showcase/page.tsx` - Documentation page not requested

### Scenario 3: API Endpoint

**Requirement:** "Add POST /api/users endpoint"

**Allowed:**
- `app/api/users/route.ts` - The requested endpoint
- `lib/validation/user.ts` - Validation if complex

**Not Allowed:**
- `app/api/users/[id]/route.ts` - GET by ID not requested
- `app/api/users/stats/route.ts` - Analytics not requested
- `app/api/admin/users/route.ts` - Admin endpoint not requested
- `lib/logger.ts` - Logging not requested

## Benefits

### 1. **Predictable Outcomes**
You get exactly what you asked for, nothing more, nothing less.

### 2. **Faster Development**
No time wasted on:
- Debugging unauthorized features
- Removing unwanted code
- Testing functionality that shouldn't exist

### 3. **Easier Code Review**
Reviewers can focus on the actual requirements without being surprised by extra features.

### 4. **Better Estimates**
When you create a Jira ticket for "Add login form", you get a login form. Not a login form + dashboard + settings page + profile editor.

### 5. **Clearer Git History**
Each commit implements exactly what the ticket describes.

## Implementation Details

### File: `app/executor.py`

**System Prompt Section:**
```python
def _system_prompt() -> str:
    return (
        # ... other rules ...
        "**🚨 CRITICAL SCOPE RULES - MUST FOLLOW:**\n"
        "- ONLY implement what is EXPLICITLY stated...\n"
        # ... full rules ...
    )
```

**Task Prompt Section:**
```python
prompt += (
    f"**REMINDER - SCOPE CHECK:**\n"
    f"Before implementing, verify that EVERY file you create is "
    f"explicitly mentioned in the requirements above.\n"
    # ...
)
```

## Monitoring

### Signs That Scope Control is Working

✅ **Good signs:**
- PRs match Jira ticket descriptions exactly
- No unexpected files in commits
- AI asks questions when requirements are unclear
- Build failures decrease (no code that shouldn't exist)

### Signs of Scope Creep

❌ **Warning signs:**
- Files in PR that aren't mentioned in Jira ticket
- "I also added..." comments in commit messages
- Features implemented that "would be nice to have"
- Dashboard/admin pages appearing without being requested

### How to Check

```bash
# Review recent Story PRs
gh pr list --label "ai-generated" --limit 10

# For each PR, compare files changed vs Jira ticket description
gh pr view <PR-NUMBER> --json files,body

# Look for mismatches between ticket and implementation
```

## Handling Edge Cases

### Case 1: Implied Dependencies

**Scenario:** Ticket says "Add user authentication"

**Question:** Can AI create a login form?

**Answer:** YES - Login form is directly implied by "authentication"

**Rule:** If feature X requires component Y to function, Y is allowed.

### Case 2: Configuration Files

**Scenario:** Ticket says "Add database"

**Question:** Can AI update `.env.example`?

**Answer:** YES - Configuration for new features is implied

**Rule:** Configuration/setup for explicitly requested features is allowed.

### Case 3: Testing

**Scenario:** Ticket says "Add API endpoint"

**Question:** Can AI create test files?

**Answer:** YES - If project has test structure, tests for new code are implied

**Rule:** Tests for implemented features are allowed (but not test infrastructure if it doesn't exist).

### Case 4: Documentation

**Scenario:** Ticket says "Add payment processing"

**Question:** Can AI add JSDoc comments?

**Answer:** YES - Inline documentation is always allowed

**Question:** Can AI create `docs/payment-guide.md`?

**Answer:** NO - Unless ticket explicitly requests documentation

## Troubleshooting

### Issue: AI Asks Too Many Questions

**Symptom:** Every task results in questions instead of implementation

**Cause:** Rules are too strict, or requirements are too vague

**Solution:**
1. Make Jira tickets more explicit
2. Include "implied dependencies" in ticket description
3. Add examples of what should be created

### Issue: AI Still Adds Unauthorized Files

**Symptom:** Extra files still appearing in PRs

**Possible causes:**
1. Requirements are too broad ("Implement user system")
2. AI is inferring requirements from repository context
3. Design system or templates suggest additional features

**Solution:**
1. Make tickets more specific
2. Review system prompt enforcement
3. Check if repository context is misleading

### Issue: AI Doesn't Implement Necessary Files

**Symptom:** Implementation is incomplete and doesn't work

**Cause:** Rules are too restrictive

**Solution:**
- Add "and any necessary supporting files" to ticket
- Be more explicit about required components
- Review questions array in AI's response

## Best Practices for Writing Tickets

### ✅ Good Ticket Examples

**Example 1: Specific and Complete**
```
Title: Add user registration form
Description:
- Create /register page with email/password fields
- Add form validation (email format, password strength)
- Connect to POST /api/auth/register endpoint
- Show success message and redirect to /dashboard on success
- Show error message on failure
```
*Result:* AI creates exactly these components, nothing more.

**Example 2: With Implied Dependencies**
```
Title: Add blog post creation
Description:
- Create /admin/posts/new page for admins
- Include title, content (rich text editor), and publish date fields
- Save to database on submit
- Includes any necessary API routes and data models
```
*Result:* AI creates page, API route, and model. "Includes any necessary" gives permission for required infrastructure.

### ❌ Bad Ticket Examples

**Example 1: Too Vague**
```
Title: Improve user experience
Description: Make the app better for users
```
*Problem:* AI could implement anything. Too open-ended.

**Example 2: Missing Scope**
```
Title: Add products
Description: The app needs products
```
*Problem:* Does this mean:
- Product listing page?
- Product creation page?
- Product database model?
- Product search?
All of the above?

## Metrics to Track

Track these metrics to measure scope control effectiveness:

```python
# Suggested tracking
scope_metrics = {
    "total_tasks": 100,
    "files_requested": 150,      # From Jira tickets
    "files_implemented": 155,    # From commits
    "scope_creep_rate": "3%",    # (155-150)/150
    "unauthorized_files": 5,
    "questions_asked": 12        # AI asked for clarification
}
```

**Target metrics:**
- Scope creep rate: < 5%
- Unauthorized files: < 3 per 100 tasks
- Questions asked: 5-15 per 100 tasks (shows AI is checking)

## Future Enhancements

### 1. Pre-Flight Scope Validation

Before generating code, AI lists all files it plans to create and asks for confirmation:

```
I plan to create these files for this task:
✓ lib/auth.ts (explicit in requirements)
✓ middleware.ts (implied by auth requirement)
? app/dashboard/page.tsx (not mentioned - should I create this?)

Proceed? [yes/ask/no]
```

### 2. Scope Diff Tool

Tool that compares Jira ticket to implemented files:

```bash
./scripts/scope_check.sh STORY-123

Requirements mentioned:
  ✓ lib/auth.ts
  ✓ app/login/page.tsx

Files implemented:
  ✓ lib/auth.ts
  ✓ app/login/page.tsx
  ❌ app/dashboard/page.tsx (NOT in requirements!)
  ❌ app/profile/page.tsx (NOT in requirements!)

Scope creep detected: 2 unauthorized files
```

### 3. Learning System

Track which files are commonly needed together:

```python
patterns = {
    "authentication": ["lib/auth.ts", "middleware.ts", "app/login/page.tsx"],
    "api_endpoint": ["app/api/*/route.ts", "lib/validation/*.ts"],
    "react_component": ["components/*.tsx", "components/*.test.tsx"]
}
```

AI can reference these patterns when deciding if a file is "implied".

## Conclusion

Strict scope control ensures that:

1. ✅ AI implements exactly what's requested
2. ✅ No surprise features appear
3. ✅ Builds don't fail on unauthorized code
4. ✅ Code reviews are predictable
5. ✅ Development stays on track

**Remember:** It's always easier to add a feature later than to remove an unexpected one.

---

**Last Updated:** February 5, 2026  
**Version:** 1.0  
**Status:** Production
