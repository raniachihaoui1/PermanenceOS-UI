### 0. Daylight tool has an error - investigate

### 1. Preprocessing should detect user feedback keywords
**File**: `python/nodes/preprocessing.py`
**Issue**: After feedback asks "are you happy?", user's response goes back through preprocessing but routes to brief again instead of routing smartly

**Required**:
- Detect keywords: "yes", "no", "different", "change rooms", "change boundary"
- If "yes" → set `final_response = "Layout finalized!"` and route to END
- If "no"/"different" → route to search (not brief)
- If "change rooms" → route to brief (new program extraction)
- If "change boundary" → route to boundary node
- If no keyword → assume new request, route to brief

### 2. Preprocessing should load/set layout in state
File: python/nodes/preprocessing.py
Issue: Bootstrap loads input_layout, but preprocessing should manage layout state
Required: Move layout initialization logic from graph._build_initial_state to preprocessing node

### 3. Feedback-to-search routing not working
File: python/graph.py
Issue: Feedback response → preprocessing → should intelligently route, not always to brief