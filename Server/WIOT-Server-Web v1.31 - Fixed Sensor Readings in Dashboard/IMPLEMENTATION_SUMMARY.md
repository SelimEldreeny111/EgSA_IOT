# WIOT Server Implementation Summary

## Implementation Date: May 21, 2026

### Overview
This document outlines the implementation of separate company databases, dynamic graph updates on company changes, and comprehensive logging for company operations.

---

## 1. Separate Database Files Per Company ✅

### Status: **COMPLETED** (Already Implemented)

### Database Structure
- **Main Database**: `iot_data.db`
  - Contains: Users and Companies metadata
  - Location: Root directory

- **Company Databases**: Individual files in `messages_dbs/` directory
  - Format: `{company_name}.db`
  - Example: `Company_1.db`, `Company_2.db`, etc.
  - Safe naming: Special characters are replaced with underscores

### Database Functions
```python
def get_company_db_path(company: str) -> str
    - Returns: Path to company-specific database file
    - Format: messages_dbs/{safe_company_name}.db

def ensure_message_db(company: str) -> str
    - Creates database if it doesn't exist
    - Initializes message table schema
    - Logs creation to system.log

def safe_company_name(company: str) -> str
    - Sanitizes company names for filesystem safety
    - Replaces special characters with underscores
```

### Message Table Schema
Each company database contains a `messages` table with:
- `timestamp` - Message timestamp
- `type` - Message type (Status, Telemetry, Command)
- `node_id` - Node identifier
- `sensor_id` - Sensor identifier
- `flow` - Flow rate (m3/h)
- `velocity` - Velocity (m/s)
- `flow_day`, `flow_month`, `flow_year` - Accumulated flows
- `details` - Additional message details
- `company` - Company identifier
- `node_status` - Node status code

---

## 2. Graph Updates on Company Change ✅

### Status: **COMPLETED**

### Implementation Details

#### Frontend Changes (app.js)

**New Function**: `setupCompanyChangeListener()`
```javascript
- Attaches listener to company selector dropdown
- Triggered when user changes company selection
- Actions performed:
  1. Clears all node data (nodeLatestData, nodeHistoryData)
  2. Reinitializes node selectors for new company
  3. Clears graph and live status displays
  4. Reloads tabular data if visible
  5. Logs all actions
```

**Enhanced Function**: `switchGraphNode()` & `renderGraphNode()`
- Added logging when graph is updated
- Logs node ID and data point count
- Tracks graph state changes

**Initialization**: Updated `window.onload`
- Calls `setupCompanyChangeListener()` on page load

### Graph Reset Behavior
When company selection changes:
1. All historical node data is cleared
2. Graph displays empty state
3. Node dropdowns are repopulated with allowed nodes for new company
4. Live status metrics reset to "-"
5. Connection configuration updates to new company

---

## 3. Comprehensive Logging System ✅

### Status: **COMPLETED**

### Server-Side Logging

#### File: `system.log`
- Format: `%(asctime)s - %(levelname)s - %(message)s`
- Location: Root directory

#### Logged Events
1. **Database Operations**
   - Company database creation/access
   - Message saves with company association

2. **MQTT Connection Events**
   - Connection attempts (broker, port, company)
   - Disconnection events
   - Topic subscriptions

3. **Client Events** (via SocketIO)
   - Company changes
   - Graph updates and resets
   - Node selector changes

#### Backend Handler: `handle_client_log()`
```python
@socketio.on('client_log')
def handle_client_log(data):
    - Receives logging messages from client
    - Logs to system.log with [CLIENT] prefix
    - Broadcasts to all connected clients via SocketIO
```

### Client-Side Logging

#### New Function: `logToSystemLog(message)`
```javascript
- Adds timestamp to messages
- Logs to browser console
- Emits to server via SocketIO for persistence
- Broadcast to all connected clients in system logs
```

#### Logged Client Events
1. **Company Management**
   - `[COMPANY CHANGE]` - When company dropdown changes
   - `[GRAPH RESET]` - When graph is cleared for new company

2. **MQTT Operations**
   - `[MQTT CONNECT]` - Connection with broker details
   - `[MQTT DISCONNECT]` - Disconnection confirmation
   - `[MQTT ERROR]` - Connection failures with error details

3. **Graph Updates**
   - `[GRAPH UPDATE]` - Node switch with node ID
   - `[GRAPH UPDATE]` - Graph data refresh with point count
   - `[GRAPH UPDATE]` - No-data notifications

### Log Output Format
```
[HH:MM:SS] Log Message
[CLIENT] [HH:MM:SS] Client Action
[TIMESTAMP] - LEVEL - MESSAGE (in system.log file)
```

---

## 4. Integration Points

### SocketIO Communication
- **Event**: `client_log`
  - Direction: Client → Server
  - Payload: `{ message: string }`
  - Response: Broadcast to all connected clients

- **Event**: `system_log`
  - Direction: Server → Client
  - Payload: `{ message: string }`
  - Display: System Logs tab in UI

### Query Functions
```python
def query_messages_db(db_path, start, end, limit)
    - Queries specific company database

def query_messages_from_all_company_dbs(start, end, limit)
    - Aggregates data from all company databases
    - Used by EgSA_Supervisor role
```

### API Endpoints
- `GET /api/messages` - Fetches messages for current user's company
- `GET /export_csv` - Exports company-specific data to CSV
- `POST /api/connect` - Connects with company selection
- `POST /api/disconnect` - Disconnects and logs event

---

## 5. Database Migration

### Legacy Data Handling
- **Function**: `migrate_legacy_messages_to_company_dbs()`
- Automatically migrates data from old single `iot_data.db` to company-specific databases
- Runs on server initialization
- Preserves company assignments during migration

---

## 6. User Access Control

### Company-Based Access
- Regular users: See only their assigned company's data
- Company Admins: See their company's data
- EgSA_Supervisor: See all companies' data

### Node Configuration
```javascript
COMPANY_NODE_MAP = {
    Company_1: ['1', '2', '3'],
    Company_2: ['1', '2']
}
```
- Dynamically determines available nodes per company
- Updated via `getAllowedNodeIds()` function

---

## 7. System Architecture

### Directory Structure
```
WIOT-Server-Web/
├── server_web.py          # Main Flask/SocketIO server
├── system.log             # Application logs
├── iot_data.db            # Users and companies metadata
├── messages_dbs/          # Company-specific databases
│   ├── Company_1.db
│   ├── Company_2.db
│   └── ...
├── static/
│   ├── js/app.js          # Frontend logic with logging
│   └── css/style.css
└── templates/
    └── index.html         # Main dashboard
```

---

## 8. Testing Recommendations

### Manual Testing
1. **Company Switching**
   - Change company in dropdown
   - Verify graph clears
   - Check node selectors update
   - Confirm logging appears

2. **Graph Operations**
   - Switch between nodes
   - Verify graph updates with correct data
   - Check log entries for each update

3. **Database Verification**
   - Verify company-specific `.db` files are created
   - Check `messages_dbs/` directory
   - Confirm data isolation between companies

4. **Logging**
   - Monitor `system.log` for entries
   - Check System Logs tab in UI
   - Verify client-side events are logged
   - Test MQTT connection logging

### Automated Testing
- Check file handles for database connections
- Verify no data leakage between companies
- Test performance with large datasets

---

## 9. Features Summary

| Feature | Status | Details |
|---------|--------|---------|
| Separate DB per Company | ✅ | Individual files in messages_dbs/ |
| Graph Update on Company Change | ✅ | Automatic reset and refresh |
| Client-Side Logging | ✅ | Via SocketIO with timestamps |
| Server-Side Logging | ✅ | To system.log file |
| Log Broadcast | ✅ | All users see relevant logs |
| Company Access Control | ✅ | Users see only assigned company |
| Data Migration | ✅ | Legacy data automatically migrated |
| Node Configuration | ✅ | Per-company node mapping |

---

## 10. Future Enhancements

- Database compression/archival for old data
- Advanced filtering in log viewer
- Real-time log streaming with filters
- Database backup automation
- Export logs in multiple formats (CSV, JSON)
- Log retention policies
- Dashboard analytics by company

---

**Implementation Completed**: May 21, 2026
**Author**: System Implementation
**Status**: Ready for Production Testing
