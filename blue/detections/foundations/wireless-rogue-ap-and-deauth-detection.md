# Review wireless identity and management-frame anomalies

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Is an observed access point or management-frame pattern inconsistent with the managed wireless design?

## Evidence to request

Wireless IDS/controller observations, radio channel and coverage, BSSID/SSID inventory, RADIUS/authentication records, switch location and authorized maintenance.

## Reasoning procedure

- Compare AP identity, channel, security settings and wired attachment with the inventory. An SSID name can be duplicated legitimately and is not an authentication of the AP.
- Examine deauthentication/disassociation bursts with client impact and radio conditions. The transmitter address can be spoofed; a frame observation is not reliable actor attribution.
- Relate affected clients to later association and authentication outcomes, accounting for roaming and controller handoffs.
- Use wireless management telemetry for radio-layer claims. A wired flow sensor normally cannot establish what management frames were transmitted.
- Document monitored channels, sensor placement and management-frame protection configuration before negative conclusions.

## Alternatives and limits

Roaming, interference, load balancing, device faults and neighboring networks produce similar symptoms. Randomized client addresses complicate tracking.

## Discriminating checks

Test synthetic managed AP changes, a neighboring same-name network, a controller-driven disconnect and an unexplained frame burst. Do not transmit disruptive wireless frames. Radio containment or AP shutdown requires network-owner authority and impact review.

## Concrete observation contract

For retained monitor-mode capture, use parser-supported `wlan.fc.type_subtype`,
`wlan.bssid`, `wlan.ssid`, `wlan.sa`, `wlan.da` and `wlan.fixed.reason_code`. Preserve
capture channel, time and loss information. A source MAC field is not authenticated
sender identity, and a missed channel can conceal the relevant exchange.

Correlate controller association and RADIUS records rather than relying on SSID alone.
`Called-Station-Id` and `Calling-Station-Id` identify different sides of the access
exchange; verify formatting and MAC randomization for the deployed service. Record
Protected Management Frames policy and observed negotiation. Roaming, AP maintenance and
RF disruption can explain disconnection bursts. No transmission is needed to check this
card; [specialist telemetry](../../skills/soc-detection-engineering/references/telemetry-specialist.md)
describes the passive evidence contract and its limits.
