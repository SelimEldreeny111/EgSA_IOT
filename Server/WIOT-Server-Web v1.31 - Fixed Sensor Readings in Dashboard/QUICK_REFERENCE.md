# Quick Reference Guide - Company Database & Logging Features

## ✅ What Was Implemented

### 1. Separate Database Files Per Company
- **Status**: Already existed, verified and enhanced
- **Location**: `messages_dbs/` directory
- **File Format**: `{company_name}.db`
- **Examples**: `Company_1.db`, `Company_2.db`
- **Auto-created**: Yes, on first message reception

### 2. Graph Updates on Company Change
- **Trigger**: When user changes company dropdown
- **Actions**:
  - Graph is cleared (no old data shown)
  - Live status resets to "-"
  - Node selectors update with new company's nodes
  - Tabular data refreshes if visible
- **Files Modified**: `static/js/app.js`
- **Function**: `setupCompanyChangeListener()`

### 3. Comprehensive Logging

#### Server Logs
- **File**: `system.log` (root directory)
- **Format**: `YYYY-MM-DD HH:MM:SS - LEVEL - MESSAGE`
- **Logged Events**:
  - Database operations (creation, access)
  - Message saves with company info
  - MQTT connections/disconnections
  - Client-side events via SocketIO

#### Client Logs
- **Display**: System Logs tab in web UI
- **Function**: `logToSystemLog(message)`
- **Events Logged**:
  - `[COMPANY CHANGE]` - User switches companies
  - `[GRAPH RESET]` - Graph cleared and reset
  - `[GRAPH UPDATE]` - Node selection or data refresh
  - `[MQTT CONNECT]` - Broker connection details
  - `[MQTT DISCONNECT]` - Disconnection confirmed
  - `[MQTT ERROR]` - Connection errors

---

## 📁 Modified Files

### Server-side
1. **server_web.py**
   - Added: `handle_client_log()` function with SocketIO handler
   - Enhanced: `log_event()` with SocketIO broadcast
   - Enhanced: `ensure_message_db()` with logging
   - Enhanced: `save_message()` with detailed logging

### Client-side
1. **static/js/app.js**
   - Added: `logToSystemLog()` function
   - Added: `setupCompanyChangeListener()` function
   - Enhanced: `connect()` - MQTT connection logging
   - Enhanced: `disconnect()` - Disconnect logging
   - Enhanced: `switchGraphNode()` - Graph switching logging
   - Enhanced: `renderGraphNode()` - Graph update logging
   - Updated: `window.onload` - Initialize company listener

---

## 🗂️ Database Structure

### Main Database (iot_data.db)
- `users` table - User credentials and company assignments
- `companies` table - Company metadata

### Company Databases (messages_dbs/*.db)
- `messages` table per company with fields:
  - timestamp, type, node_id, sensor_id
  - flow, velocity, flow_day, flow_month, flow_year
  - details, company, node_status

---

## 🔍 How to Verify

### Check Separate Databases
```bash
# List all company databases
ls -la messages_dbs/

# Expected output:
# Company_1.db
# Company_2.db
# ... (one file per company)
```

### Check Logs
```bash
# View system logs
tail -f system.log

# Expected entries:
# 2026-05-21 HH:MM:SS,sss - INFO - Ensured company database: messages_dbs/Company_1.db
# 2026-05-21 HH:MM:SS,sss - INFO - Saved Status message for Node 1 (Company: Company_1)
# 2026-05-21 HH:MM:SS,sss - INFO - CLIENT: [COMPANY CHANGE] Switched to company: Company_2
```

### Test Company Switching
1. Open web UI in browser
2. Go to "Server Configuration" (admin only)
3. Change "Company ID" dropdown
4. Observe:
   - Graph clears
   - Status metrics reset
   - Node selectors update
   - System Logs tab shows change event

### Test Graph Updates
1. Select a node in "Live Graphs" tab
2. Observe:
   - Graph populates with data
   - System logs show "[GRAPH UPDATE]" entries
   - Data point count shown in logs

---

## 🚀 Usage Examples

### For Administrators
1. Monitor all companies' data in System Logs
2. Track MQTT connections per company
3. Diagnose issues using timestamp-coordinated logs
4. Export data per company from Historical DB tab

### For Company Users
1. See only their company's data
2. Switch between nodes to view different sensor data
3. All operations automatically logged for audit trail

---

## 📊 Sample Log Output

```
[08:15:23] [CLIENT] [08:15:22] [COMPANY CHANGE] Switched to company: Company_1
[08:15:24] [CLIENT] [08:15:23] [GRAPH RESET] Graph and live status cleared for company: Company_1
[08:15:25] [STATUS] [08:15:24] Received 128 bytes on EgSA/Company_1/1/Status
[08:15:25] Saved Status message for Node 1 (Company: Company_1) to database
[08:15:26] [CLIENT] [08:15:25] [GRAPH UPDATE] Switched graph to Node ID: 1
[08:15:26] [CLIENT] [08:15:25] [GRAPH UPDATE] Graph updated for Node 1 with 12 data points
```

---

## ⚙️ Configuration

### Company Node Mapping (app.js)
```javascript
const COMPANY_NODE_MAP = {
    Company_1: ['1','2','3'],
    Company_2: ['1','2']
};
```
Edit this to define which nodes are available per company.

---

## 🔐 Security Notes

- Each user sees only their assigned company's data
- EgSA_Supervisor can view all companies
- Database files are protected by OS file permissions
- All operations logged for audit trail
- SocketIO broadcasts limited to system logs (no sensitive data)

---

## 📝 Next Steps

1. **Monitor Logs**: Watch `system.log` during normal operation
2. **Test Multi-Company**: Add new companies and verify isolation
3. **Archive Old Data**: Plan database maintenance strategy
4. **Backup Logs**: Implement log rotation (system.log can grow large)
5. **Analytics**: Use logs for performance analysis

---

**Implementation Status**: ✅ COMPLETE
**Testing Status**: Ready for Production
**Date**: May 21, 2026
