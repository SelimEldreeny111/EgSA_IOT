# WIOT Platform — integration examples

All examples use an **API token** (Organization → API & webhooks → Create token). A read token can call every
`GET` endpoint of its company; a write token can also send commands. Send it as `Authorization: Bearer wiot_…`.
The full, interactive API reference is at `https://<server>/api/docs`.

Replace `https://wiot.example.org` with your server address and `Company_1` with your company ID.

## Daily table (Power BI, Excel, data warehouse)

`GET /api/v2/feeds/daily.csv?company=Company_1&days=365` returns one row per node and day with the number of
valid readings, mean, minimum and maximum of flow, battery voltage, soil moisture, soil temperature and salinity (EC).

### Power BI Desktop / Excel Power Query (M)

```m
let
    Token = "wiot_xxxxxxxxxxxxxxxx",
    Source = Csv.Document(
        Web.Contents("https://wiot.example.org/api/v2/feeds/daily.csv",
            [Query = [company = "Company_1", days = "365"],
             Headers = [Authorization = "Bearer " & Token]]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {{"day", type date}, {"node_id", Int64.Type},
        {"flow_mean", type number}, {"battery_voltage_mean", type number}, {"soil_moisture_mean", type number},
        {"electrical_conductivity_mean", type number}})
in
    Typed
```

In the Power BI service, set the data source credential to **Anonymous** (the token travels in the header) and
schedule a refresh once a day.

### Python

```python
import io, urllib.request
import pandas as pd

req = urllib.request.Request("https://wiot.example.org/api/v2/feeds/daily.csv?company=Company_1&days=90",
                             headers={"Authorization": "Bearer wiot_xxxxxxxxxxxxxxxx"})
with urllib.request.urlopen(req) as r:
    daily = pd.read_csv(io.BytesIO(r.read()), parse_dates=["day"])
print(daily.groupby("node_id")["soil_moisture_mean"].describe())
```

### PowerShell

```powershell
$h = @{ Authorization = "Bearer wiot_xxxxxxxxxxxxxxxx" }
Invoke-WebRequest "https://wiot.example.org/api/v2/feeds/daily.csv?company=Company_1&days=30" -Headers $h -OutFile daily.csv
Import-Csv daily.csv | Where-Object { [double]$_.battery_voltage_min -lt 3.4 } | Format-Table day, node_id, battery_voltage_min
```

### curl

```bash
curl -H "Authorization: Bearer wiot_xxxxxxxxxxxxxxxx" \
  "https://wiot.example.org/api/v2/feeds/daily.csv?company=Company_1&days=30" -o daily.csv
```

## Live readings and history

| Need | Endpoint |
|---|---|
| Latest reading of every node | `GET /api/v2/fleet?company=Company_1&region=Region_1` |
| Chart series (any range; > 7 days reads the summaries) | `GET /api/v2/nodes/2/series?metric=soil_moisture&hours=720&points=360` |
| Raw messages, paged | `GET /api/v2/messages?company=Company_1&page=1&page_size=500` |
| Raw export | `GET /api/v2/export.csv?company=Company_1&start=2026-10-01&end=2026-11-01` |
| Monthly report | `GET /api/v2/reports/monthly?company=Company_1&month=2026-10&format=xlsx` (or `pdf`, `json`) |
| Node health scores | `GET /api/v2/fleet/health?company=Company_1` |
| Open alerts | `GET /api/v2/alerts?company=Company_1` |

## Push instead of pull

* **Webhooks** (Organization → API & webhooks): signed JSON (`X-WIOT-Signature: sha256=…`, HMAC of the body with
  the webhook secret) for telemetry, alerts, commands, automation and flash events.
* **Forwarding** (Settings → Integrations): every reading to ThingsBoard (device API), Azure IoT Hub
  (device-to-cloud over HTTPS with a SAS token) or any HTTPS endpoint.

### Verify a webhook signature (Python)

```python
import hashlib, hmac

def valid(secret: str, body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
```

## Sending a command (write token)

```bash
curl -X POST -H "Authorization: Bearer wiot_xxxxxxxxxxxxxxxx" -H "Content-Type: application/json" \
  -d '{"company":"Company_1","region":"Region_1","node_id":2,"cmd_type":"VALVE","cmd_data":1,"delivery":"auto"}' \
  https://wiot.example.org/api/v2/commands
```

`delivery: "auto"` sends at once when the node is probably listening and otherwise queues the command for the
node's next wake. Follow it with `GET /api/v2/commands/{request_id}?company=Company_1&region=Region_1&node_id=2`.
