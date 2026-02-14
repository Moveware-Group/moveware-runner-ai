# Writing Effective Stories for the AI Runner

**Purpose:** Guide for writing Jira Stories that the AI Runner understands and implements correctly  
**Date:** February 14, 2026

---

## 🚨 Case Study: What Went Wrong with OD-750

### **The Problem:**

**Story:** "Fix: Restore Companies Management Section"

**What the AI Did:**
- ✅ Created backend API endpoints
- ✅ Added database support
- ❌ **Did NOT restore the UI components** (the main requirement!)

**Root Cause:**
- Story description said "restore" but didn't explicitly list what to restore
- No screenshots or references to the original UI
- Acceptance criteria were generic
- AI assumed "restore" meant "create backend support" instead of "bring back the full UI"

---

## ✅ How to Write Stories the AI Understands

### **1. Use Explicit Action Words**

| ❌ Vague | ✅ Clear |
|----------|----------|
| "Restore Companies Management" | "**Re-implement** the Companies Management UI that was removed in Story OD-48" |
| "Fix the login" | "**Fix bug:** Login button doesn't disable during API call" |
| "Add authentication" | "**Implement** JWT-based authentication with registration and login endpoints" |
| "Improve performance" | "**Optimize** search query to reduce response time from 3s to <500ms" |

**Key Action Words:**
- **Re-implement:** Bring back something that was removed
- **Restore:** Put back exactly as it was before
- **Implement:** Create something new from scratch
- **Fix bug:** Correct specific broken behavior
- **Enhance:** Improve existing feature
- **Refactor:** Restructure code without changing behavior

---

### **2. Include "Before" Context for Restorations**

When asking the AI to restore or fix something, **always include context about what existed before**.

#### **❌ BAD Example:**
```
Story: Restore Companies Management Section

Description:
Restore Companies management functionality that was removed in Story 1

RESTORE:
• Companies button/tab in settings
• Primary color picker
• Secondary color picker  
• Tertiary color picker
• Logo upload functionality
```

**Problem:** AI doesn't know what the UI looked like!

#### **✅ GOOD Example:**
```
Story: Re-implement Companies Management UI (Removed in OD-48)

Description:
The AI chatbot implementation (OD-48) accidentally removed the entire Companies 
management UI from the Settings page. We need to bring it back EXACTLY as it was.

**What existed before (removed in OD-48):**
1. **Companies Tab/Button** in Settings navigation
2. **Companies List View** showing all companies with:
   - Company name
   - Logo preview
   - Edit button for each company
3. **Add Company Form** with fields:
   - Company Name (text input)
   - Brand Code (text input)
   - Primary Color (color picker)
   - Secondary Color (color picker)
   - Tertiary Color (color picker)
   - Logo (file upload, accepts PNG/JPG)
   - Hero Content (textarea)
   - Copy Content (textarea)
4. **Edit Company Form** (same fields as Add)
5. **Delete Company** button (with confirmation)

**Reference:**
- See commit BEFORE OD-48 for original implementation
- Original file: `app/settings/companies/page.tsx` (was deleted)
- Component location: `components/CompaniesManager.tsx` (was deleted)

**What to preserve:**
- Keep the new AI Chatbot section from OD-48
- Keep all existing settings
- The Companies section should be ADDITIONAL, not replacing anything

ACCEPTANCE CRITERIA:
[ ] Companies tab appears in Settings navigation
[ ] Can see list of existing companies
[ ] Can add new company with all 8 fields
[ ] Can edit existing companies
[ ] Can delete companies (with confirmation)
[ ] Color pickers work (shows preview)
[ ] Logo upload works (shows preview)
[ ] All data saves to database correctly
[ ] AI Chatbot section still works (no regression)
```

**Why this works:**
- ✅ Explicit "re-implement" instead of vague "restore"
- ✅ Lists EXACTLY what existed before
- ✅ Specifies where files were located
- ✅ References the commit that broke it
- ✅ Clear acceptance criteria (9 specific checkboxes)
- ✅ Reminds AI to preserve existing features

---

### **3. Break Down Complex Stories**

If a Story is too large, the AI might miss parts. Break it down:

#### **❌ Single Large Story:**
```
Story: Add user management system

Description: Add complete user management with CRUD, roles, permissions, and audit logs
```

**Problem:** Too broad - AI might implement only part of it.

#### **✅ Multiple Focused Stories:**
```
Story 1: Implement User CRUD operations
- Create, Read, Update, Delete users
- Basic user profile fields

Story 2: Add User Roles and Permissions
- Define role types (Admin, Editor, Viewer)
- Implement permission checks
- Assign roles to users

Story 3: Add User Audit Logging
- Track user actions
- Display audit log UI
- Filter and search logs
```

**Why this works:**
- ✅ Each Story is focused and testable
- ✅ AI can fully complete each one
- ✅ Dependencies are clear
- ✅ Easier to verify completion

---

### **4. Provide Visual References**

The AI works better when it can "see" what you want.

#### **Options:**

1. **Screenshots of the original UI** (attached to Story)
   ```
   See attached screenshots:
   - companies-list-view.png
   - companies-add-form.png
   - companies-edit-form.png
   ```

2. **Link to commit before regression**
   ```
   Reference: See code at commit abc123 (before OD-48)
   Original files:
   - app/settings/companies/page.tsx
   - components/CompaniesManager.tsx
   ```

3. **Wireframes or mockups**
   ```
   See Figma mockup: https://figma.com/file/...
   ```

4. **Link to similar feature**
   ```
   UI should look similar to the "Users Management" page
   but with company-specific fields
   ```

---

### **5. Write Specific Acceptance Criteria**

The AI uses acceptance criteria to verify it's done. Make them VERY specific.

#### **❌ VAGUE Acceptance Criteria:**
```
[ ] Companies management works
[ ] UI looks good
[ ] Data saves correctly
```

**Problem:** Too subjective - AI can't verify these!

#### **✅ SPECIFIC Acceptance Criteria:**
```
[ ] Companies tab appears in Settings navigation (next to "General")
[ ] Clicking Companies tab shows the Companies page
[ ] Companies page shows a table with columns: Name, Logo, Colors (preview), Actions
[ ] "Add Company" button visible at top-right
[ ] Clicking "Add Company" opens a form with 8 fields (listed above)
[ ] Primary/Secondary/Tertiary color pickers show color preview swatch
[ ] Logo upload accepts PNG/JPG, shows preview after selection
[ ] Form validation: Company Name and Brand Code are required
[ ] Clicking "Save" creates company and returns to list
[ ] Clicking "Edit" (pencil icon) opens edit form with current values
[ ] Clicking "Delete" (trash icon) shows confirmation dialog
[ ] Confirming delete removes company from list
[ ] All existing features still work (AI Chatbot, General Settings)
```

**Why this works:**
- ✅ 13 specific, testable criteria
- ✅ AI can verify each one
- ✅ Tester knows exactly what to test
- ✅ No ambiguity

---

### **6. Specify What NOT to Change**

When you want something preserved, say it explicitly!

```
CRITICAL: DO NOT MODIFY OR REMOVE:
- AI Chatbot section (from OD-48)
- General Settings section
- Any existing settings functionality
- Database schema for other features

This is an ADDITIVE change - add the Companies section ALONGSIDE existing features.
```

---

### **7. Use Technical Details When Needed**

For technical tasks, be specific about implementation:

#### **❌ Too Generic:**
```
Story: Add caching

Description: Add caching to improve performance
```

#### **✅ Technically Specific:**
```
Story: Implement Redis caching for user sessions

Description:
Replace current in-memory session storage with Redis caching.

TECHNICAL REQUIREMENTS:
- Use Redis for session storage
- Session TTL: 24 hours
- Cache key format: `session:{userId}:{sessionId}`
- Fallback to in-memory if Redis unavailable
- Add Redis connection to `.env.example`:
  - REDIS_URL=redis://localhost:6379

FILES TO MODIFY:
- lib/session.ts (replace in-memory Map with Redis client)
- .env.example (add REDIS_URL)
- package.json (add 'ioredis' dependency)

ACCEPTANCE CRITERIA:
[ ] Sessions stored in Redis instead of memory
[ ] Sessions persist across server restarts
[ ] Session TTL works (expires after 24 hours)
[ ] Graceful fallback to in-memory if Redis down
[ ] REDIS_URL in .env.example
[ ] ioredis dependency added
```

---

## 🔧 Template for Restoration Stories

Use this template when asking the AI to restore removed functionality:

```
Story: Re-implement [Feature Name] (Removed in [Story/Commit])

## Context
The [feature name] was accidentally removed in [Story X]. We need to bring it back 
EXACTLY as it was before.

## What Was Removed
[Detailed description of what existed before, including:]
- UI components
- API endpoints
- Database tables/fields
- File locations

## Reference Materials
- Commit before removal: [commit hash]
- Original files:
  - [file path 1]
  - [file path 2]
- Screenshots attached: [list]

## What to Re-implement
1. [Component/Feature 1]
   - [Specific detail]
   - [Specific detail]
2. [Component/Feature 2]
   - [Specific detail]

## What to Preserve
CRITICAL: Keep these existing features:
- [Feature A from the Story that broke this]
- [Feature B]

This is ADDITIVE - add [feature name] ALONGSIDE existing features.

## Technical Details
Files to restore/create:
- [file path 1]: [what it should contain]
- [file path 2]: [what it should contain]

## Acceptance Criteria
[ ] [Specific, testable criterion 1]
[ ] [Specific, testable criterion 2]
[ ] [Specific, testable criterion 3]
...
[ ] All existing features still work (no regression)
```

---

## 🎯 Checklist Before Creating a Story

Before clicking "Create", verify your Story has:

- [ ] **Clear action word** (Implement, Re-implement, Fix, Enhance, etc.)
- [ ] **Detailed description** (not just 1-2 sentences)
- [ ] **Context** (why this is needed, what happened before)
- [ ] **Visual references** (screenshots, mockups, or code references)
- [ ] **Specific acceptance criteria** (5-15 checkboxes, very specific)
- [ ] **Technical details** (if applicable: files, APIs, dependencies)
- [ ] **Preservation note** (what NOT to change)
- [ ] **Reference to related work** (if this fixes a regression or extends a feature)

---

## 📊 Story Quality Examples

### **⭐⭐⭐⭐⭐ Excellent Story**
```
Story: Re-implement Companies Management UI (Removed in OD-48)

[Follows all guidelines above: context, specific details, acceptance criteria, 
visual references, technical details, preservation notes]

Result: AI implements EXACTLY what's needed on first try ✅
```

### **⭐⭐⭐ Good Story**
```
Story: Add user authentication

Description: Implement JWT-based authentication with login and registration

Acceptance Criteria:
[ ] User can register with email/password
[ ] User can login with email/password
[ ] JWT token issued on successful login
[ ] Protected routes require valid token

Result: AI implements correctly but might need refinement 🟡
```

### **⭐ Poor Story**
```
Story: Restore Companies Management

Description: Restore Companies management functionality that was removed in Story 1

RESTORE:
• Companies button/tab in settings
• Color pickers

Result: AI misunderstands and implements only part of it ❌
```

---

## 🚀 For Your Specific Issue (OD-750)

### **Immediate Fix:**

Create a NEW Story with this template:

```
Story: Complete Companies Management UI Implementation (OD-750 Follow-up)

## Context
Story OD-750 implemented the backend API for Companies management, but the frontend 
UI was never completed. The Settings page currently shows placeholder cards but no 
actual Companies management form.

## What's Already Done (OD-750)
✅ Backend API endpoints (/api/companies)
✅ Database schema for companies
✅ CRUD operations working

## What's Still Missing (THIS STORY)
❌ Companies tab/button in Settings navigation
❌ Companies list view
❌ Add Company form
❌ Edit Company form
❌ Color pickers (Primary, Secondary, Tertiary)
❌ Logo upload component

## What to Implement

### 1. Navigation Tab
Add "Companies" tab to Settings page navigation (next to "General")

### 2. Companies List View (`app/settings/companies/page.tsx`)
Display table with columns:
- Company Name
- Logo (thumbnail)
- Brand Code
- Colors (show 3 color swatches)
- Actions (Edit, Delete buttons)

### 3. Add Company Form
Modal or page with fields:
- Company Name (text input, required)
- Brand Code (text input, required)  
- Primary Color (color picker with preview)
- Secondary Color (color picker with preview)
- Tertiary Color (color picker with preview)
- Logo (file upload, accepts PNG/JPG, shows preview)
- Hero Content (textarea, optional)
- Copy Content (textarea, optional)

### 4. Edit Company Form
Same as Add Company form, but:
- Pre-populated with existing values
- "Save Changes" button instead of "Create"

### 5. Delete Functionality
- Trash icon button on each row
- Shows confirmation dialog: "Are you sure you want to delete [Company Name]?"
- Deletes via DELETE /api/companies/:id

## Technical Implementation

### Files to Create:
- `app/settings/companies/page.tsx` - Main companies page
- `components/companies/CompaniesList.tsx` - List view component
- `components/companies/CompanyForm.tsx` - Add/Edit form
- `components/companies/ColorPicker.tsx` - Reusable color picker
- `components/companies/LogoUpload.tsx` - Logo upload component

### API Endpoints (Already exist from OD-750):
- GET /api/companies - List all companies
- POST /api/companies - Create company
- PUT /api/companies/:id - Update company
- DELETE /api/companies/:id - Delete company

### UI Framework:
- Use existing Tailwind CSS styling
- Use shadcn/ui components (Button, Input, Dialog, etc.)
- Match style of existing Settings pages

## Preservation Requirements

CRITICAL: Keep these existing features:
- AI Setup Assistant section (from OD-50)
- General Settings section
- All existing navigation
- All existing functionality

This is ADDITIVE - we're adding the Companies section to the existing Settings page.

## Acceptance Criteria

### Navigation
[ ] "Companies" tab appears in Settings navigation
[ ] Clicking "Companies" tab navigates to /settings/companies
[ ] Tab is highlighted when on Companies page

### List View
[ ] Companies list displays all companies from database
[ ] Each row shows: Name, Logo thumbnail, Brand Code, Color swatches (3), Edit/Delete buttons
[ ] "Add Company" button visible at top-right
[ ] Empty state shows "No companies yet" message with "Add Company" CTA

### Add Company
[ ] Clicking "Add Company" opens form (modal or new page)
[ ] Form has all 8 fields listed above
[ ] Company Name shows validation error if empty
[ ] Brand Code shows validation error if empty
[ ] Color pickers show color preview swatch
[ ] Clicking color picker opens color selection interface
[ ] Logo upload shows file selector when clicked
[ ] After logo selection, shows preview image
[ ] "Save" button disabled until required fields filled
[ ] Clicking "Save" creates company via POST /api/companies
[ ] After save, returns to list view and shows new company
[ ] Shows success toast: "Company created successfully"

### Edit Company
[ ] Clicking "Edit" button opens form with current values
[ ] All fields pre-populated with company data
[ ] Logo shows current logo (if exists)
[ ] Clicking "Save Changes" updates via PUT /api/companies/:id
[ ] After save, returns to list and shows updated company
[ ] Shows success toast: "Company updated successfully"

### Delete Company
[ ] Clicking "Delete" button shows confirmation dialog
[ ] Dialog shows: "Are you sure you want to delete [Company Name]?"
[ ] Dialog has "Cancel" and "Delete" buttons
[ ] Clicking "Cancel" closes dialog (no action)
[ ] Clicking "Delete" calls DELETE /api/companies/:id
[ ] After delete, removes company from list
[ ] Shows success toast: "Company deleted successfully"

### General
[ ] All existing Settings features still work (AI Assistant, General)
[ ] No console errors
[ ] Mobile responsive
[ ] Loading states shown during API calls
[ ] Error states shown if API calls fail

## Testing Instructions

1. Navigate to /settings
2. Click "Companies" tab
3. Verify empty state or existing companies list
4. Click "Add Company" and fill all fields
5. Verify color pickers work
6. Upload a logo and verify preview
7. Save and verify company appears in list
8. Click "Edit" and verify form pre-populated
9. Change some values, save, verify updates
10. Click "Delete", confirm, verify removal
11. Navigate to other Settings tabs and verify they still work
```

### **Result:**
With this level of detail, the AI should implement the UI correctly! ✅

---

## 📚 Additional Resources

- **Story Writing Best Practices:** [Atlassian Guide](https://www.atlassian.com/agile/project-management/user-stories)
- **Acceptance Criteria Examples:** [ProductPlan Guide](https://www.productplan.com/glossary/acceptance-criteria/)
- **AI Runner Documentation:** See `docs/` folder

---

## 🎉 Summary

**The Key to Success:**
1. **Be explicit** - Don't assume the AI knows what you mean
2. **Provide context** - Especially for restorations and fixes
3. **Be specific** - 10 specific criteria better than 3 vague ones
4. **Show, don't just tell** - Screenshots, code references, examples
5. **Specify preservation** - What NOT to change

**Remember:** The AI is very capable, but it needs CLEAR instructions. A well-written Story 
saves hours of back-and-forth and ensures you get what you need on the first try!

---

_Document Version: 1.0_  
_Last Updated: February 14, 2026_
