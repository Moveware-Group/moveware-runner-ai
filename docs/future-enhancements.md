# Future Enhancements - AI Runner

**Purpose:** Planned features to implement after system stabilization  
**Status:** Backlog  
**Date:** February 14, 2026

---

## 🎯 Priority 1: GitHub PR Integration (High Value)

**Status:** Not Started  
**Complexity:** Medium  
**Estimated Time:** 2-4 hours  
**Value:** HIGH - Closes the feedback loop

### **Overview**
Connect GitHub PR events back to AI Runner for automatic Jira status updates and rework triggers.

### **Features to Implement:**

#### **1. PR Approved → Auto-Complete Task**
- GitHub webhook: `pull_request_review` (approved)
- AI Runner: Move Jira task to "Done"
- Add comment with approver name
- Trigger next Story in Epic (if applicable)

#### **2. PR Changes Requested → Auto-Rework**
- GitHub webhook: `pull_request_review` (changes_requested)
- AI Runner: Move task back to "Selected for Development"
- Add PR feedback comments to Jira
- Re-execute with fixes
- Update PR

#### **3. PR Merged → Auto-Complete Story**
- GitHub webhook: `pull_request` (closed, merged=true)
- AI Runner: Mark Story/Epic as Done
- Check Epic completion

### **Technical Requirements:**

**New Endpoint:**
```python
@app.post("/webhook/github-pr")
async def github_pr_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None)
):
    # Verify signature
    # Parse event type (approved, changes_requested, merged)
    # Extract issue key from branch name
    # Update Jira accordingly
    # Trigger rework if needed
```

**GitHub Setup:**
1. Repo Settings → Webhooks → Add webhook
2. URL: `https://ai-console.moveconnect.com/webhook/github-pr`
3. Events: Pull request reviews, Pull requests
4. Secret: Store in `.env`

**Implementation Files:**
- `app/main.py` - Add webhook endpoint
- `app/github_handler.py` - Parse GitHub events
- `app/worker.py` - Add PR feedback handlers

### **Benefits:**
- ✅ Truly end-to-end automation
- ✅ PR feedback automatically processed
- ✅ No manual Jira status updates
- ✅ Faster iteration cycle

---

## 🎯 Priority 2: Enhanced Restoration Detection (Medium Value)

**Status:** Basic version implemented  
**Next Steps:** Expand capabilities  
**Complexity:** Low  
**Value:** MEDIUM

### **Enhancements:**

#### **1. Visual Diff in Jira**
- When git history found, show before/after diff
- Highlight deleted lines in red, new lines in green
- Helps AI understand exactly what changed

#### **2. Multi-File Restoration**
- Currently: Shows first 3 deleted files
- Enhancement: Show all related files
- Group by component (UI, API, models, etc.)

#### **3. Dependency Detection**
- If deleted files imported from other files
- Find and include those dependencies
- Show full component tree

---

## 🎯 Priority 3: Smart Testing Suggestions (Medium Value)

**Status:** Not Started  
**Complexity:** High  
**Value:** MEDIUM

### **Overview**
Automatically generate testing checklists based on code changes.

### **Features:**

#### **1. Test Case Generation**
Analyze changed files and generate:
- Unit test suggestions
- Integration test scenarios
- Edge cases to test
- Regression test areas

#### **2. Visual Testing**
For UI changes:
- Auto-capture screenshots (before/after)
- Suggest visual regression tests
- List UI components to test manually

#### **3. API Testing**
For API changes:
- Generate Postman/curl examples
- List all affected endpoints
- Suggest load testing if performance-critical

---

## 🎯 Priority 4: Parallel Story Processing (Low Value)

**Status:** Sequential processing implemented  
**Alternative Approach:** Parallel  
**Complexity:** Medium  
**Value:** LOW (sequential is safer)

### **Overview**
Process multiple Stories in an Epic simultaneously instead of sequentially.

### **Pros:**
- ✅ Faster Epic completion (2-3x speed)
- ✅ Better resource utilization

### **Cons:**
- ❌ Merge conflict risk
- ❌ Harder to debug
- ❌ May break dependencies between Stories

### **Recommendation:**
- Keep sequential as default
- Add `parallel: true` flag in Epic plan for independent Stories
- Implement only if Epic completion speed becomes a bottleneck

---

## 🎯 Priority 5: AI Model Selection (Low Value)

**Status:** Currently fixed (Claude + GPT)  
**Enhancement:** Dynamic model selection  
**Complexity:** Low  
**Value:** LOW

### **Features:**

#### **1. Task-Based Model Selection**
- Simple tasks → Faster/cheaper model (GPT-4o-mini)
- Complex tasks → Premium model (Claude Opus)
- UI tasks → Model trained on frontend
- Backend tasks → Model trained on APIs

#### **2. Cost Optimization**
- Track cost per task type
- Switch to cheaper models where quality doesn't drop
- Alert when cost exceeds budget

#### **3. Multi-Model Voting**
- For critical fixes: get 3 AI opinions
- Use majority approach
- Higher accuracy, higher cost

---

## 🎯 Priority 6: Automated E2E Testing (Low Value)

**Status:** Not Started  
**Complexity:** High  
**Value:** LOW (manual testing works)

### **Overview**
Automatically run end-to-end tests after implementation.

### **Features:**
- Playwright/Cypress tests run automatically
- Screenshot comparison (visual regression)
- API smoke tests
- Performance benchmarks

### **Why Low Priority:**
- Manual testing catches most issues
- E2E tests require significant setup
- False positives can be frustrating
- Better to stabilize core system first

---

## 🎯 Priority 7: Multi-Language Support (Future)

**Status:** Currently Node.js/TypeScript focused  
**Complexity:** High  
**Value:** Depends on your stack

### **Languages to Add:**
- Python/Django
- Python/Flask
- Ruby on Rails
- Java/Spring Boot
- Go
- Rust

---

## 📊 Prioritization Criteria

| Feature | Value | Complexity | Priority |
|---------|-------|------------|----------|
| GitHub PR Integration | HIGH | Medium | 1️⃣ |
| Enhanced Restoration | MEDIUM | Low | 2️⃣ |
| Smart Testing | MEDIUM | High | 3️⃣ |
| Parallel Stories | LOW | Medium | 4️⃣ |
| Model Selection | LOW | Low | 5️⃣ |
| E2E Testing | LOW | High | 6️⃣ |
| Multi-Language | Varies | High | 7️⃣ |

---

## 🔮 Recommended Implementation Order

### **Phase 1: Stabilization** (Next 2-4 weeks)
- Deploy current 34 commits
- Monitor for edge cases
- Fix any issues that emerge
- Let pattern learning accumulate data

### **Phase 2: Close the Loop** (After stabilization)
1. ✅ Implement GitHub PR webhook integration
2. ✅ Test with real PRs
3. ✅ Document setup for team

### **Phase 3: Intelligence** (Optional, based on needs)
1. Enhanced restoration detection
2. Smart testing suggestions
3. Cost optimization

### **Phase 4: Scale** (When needed)
1. Parallel Story processing (if speed needed)
2. Multi-language support (if expanding stack)
3. E2E testing automation (if team grows)

---

## 📝 Notes

- Review this list quarterly
- Re-prioritize based on pain points
- Don't implement unless there's clear value
- Stability > features

---

_Document maintained by: AI Runner Development Team_  
_Last updated: February 14, 2026_
