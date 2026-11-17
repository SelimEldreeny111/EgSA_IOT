// Help articles, guided-tour steps and release notes shown in the dashboard (R2.3, point 30).
// Articles are short task-oriented pages; keep them in plain language for farm and utility staff.

export const ARTICLES = [
  { id: "start", title: "Getting started", body: [
    ["p", "The WIOT Control Center shows what your field nodes measure — soil moisture, salinity, water flow, battery — and lets authorised staff send commands such as opening a valve."],
    ["p", "Choose the company and region at the top. The left menu groups pages into Operations (daily work), Insights (history and analysis) and Settings."],
    ["ul", ["Smart farm: fields, irrigation advice and valves on the map.", "Alerts: what needs attention now.", "Node health: which devices need a visit.", "Command center: send and follow commands."]],
  ] },
  { id: "alerts", title: "Alerts and notifications", body: [
    ["p", "The server checks every node once a minute. Built-in alerts cover silent nodes, low battery, unstable flow readings, leaks and no-flow on valve nodes, frost and heat forecasts and security events."],
    ["p", "Add your own rules on Rules & notifications — for example soil moisture below 18 % for 30 minutes. Each rule opens an alert like the built-in ones."],
    ["p", "Channels send alerts outside the dashboard: e-mail, Telegram, SMS, WhatsApp or Microsoft Teams. Use \"Send test\" after setting one up."],
  ] },
  { id: "commands", title: "Commands and power modes", body: [
    ["p", "Nodes that sleep to save battery only listen for a few seconds after each report. \"Auto\" delivery sends a command at once when the node is likely awake and otherwise queues it for its next wake."],
    ["p", "A command is acknowledged when the node replies. If no reply comes within the time allowed for its power mode, the command is marked \"No reply\" — check the node on Node health."],
  ] },
  { id: "health", title: "Node health score", body: [
    ["p", "Each node gets a score from 100. Points are removed for a battery that will reach 3.3 V within 30 days, watchdog or power resets, missed reports, an untrusted clock, commands without a reply and an interval that differs from the one set."],
    ["p", "Good is 80 or more, fair 60 to 79, poor below 60. The Findings column says what to check."],
  ] },
  { id: "reports", title: "Monthly reports", body: [
    ["p", "Reports summarise a month per node: reports received, battery, water delivered, soil moisture, salinity and alerts. Download them as Excel or PDF."],
    ["p", "On the 1st of each month the server builds last month's report and e-mails it to channels subscribed to \"Monthly report\"."],
  ] },
  { id: "security", title: "Two-factor sign-in and sessions", body: [
    ["p", "Turn on two-factor sign-in on the Security page: scan or type the key into an authenticator app, then enter the code it shows. Keep the recovery codes in a safe place."],
    ["p", "The Security page also lists where you are signed in; sign out any browser you do not recognise. Administrators can invite people by e-mail and limit which pages each person sees."],
  ] },
  { id: "integrations", title: "Integrations and data export", body: [
    ["p", "Readings can be forwarded to ThingsBoard, Azure IoT Hub or any HTTPS endpoint. Power BI and Excel can pull a daily table with an API token."],
    ["p", "Webhooks and API tokens are on Organization → API & webhooks."],
  ] },
  { id: "satellite", title: "Satellite data (Sentinel and EUMETSAT)", body: [
    ["p", "The satellite viewer at the top of the Satellite page draws the Copernicus Browser layers on the farm map: true and false colour, NDVI, moisture, NDWI, SWIR, wildfires, scene classification and more for Sentinel-2, radar for Sentinel-1 and colour or temperature for Sentinel-3. Choose the satellite, a date and a layer; the legend opens under the layer. Custom builds your own band composite or index. Opacity, field outlines, Download image and Open in Copernicus Browser are above the map."],
    ["p", "Satellite data over this farm shows every Sentinel-1, -2 and -3 and Landsat pass of the last months, one cell per day (Sentinel-2 and Landsat coloured by cloud), plus the number of EUMETSAT products. Click a day to open it in the viewer."],
    ["p", "The page also shows the crop health (NDVI) of every field after each clear Sentinel-2 pass, every 2 to 5 days in Egypt. NDVI below 0.15 is bare soil; above 0.7 is a dense green crop. A field that stays lower than its neighbours deserves a visit."],
    ["p", "The server takes NDVI either from the Copernicus Sentinel Hub (with a Copernicus Data Space account) or, with no account, from the open Sentinel-2 archive (setting WIOT_SATELLITE_PROVIDER=open). Clouds and shadows are removed before the average is taken."],
    ["ul", ["Copernicus catalogue: Sentinel-1 radar, Sentinel-2 and Sentinel-3 passes over the farm; “Open in browser” shows the pass in the Copernicus Browser.", "EUMETSAT Data Store: Meteosat and Metop land surface temperature, rainfall, albedo and soil moisture products over the farm; administrators can download them when the EUMETSAT API key is set.", "Find pivots: detects green centre-pivot circles in an image of a new farm."]],
  ] },
  { id: "status", title: "Service status", body: [
    ["p", "The public page /status shows whether the platform, the field network link and data ingestion are working, with 30 days of availability. Supervisors see more detail on System health."],
  ] },
  { id: "devices", title: "Third-party devices", body: [
    ["p", "The Devices page connects climate, water-quality and tank sensors from other makers. They report JSON over MQTT or through a LoRaWAN network server, and their readings are kept next to those of the WIOT nodes. Administrators register devices; everyone else sees their status and readings."],
    ["p", "MQTT: register the device, then publish to the topic shown for it (wiotx/<company>/<device ID>/up) on the same broker as the nodes. The broker is public, so a device is signed by default: it sends {\"p\": \"<JSON text>\", \"sig\": \"<hex>\"}, where p holds ts (Unix seconds) and the readings, and sig is HMAC-SHA256 of the topic, a line break and p, keyed with the device secret. Each message must be newer than the last one stored."],
    ["p", "The device secret is shown once, when the device is registered or the secret is rotated. Copy it to the device at once; rotate it if it may have leaked."],
    ["p", "Unsigned devices publish plain JSON. Anyone who can reach the broker could send the same, so their readings are stored but marked untrusted. Use signed devices for anything you act on."],
    ["p", "LoRaWAN: create a connection key for The Things Stack or ChirpStack on the Devices page; it is shown once. In The Things Stack add a webhook with Uplink message enabled; in ChirpStack add an HTTP integration with JSON encoding. Point it at the address shown and send the key in the Authorization header. Devices are matched by their DevEUI."],
    ["p", "Payload mapping: every reading is stored as a metric from the catalog, such as air temperature, relative humidity, CO₂, soil moisture, pH or tank level, each in one unit. Fields named like a catalog metric or a common vendor name (temperature, humidity, co2) are mapped automatically. Otherwise map a payload field to a metric, with an optional scale and offset. Values outside a metric's valid range are rejected."],
    ["p", "Each device has a report interval. After three missed reports, and never sooner than 15 minutes, a \"Device silent\" warning opens on the Alerts page. It clears with the next reading."],
  ] },
  { id: "greenhouses", title: "Greenhouse layouts", body: [
    ["p", "The Greenhouses page draws your houses on the farm map. Each house is split into zones, and each zone holds benches (or rows and gutters). The layout is separate from the Smart farm fields: greenhouse zones do not change irrigation advice, water accounts or reports."],
    ["p", "Administrators edit the layout; everyone else sees it with the latest readings. Pick a tool, then draw on the map: a house first, zones inside a house, benches inside a zone."],
    ["p", "Rectangle: click one corner, click the next corner along one side, then click a third time to set the width. The rectangle follows the direction of the first side, so it can match a building that is not aligned north–south."],
    ["p", "Polygon: click each corner in turn and close the shape on the first corner. Use it for houses and zones that are not rectangular."],
    ["p", "Bench rows: select a zone, set the bench width, the path between benches and the margin from the zone edge, and choose the direction. The map previews how many benches fit; Add benches lays them out in one step."],
    ["p", "To change a shape, select it and drag its corners. A zone or bench that sticks out of its house or zone is still saved, but listed as a warning so you can fix it."],
    ["p", "Sensors: select a house, zone or bench and attach registered devices or WIOT nodes. Latest readings then shows the mean of the latest value of each sensor attached to it or to anything inside it; values older than 3 hours are left out."],
    ["p", "Save stores the whole layout. If someone else saved in the meantime, your save is refused instead of overwriting their work: reload the layout and apply your edits again. Unsaved edits are kept as a draft in this browser tab (closing the tab discards them)."],
  ] },
];

export const TOUR = [
  { sel: '#rail a[data-route="farm"]', title: "Smart farm", text: "Your fields on the map with soil moisture, irrigation advice and valves." },
  { sel: '#rail a[data-route="greenhouses"]', title: "Greenhouses", text: "Draw houses, zones and benches on the map and see the readings of the sensors attached to each." },
  { sel: '#rail a[data-route="alerts"]', title: "Alerts", text: "Everything that needs attention. The red number counts alerts nobody has acknowledged yet." },
  { sel: '#rail a[data-route="health"]', title: "Node health", text: "A score per device: battery trend, resets, missed reports, clock and commands." },
  { sel: '#rail a[data-route="devices"]', title: "Devices", text: "Third-party sensors over MQTT or LoRaWAN: when each one last reported and what it measured." },
  { sel: '#rail a[data-route="notify"]', title: "Rules & notifications", text: "Create your own alert rules and send alerts by e-mail, Telegram, SMS or WhatsApp." },
  { sel: '#rail a[data-route="commands"]', title: "Command center", text: "Open valves and change settings. Commands wait for sleeping nodes automatically." },
  { sel: '#rail a[data-route="reports"]', title: "Reports", text: "Monthly reports per node in Excel and PDF." },
  { sel: "#sel-region", title: "Region", text: "Switch between the regions of your company here." },
  { sel: '#rail a[data-route="help"]', title: "Help", text: "Guides for every page, this tour and the list of what is new." },
];

// The "What's new" card opens once for each new WHATS_NEW[0].version (compared as text in help.js).
export const WHATS_NEW = [
  { version: "2.8", title: "Greenhouses and third-party devices", items: [
    "Devices page: connect climate, water-quality and tank sensors from other makers over MQTT or LoRaWAN (The Things Stack, ChirpStack).",
    "Signed MQTT messages, readings mapped to one metric catalog, and an alert when a device stops reporting.",
    "Greenhouses page: draw houses, zones and benches on the map and attach sensors to see their readings on the layout.",
  ] },
  { version: "2.7", title: "Earth observation", items: [
    "Field NDVI from the open Sentinel-2 archive, with no account needed.",
    "Copernicus catalogue of Sentinel-1, -2 and -3 passes over your farm, with links to the Copernicus Browser.",
    "EUMETSAT Data Store search and downloads: land surface temperature, rainfall, albedo, soil moisture.",
  ] },
  { version: "2.4–2.6", title: "Agronomy, crop records, field apps", items: [
    "Irrigation planning with crop stages, soil, salinity and deficit programmes; water accounts, wells and quotas.",
    "Crop care, Sentinel-2 crop health, pivot detection, regional dashboard and the Arabic farmer view.",
    "Installable app with offline mode and push alerts, commissioning wizard, maintenance work orders.",
  ] },
  { version: "2.3", title: "Security, alerts by message, reports", items: [
    "Two-factor sign-in, a list of your sessions and single sign-on with your organisation's account.",
    "Invitations by e-mail and page access per user.",
    "Your own alert rules, and alerts by e-mail, Telegram, SMS, WhatsApp or Teams.",
    "Monthly reports in Excel and PDF, sent automatically on the 1st.",
    "Company branding, usage per month, and forwarding to ThingsBoard or Azure IoT Hub.",
  ] },
  { version: "2.2", title: "Operations", items: [
    "Node health scores with battery trend and findings.",
    "System health for supervisors and a public status page.",
    "Faster long-range charts from hourly and daily summaries.",
    "Intervals reported by a node are checked against the ones set, and corrected at its next wake.",
  ] },
  { version: "2.1", title: "Field operations", items: [
    "Automatic clock synchronisation, Auto command delivery and per-mode reply times.",
    "Leak, no-flow, night-flow, frost and heat alerts; a 7-day irrigation index per field.",
    "Encrypted backups.",
  ] },
];
