# Detailed Code Changes Reference

## File 1: server_web.py

### Change 1: Added Client Log Handler (After line 38)
```python
@socketio.on('client_log')
def handle_client_log(data):
    """Handle logging messages from the client side"""
    msg = data.get('message', 'Unknown client event')
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted = f"[CLIENT] [{timestamp}] {msg}"
    print(formatted)
    logging.info(f"CLIENT: {msg}")
    socketio.emit('system_log', {'message': formatted}, broadcast=True)
```

**Purpose**: Receives logging events from frontend via SocketIO and broadcasts to all clients

**Location**: After log_event() function definition

---

### Change 2: Enhanced ensure_message_db() (Line 75)
**Before**:
```python
def ensure_message_db(company: str) -> str:
    os.makedirs(MESSAGE_DB_DIR, exist_ok=True)
    db_path = get_company_db_path(company)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (...)''')
    conn.commit()
    conn.close()
    return db_path
```

**After** (Added logging line):
```python
def ensure_message_db(company: str) -> str:
    os.makedirs(MESSAGE_DB_DIR, exist_ok=True)
    db_path = get_company_db_path(company)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (...)''')
    conn.commit()
    conn.close()
    logging.info(f"Ensured company database: {db_path}")  # ← NEW
    return db_path
```

**Purpose**: Log when company databases are created or accessed

---

### Change 3: Enhanced save_message() (Line 145)
**Before**:
```python
def save_message(t, m_type, n_id, s_id, flow, vel, fday, fmonth, fyear, det, company, node_status=0):
    try:
        db_path = ensure_message_db(company)
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO messages 
                     (...)''',
                  (t, m_type, n_id, str(s_id), flow, vel, fday, fmonth, fyear, det, company, node_status))
        conn.commit()
        conn.close()
    except Exception as e:
        log_event(f"Database error: {e}")
```

**After** (Added logging):
```python
def save_message(t, m_type, n_id, s_id, flow, vel, fday, fmonth, fyear, det, company, node_status=0):
    try:
        db_path = ensure_message_db(company)
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO messages 
                     (...)''',
                  (t, m_type, n_id, str(s_id), flow, vel, fday, fmonth, fyear, det, company, node_status))
        conn.commit()
        conn.close()
        logging.info(f"Saved {m_type} message for Node {n_id} (Company: {company}) to database")  # ← NEW
    except Exception as e:
        log_event(f"Database error: {e}")
```

**Purpose**: Log each message save with company context

---

## File 2: static/js/app.js

### Change 1: Updated window.onload (Line 23-36)
**Before**:
```javascript
window.onload = function() {
    searchTabular();
    if(document.getElementById('users-table')) {
        loadUsers();
        if(document.getElementById('companies-table')) {
            loadCompanies();
        }
    }
    initNodeSelectors();
    handleCmdChange();
}
```

**After** (Added listener initialization):
```javascript
window.onload = function() {
    searchTabular();
    if(document.getElementById('users-table')) {
        loadUsers();
        if(document.getElementById('companies-table')) {
            loadCompanies();
        }
    }
    initNodeSelectors();
    handleCmdChange();
    setupCompanyChangeListener();  // ← NEW
}
```

**Purpose**: Initialize company change listener on page load

---

### Change 2: Added setupCompanyChangeListener() (Line 125-151)
```javascript
function setupCompanyChangeListener() {
    const companySelect = document.getElementById('cfg-company');
    if (!companySelect) return;
    
    companySelect.addEventListener('change', function() {
        const newCompany = this.value;
        logToSystemLog(`[COMPANY CHANGE] Switched to company: ${newCompany}`);
        
        // Clear node data for new company
        nodeLatestData = {};
        nodeHistoryData = {};
        
        // Reset all node selectors
        initNodeSelectors();
        
        // Clear graph and live status
        renderLiveNode();
        renderGraphNode();
        
        // Reload tabular data if visible
        const tabularTab = document.getElementById('TabularData');
        if (tabularTab && tabularTab.classList.contains('active')) {
            searchTabular();
        }
        
        logToSystemLog(`[GRAPH RESET] Graph and live status cleared for company: ${newCompany}`);
    });
}
```

**Purpose**: Handle company dropdown changes and reset all UI elements

---

### Change 3: Added logToSystemLog() (Line 176-182)
```javascript
function logToSystemLog(message) {
    const timestamp = new Date().toLocaleTimeString();
    const logEntry = `[${timestamp}] ${message}`;
    console.log(logEntry);
    
    // Also emit to server log via socket for persistence
    socket.emit('client_log', { message: message });
}
```

**Purpose**: Centralized client-side logging with SocketIO emission

---

### Change 4: Enhanced connect() (Line 192-209)
**Before**:
```javascript
async function connect() {
    const data = {...}
    const res = await fetch("/api/connect", {...});
    const result = await res.json();
    if(result.success) {
        document.getElementById('btn-connect').disabled = true;
        document.getElementById('btn-disconnect').disabled = false;
    } else { alert("Error connecting: " + result.error); }
}
```

**After** (Added logging):
```javascript
async function connect() {
    const data = {...}
    const res = await fetch("/api/connect", {...});
    const result = await res.json();
    if(result.success) {
        document.getElementById('btn-connect').disabled = true;
        document.getElementById('btn-disconnect').disabled = false;
        logToSystemLog(`[MQTT CONNECT] Connected to ${data.broker}:${data.port} for company: ${data.company}`);  // ← NEW
    } else { 
        logToSystemLog(`[MQTT ERROR] Failed to connect: ${result.error}`);  // ← NEW
        alert("Error connecting: " + result.error); 
    }
}
```

**Purpose**: Log MQTT connection attempts and results

---

### Change 5: Enhanced disconnect() (Line 212-217)
**Before**:
```javascript
async function disconnect() {
    await fetch("/api/disconnect", {method: "POST"});
    document.getElementById('btn-connect').disabled = false;
    document.getElementById('btn-disconnect').disabled = true;
    stopPeriodicStime();
}
```

**After** (Added logging):
```javascript
async function disconnect() {
    await fetch("/api/disconnect", {method: "POST"});
    document.getElementById('btn-connect').disabled = false;
    document.getElementById('btn-disconnect').disabled = true;
    stopPeriodicStime();
    logToSystemLog("[MQTT DISCONNECT] Disconnected from broker");  // ← NEW
}
```

**Purpose**: Log MQTT disconnections

---

### Change 6: Enhanced switchGraphNode() (Line 434-436)
**Before**:
```javascript
function switchGraphNode() { renderGraphNode(); }
```

**After** (Added logging):
```javascript
function switchGraphNode() { 
    const nodeId = document.getElementById('graph-node-select').value;
    logToSystemLog(`[GRAPH UPDATE] Switched graph to Node ID: ${nodeId}`);  // ← NEW
    renderGraphNode(); 
}
```

**Purpose**: Log node selection changes

---

### Change 7: Enhanced renderGraphNode() (Line 438-456)
**Before**:
```javascript
function renderGraphNode() {
    const nid = document.getElementById('graph-node-select').value;
    const h = nodeHistoryData[nid];
    if(!h || h.flows.length === 0) {
        myChart.data.labels = [];
        myChart.data.datasets[0].data = [];
        myChart.data.datasets[1].data = [];
        myChart.update();
        updateNodeStatusTexts();
        return;
    }
    myChart.data.labels = h.lbls;
    myChart.data.datasets[0].data = h.flows;
    myChart.data.datasets[1].data = h.vels;
    myChart.update();
    updateNodeStatusTexts();
}
```

**After** (Added logging):
```javascript
function renderGraphNode() {
    const nid = document.getElementById('graph-node-select').value;
    const h = nodeHistoryData[nid];
    if(!h || h.flows.length === 0) {
        myChart.data.labels = [];
        myChart.data.datasets[0].data = [];
        myChart.data.datasets[1].data = [];
        myChart.update();
        logToSystemLog(`[GRAPH UPDATE] Node ${nid} has no history data`);  // ← NEW
        updateNodeStatusTexts();
        return;
    }
    myChart.data.labels = h.lbls;
    myChart.data.datasets[0].data = h.flows;
    myChart.data.datasets[1].data = h.vels;
    myChart.update();
    logToSystemLog(`[GRAPH UPDATE] Graph updated for Node ${nid} with ${h.flows.length} data points`);  // ← NEW
    updateNodeStatusTexts();
}
```

**Purpose**: Log graph updates with data point count

---

## Summary of Changes

### Server-Side Changes
- Added SocketIO handler for client logging
- Enhanced database functions with logging
- Enhanced message save with logging

### Client-Side Changes  
- Added centralized logging function
- Added company change listener with full reset logic
- Enhanced all major functions with logging calls

### Total Lines Changed
- **server_web.py**: ~20 new lines
- **static/js/app.js**: ~80 new lines
- **Total**: ~100 lines added

### Backward Compatibility
- ✅ All changes are additive (no breaking changes)
- ✅ Existing functionality preserved
- ✅ No API changes
- ✅ No database schema changes

### Testing Points
1. Verify company change triggers graph reset
2. Check system.log for all logged events
3. Monitor SocketIO communication
4. Validate data isolation per company
5. Test MQTT connection logging
